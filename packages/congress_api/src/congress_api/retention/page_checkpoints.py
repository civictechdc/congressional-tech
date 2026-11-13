"""Durable page text for CT's body-text consumer, using spicy-docs page APIs.

These are pre-cleanup observations, never completed body readings. Rasters and
provider objects are omitted; native spans needed by shared glyph accounting stay.
One writer owns a source/policy directory. Files survive transient batch cleanup.
"""
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4


class CheckpointError(RuntimeError):
    """Checkpoint storage or integrity failed; this is not a source-reading verdict."""


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

    def __init__(self, extractor, *, root, identity, run):
        self.extractor, self.root, self.identity, self.run = extractor, Path(root), identity, run

    def extract(self, source, *, media_type):
        import fcntl
        identity = dict(self.identity, source_sha256=sha256(source).hexdigest(), source_bytes=len(source),
                        media_type=media_type, checkpoint_schema=1)
        directory = self.root / identity['source_sha256'] / sha256(encoded(identity)).hexdigest()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / 'writer.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                attempt = uuid4().hex
                atomic_json(directory / f'attempt-{attempt}.started.json', dict(identity=identity))
                try:
                    yield from self._extract(source, media_type, directory, identity)
                    atomic_json(directory / f'attempt-{attempt}.finished.json',
                                dict(identity=identity, failed_pages=self.run.failed))
                except BaseException as error:
                    atomic_json(directory / f'failure-{uuid4().hex}.json',
                                dict(error=type(error).__name__, detail=str(error), identity=identity))
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
        # Validate all committed records before using any. Partial writes are never committed.
        for path in sorted(directory.glob('page-*.json')):
            result = self._load(path, identity)
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
                    result = self._load(cached[number], identity)
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
                            payload = dict(identity=identity, result=pack(result))
                            atomic_json(directory / f'page-{number:06d}.json',
                                        dict(payload=payload, sha256=sha256(encoded(payload)).hexdigest()))
                        except (TypeError, ValueError) as error:
                            raise CheckpointError(f'Cannot retain page {number}: {error}') from error
                    else:
                        atomic_json(directory / f'failure-{number:06d}-{uuid4().hex}.json',
                                    dict(page=number, identity=identity, error=self.run.errors[number],
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
