"""One deterministic baseline clusterer: identical normalized text groups.

Groups selected versions by SHA-256 of casefolded, whitespace-collapsed text;
an identical-text group spanning outlets is a syndication signal. The honest
limitation is part of the contract (C9 note): such clusters do NOT prove
independent reporting and do NOT assert permanent event identity — they only
say "these stored texts are the same after normalization". Every version with
text joins exactly one story in the run (C7); metadata-only versions carry no
text and cannot be grouped by this method, so they join no story.
"""
from hashlib import sha256

from news_lake.context import AdapterContext, adapter_namespace, build_run, named_id
from news_lake.contract.records import validate_shape

NAMESPACE = adapter_namespace('analysis:cluster')
PROCESSOR = 'cluster-identical-text'
PROCESSOR_VERSION = 'identical-text-1'
CONFIG = {'normalization': 'casefold + collapse-whitespace', 'grouping': 'exact-normalized-text'}


def normalize_text(text):
    return ' '.join(text.casefold().split())


def text_group_key(text):
    return sha256(normalize_text(text).encode('utf-8')).hexdigest()


def cluster(versions, context=None, mode='reprocess'):
    """Group versions by identical normalized text; emits run + stories + members.

    Inputs are the versions in id order (documented normalization for the run
    input hash); run/story/member ids are deterministic, so replaying the same
    selection reproduces identical records.
    """
    context = context if context is not None else AdapterContext()
    ordered = sorted(versions, key=lambda version: version['id'])
    run = build_run(
        NAMESPACE, context,
        processor=PROCESSOR, processor_version=PROCESSOR_VERSION, config=dict(CONFIG),
        inputs=[{'kind': 'version', 'id': version['id']} for version in ordered],
        mode=mode,
    )
    groups = {}
    for version in ordered:
        if 'text' in version:
            groups.setdefault(text_group_key(version['text']), []).append(version)
    stories, members = [], []
    for key in sorted(groups):
        story = {
            'kind': 'story',
            'id': named_id(NAMESPACE, f'story:{run["id"]}:{key}'),
            'recorded_at': run['recorded_at'],
            'run_id': run['id'],
            'label': f'identical-text:{key[:12]}',
        }
        stories.append(validate_shape(story))
        for version in groups[key]:
            members.append(validate_shape({
                'kind': 'story_member',
                'id': named_id(NAMESPACE, f'member:{run["id"]}:{version["id"]}'),
                'recorded_at': run['recorded_at'],
                'story_id': story['id'],
                'version_id': version['id'],
                'run_id': run['id'],
            }))
    return {'run': run, 'stories': stories, 'story_members': members}
