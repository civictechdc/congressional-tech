"""Durable page text for CT's body-text consumer, using spicy-docs page APIs.

These are pre-cleanup observations, never completed body readings. Rasters and
provider objects are omitted; native spans needed by shared glyph accounting stay.
One writer owns a source/policy directory. Files survive transient batch cleanup.
"""
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from congress_api.parsers import body_text
from congress_api.parsers.body_text import CheckpointError


def adapter(root):
    """The producer supplies durable storage; parsers only call this extraction adapter."""
    if root is None:
        return None

    def wrap(extractor, rule, run):
        if rule.checkpoint_identity is None:
            raise ValueError('Page checkpointing requires an explicit reproducible rule identity')
        identity = dict(rule=rule.checkpoint_identity, strategy=type(rule.strategy).__qualname__,
            code=sha256(Path(body_text.__file__).read_bytes()).hexdigest(),
            adapter=sha256(Path(__file__).read_bytes()).hexdigest(),
            dependencies={name: version(name) for name in ('spicy-docs', 'pymupdf', 'pillow')})
        overrides = {}
        for number, replacement in run.overrides.items():
            if replacement.checkpoint_identity is None:
                raise ValueError('Page replacements require an explicit reproducible rule identity')
            overrides[number] = dict(rule=replacement.checkpoint_identity,
                                     strategy=type(replacement.strategy).__qualname__)
        return CheckpointedExtractor(extractor, root=root, identity=identity, run=run, overrides=overrides)

    return wrap


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def atomic_json(path, value):
    path = Path(path)
    with NamedTemporaryFile(dir=path.parent, prefix='.', suffix='.partial', delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temp, path)
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temp.unlink(missing_ok=True)


def pack(result):
    observations = []
    for observation in result.content.observations:
        observations.append(dict(id=observation.id, text=observation.text,
            configuration=observation.configuration,
            raw=observation.raw if observation.id == 'native' else None,
            blocks=[asdict(b) for b in observation.blocks], text_format=observation.text_format,
            issues=[asdict(i) for i in observation.issues],
            inspected_region=asdict(observation.inspected_region) if observation.inspected_region else None))
    return dict(metadata=result.metadata, blocks=[asdict(b) for b in result.content.blocks], observations=observations)


def unpack(value):
    from spicy_docs.extraction.model import Box, TextBlock, ProcessingIssue, Observation, PageContent, PageResult
    def box(v):
        return None if v is None else Box(**v)
    def block(v):
        return TextBlock(**dict(v, box=box(v['box']), inspected_region=box(v['inspected_region'])))
    observations = tuple(Observation(**dict(o, blocks=tuple(block(b) for b in o['blocks']),
        issues=tuple(ProcessingIssue(**dict(i, box=box(i['box']))) for i in o['issues']),
        inspected_region=box(o['inspected_region']))) for o in value['observations'])
    return PageResult(value['metadata'], PageContent(tuple(block(b) for b in value['blocks']), observations))


class CheckpointedExtractor:
    """Adapt DocumentExtractor's selected-page stream to the existing rendition cleanup."""

    def __init__(self, extractor, *, root, identity, run, overrides=None):
        self.extractor, self.root, self.identity, self.run = extractor, Path(root), identity, run
        self.overrides = overrides or {}

    def _page_identity(self, identity, number):
        replacement = self.overrides.get(number)
        return identity if replacement is None else dict(identity, page_override=replacement)

    def _page_path(self, directory, identity, number):
        if number in self.overrides:
            directory = directory / 'overrides' / sha256(encoded(self._page_identity(identity, number))).hexdigest()
        return directory / f'page-{number:06d}.json'

    def extract(self, source, *, media_type):
        import fcntl
        identity = dict(self.identity, source_sha256=self.run.source_sha256 or sha256(source).hexdigest(), source_bytes=len(source),
                        media_type=media_type, checkpoint_schema=1)
        directory = self.root / identity['source_sha256'] / sha256(encoded(identity)).hexdigest()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / 'writer.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                attempt = uuid4().hex
                attempt_identity = dict(identity=identity, page_overrides=self.overrides)
                atomic_json(directory / f'attempt-{attempt}.started.json', attempt_identity)
                try:
                    yield from self._extract(source, media_type, directory, identity)
                    atomic_json(directory / f'attempt-{attempt}.finished.json',
                                dict(attempt_identity, failed_pages=self.run.failed))
                except BaseException as error:
                    atomic_json(directory / f'failure-{uuid4().hex}.json',
                                dict(attempt_identity, error=type(error).__name__, detail=str(error)))
                    raise
        except OSError as error:
            raise CheckpointError(f'Checkpoint storage failed: {error}') from error

    def _load(self, path, identity):
        try:
            record = json.loads(path.read_bytes())
            payload = record['payload']
            if record['sha256'] != sha256(encoded(payload)).hexdigest() or payload['identity'] != identity:
                raise ValueError('identity or digest mismatch')
            result = unpack(payload['result'])
            meta = result.metadata
            if not isinstance(meta, dict) or not {
                    'page', 'page_count', 'source_sha256', 'source_size_bytes', 'media_type'} <= meta.keys():
                raise ValueError('missing page metadata')
            if (any(not isinstance(b.text, str) for b in result.content.blocks)
                    or any(not isinstance(o.configuration, dict) or not isinstance(o.text, str)
                           for o in result.content.observations)):
                raise ValueError('invalid page content')
            return result
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CheckpointError(f'Invalid checkpoint {path}: {error}') from error

    def _extract(self, source, media_type, directory, identity):
        cached = {}
        count = None
        # Validate selected committed records before using any. Older policies remain untouched.
        replaced = {f'page-{n:06d}.json' for n in self.overrides}
        paths = [path for path in sorted(directory.glob('page-*.json')) if path.name not in replaced]
        paths += [path for n in sorted(self.overrides)
                  if (path := self._page_path(directory, identity, n)).exists()]
        for path in paths:
            try:
                number = int(path.stem.removeprefix('page-'))
            except ValueError as error:
                raise CheckpointError(f'Conflicting page checkpoint: {path}') from error
            result = self._load(path, self._page_identity(identity, number))
            meta = result.metadata
            n, total = meta['page'], meta['page_count']
            if (any(not isinstance(v, int) or isinstance(v, bool) for v in (n, total)) or not 1 <= n <= total
                    or n in cached or (count is not None and count != total)
                    or path.name != f'page-{n:06d}.json'
                    or meta['source_sha256'] != identity['source_sha256']
                    or meta['source_size_bytes'] != len(source) or meta['media_type'] != media_type):
                raise CheckpointError(f'Conflicting page checkpoint: {path}')
            count = total
            cached[n] = path
        if count is not None and any(n > count for n in self.overrides):
            raise CheckpointError('Page override is outside the source page count')
        missing = None if count is None else [n for n in range(1, count + 1) if n not in cached]
        pages = self.extractor.extract(source, media_type=media_type, pages=missing) if missing != [] else iter(())
        try:
            next_result = None
            if count is None:
                next_result = next(pages, None)
                if next_result is None:
                    raise ValueError('PDF yielded no pages')
                count = next_result.metadata['page_count']
            for number in range(1, count + 1):
                if number in cached:
                    result = self._load(cached[number], self._page_identity(identity, number))
                    self.run.observe(result.content, number)
                    if self.run.evidence:
                        self.run.evidence(dict(event='page_reused', page=number, checkpoint=str(cached[number])))
                else:
                    if next_result is None:
                        next_result = next(pages, None)
                    result = next_result
                    if result is None or result.metadata['page'] != number or result.metadata['page_count'] != count:
                        raise CheckpointError('Incomplete or conflicting extracted page sequence')
                    if number not in self.run.failed:
                        try:
                            payload = dict(identity=self._page_identity(identity, number), result=pack(result))
                            path = self._page_path(directory, identity, number)
                            path.parent.mkdir(parents=True, exist_ok=True)
                            atomic_json(path,
                                        dict(payload=payload, sha256=sha256(encoded(payload)).hexdigest()))
                        except (TypeError, ValueError) as error:
                            raise CheckpointError(f'Cannot retain page {number}: {error}') from error
                    else:
                        atomic_json(directory / f'failure-{number:06d}-{uuid4().hex}.json',
                                    dict(page=number, identity=self._page_identity(identity, number), error=self.run.errors[number],
                                         detail=self.run.diagnostics[number]))
                    # Persist this page before advancing to any potentially failing page.
                yield result
                if number not in cached:
                    next_result = None
            if next(pages, None) is not None:
                raise CheckpointError('Extra extracted page')
        finally:
            close = getattr(pages, 'close', None)
            if close:
                close()
