"""Deterministic offline baseline labels: keyword topic and tone classification.

This is a BASELINE PLACEHOLDER, not a calibrated classifier: it emits one
`topic` and one `tone` classification per version that carries text, using the
small documented keyword sets in CONFIG. Classifications are method-specific
(C6): another producer (model, human coding, or a different taxonomy) may label
the same version differently, and these labels assert nothing about an
outlet's editorial intent. The run, taxonomy_version, and keyword sets are
recorded so consumers can identify exactly which method produced a label.
"""
import re

from news_lake.context import AdapterContext, adapter_namespace, build_run, named_id
from news_lake.contract.records import validate_shape

NAMESPACE = adapter_namespace('analysis:labels')
PROCESSOR = 'classify-keywords'
PROCESSOR_VERSION = 'keyword-baseline-1'

CONFIG = {
    'taxonomy_version': 'keyword-taxonomy-1',
    'dimensions': ['topic', 'tone'],
    # Casefolded whole-word keyword counts; the highest count wins and ties
    # break alphabetically by label. No keyword match yields 'other'.
    'topic_keywords': {
        'budget': ['budget', 'appropriation', 'deficit', 'spending'],
        'education': ['education', 'school', 'student', 'teacher', 'university'],
        'election': ['ballot', 'campaign', 'election', 'vote', 'voter'],
        'health': ['health', 'hospital', 'insurance', 'medicaid', 'medicare'],
    },
    'topic_default': 'other',
    # Only the words below move tone off neutral; ties yield 'neutral'.
    'tone_keywords': {
        'positive': ['approve', 'benefit', 'celebrate', 'success', 'victory'],
        'negative': ['criticize', 'fail', 'loss', 'protest', 'scandal'],
    },
    'tone_default': 'neutral',
    'matching': 'casefolded whole-word keyword counts; highest wins, ties alphabetical',
}


def _keyword_counts(text, keyword_sets):
    folded = text.casefold()
    counts = {}
    for label in sorted(keyword_sets):
        hits = sum(
            len(re.findall(rf'\b{re.escape(keyword)}\b', folded))
            for keyword in keyword_sets[label]
        )
        if hits:
            counts[label] = hits
    return counts


def _topic(text):
    counts = _keyword_counts(text, CONFIG['topic_keywords'])
    if not counts:
        return CONFIG['topic_default']
    return min(counts, key=lambda label: (-counts[label], label))


def _tone(text):
    counts = _keyword_counts(text, CONFIG['tone_keywords'])
    positive = counts.get('positive', 0)
    negative = counts.get('negative', 0)
    if positive > negative:
        return 'positive'
    if negative > positive:
        return 'negative'
    return CONFIG['tone_default']


def classify(versions, context=None, mode='reprocess'):
    """Label each version with text as one topic and one tone classification.

    Versions are consumed in id order, and every version (including
    metadata-only ones) appears in the run inputs, so the input hash is stable.
    Classification ids are derived from (run id, version id, dimension), making
    replay reproduce identical records. Versions without text cannot be
    classified by this method and produce nothing (C7: the run still names
    them as inputs, visibly pending for this processor).
    """
    context = context if context is not None else AdapterContext()
    ordered = sorted(versions, key=lambda version: version['id'])
    run = build_run(
        NAMESPACE, context,
        processor=PROCESSOR, processor_version=PROCESSOR_VERSION, config=dict(CONFIG),
        inputs=[{'kind': 'version', 'id': version['id']} for version in ordered],
        mode=mode,
    )
    classifications = []
    for version in ordered:
        if 'text' not in version:
            continue
        for dimension, value in (('topic', _topic(version['text'])),
                                 ('tone', _tone(version['text']))):
            classifications.append(validate_shape({
                'kind': 'classification',
                'id': named_id(
                    NAMESPACE, f'classification:{run["id"]}:{version["id"]}:{dimension}'
                ),
                'recorded_at': run['recorded_at'],
                'version_id': version['id'],
                'run_id': run['id'],
                'dimension': dimension,
                'taxonomy_version': CONFIG['taxonomy_version'],
                'value_string': value,
            }))
    return {'run': run, 'classifications': classifications}
