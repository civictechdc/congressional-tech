"""Bind retained Groq image outcomes to shared page types without a new model call.

Integrity is separate from source review: a schema-valid response can still omit
or invent words. Callers retain that review before composing a completed body.
"""
import base64
from hashlib import sha256
from io import BytesIO
import re

from spicy_docs.extraction._structured import _outcome_validator, _strict_json
from spicy_docs.extraction.model import Observation, PageContent, PageResult, TextBlock

ARTIFACTS = frozenset({'identity', 'request', 'response', 'schema', 'prompt', 'receipt', 'image'})
KEYS = frozenset({'continuity', 'markdown', 'tables', 'doc_type', 'date', 'identifiers'})
ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'
MAX_BYTES = 16 << 20


def _pin(data):
    return dict(bytes=len(data), sha256=sha256(data).hexdigest())


def _matches(reference, data):
    return isinstance(reference, dict) and all(reference.get(k) == v for k, v in _pin(data).items())


def _markdown(outcome):
    """Splice only explicitly positioned tables; metadata never becomes prose."""
    text, tables = outcome['markdown'], outcome['tables']
    markers = re.findall(r'\{\{table:([^{}]+)\}\}', text)
    ids = [t['id'] for t in tables]
    if len(set(ids)) != len(ids) or sorted(markers) != sorted(ids):
        raise ValueError('Structured page tables require unique matching placeholders')
    for table in tables:
        columns = table['columns']
        if not columns:
            raise ValueError('Structured page table requires columns')
        rows = [row.split(' | ') for row in table['rows']]
        if any(len(row) != len(columns) for row in rows):
            raise ValueError('Structured page table row has ambiguous cell boundaries')
        # Preserve observed empty cells, including the first and last column.
        rendered = '\n'.join('| ' + ' | '.join(row) + ' |' for row in
                             [columns, ['---'] * len(columns), *rows])
        text = text.replace('{{table:' + table['id'] + '}}', rendered)
    return text


def retained_groq_page(artifacts):
    """Return an actual retained six-key page and its settings, without file/network I/O.

    Each named value is the original artifact's bytes. The request identity binds
    the physical source page to its reviewed render; bytes alone do not prove
    that rendering's semantic completeness. No native-layer or Apple identity is
    assigned to this remote image interpretation.
    """
    if set(artifacts) != ARTIFACTS or any(not isinstance(v, bytes) or len(v) > MAX_BYTES
                                        for v in artifacts.values()):
        raise ValueError('Structured page requires seven bounded retained artifacts')
    identity, request, response, schema, receipt = (
        _strict_json(artifacts[name]) for name in ('identity', 'request', 'response', 'schema', 'receipt'))
    prompt = artifacts['prompt'].decode('utf-8')
    if (identity.get('endpoint') != ENDPOINT or not prompt.strip()
            or any(not _matches(identity.get(key), artifacts[name]) for key, name in (
                ('request', 'request'), ('schema', 'schema'), ('system_prompt', 'prompt'), ('input_image', 'image')))
            or not _matches(receipt.get('response'), artifacts['response'])):
        raise ValueError('Structured page request, response, schema, prompt or image identity changed')
    if receipt.get('status') != 200 or receipt.get('error'):
        raise ValueError('Structured page requires a successful retained HTTP response')
    headers = {name.lower(): value for name, value in receipt.get('headers', {}).items()}
    request_id = headers.get('x-request-id')
    if (not isinstance(request_id, str) or not request_id
            or response.get('x_groq', {}).get('id') != request_id):
        raise ValueError('Structured page HTTP and provider request identities disagree')
    if request.get('response_format') != {'type': 'json_schema', 'json_schema': schema}:
        raise ValueError('Structured page request does not carry the retained schema')
    shape = schema.get('schema', {})
    if (schema.get('strict') is not True or set(shape.get('properties', {})) != KEYS
            or set(shape.get('required', [])) != KEYS or shape.get('additionalProperties') is not False):
        raise ValueError('Structured page requires the explicit six-key schema')
    _, validator = _outcome_validator(shape)
    messages = request.get('messages')
    if (not isinstance(messages, list) or len(messages) != 2
            or messages[0] != {'role': 'system', 'content': prompt}
            or messages[1].get('role') != 'user'):
        raise ValueError('Structured page request prompt or messages changed')
    expected_content = [
        {'type': 'text', 'text': '<document>\n'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(artifacts['image']).decode()}},
        {'type': 'text', 'text': '\n</document>'},
    ]
    if messages[1].get('content') != expected_content:
        raise ValueError('Structured page requires the exact retained image without supplied transcription')
    model = request.get('model')
    if (not isinstance(model, str) or not model or identity.get('model') != model
            or response.get('model') != model or response.get('error')):
        raise ValueError('Structured page model mismatch or provider error')
    choices = response.get('choices')
    if (not isinstance(choices, list) or len(choices) != 1 or choices[0].get('finish_reason') != 'stop'
            or not isinstance(choices[0].get('message'), dict)):
        raise ValueError('Structured page provider output is incomplete or ambiguous')
    message = choices[0]['message']
    if (message.get('role') != 'assistant' or message.get('refusal') or message.get('tool_calls')
            or not isinstance(message.get('content'), str)):
        raise ValueError('Structured page provider refused or returned nontext content')
    outcome = _strict_json(message['content'])
    validator.validate(outcome)
    text = _markdown(outcome)
    source = identity.get('source', {})
    body, size = source.get('sha256'), source.get('bytes')
    number, count, dpi = (identity.get(k) for k in ('physical_file_page', 'page_count', 'dpi_from_retained_render'))
    if (not isinstance(body, str) or re.fullmatch('[0-9a-f]{64}', body) is None
            or type(size) is not int or size < 1 or type(number) is not int or type(count) is not int
            or not 1 <= number <= count <= 100_000 or type(dpi) is not int or not 36 <= dpi <= 1200):
        raise ValueError('Structured page source, page or render identity is invalid')
    from PIL import Image
    with Image.open(BytesIO(artifacts['image'])) as image:
        if image.format != 'PNG' or list(image.size) != identity.get('dimensions') or image.mode != identity.get('mode'):
            raise ValueError('Structured page image dimensions or mode changed')
        if image.width * image.height > 20_000_000 or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Structured page image exceeds the single-page bound')
        image.verify()
    settings = dict(backend='groq', endpoint=ENDPOINT, model=model, mode='structured',
        generation={k: v for k, v in request.items() if k not in {'model', 'messages', 'response_format'}},
        prompt_sha256=sha256(artifacts['prompt']).hexdigest(), schema_sha256=sha256(artifacts['schema']).hexdigest(),
        response_id=response.get('id'), transport_request_id=request_id, service_tier=response.get('service_tier'))
    if not isinstance(settings['response_id'], str) or not settings['response_id']:
        raise ValueError('Structured page response identifier is unavailable')
    block = TextBlock(text, observation='structured-provider')
    observed = Observation('structured-provider', text, settings,
        dict(response=response, outcome=outcome, receipt=receipt), (block,), text_format='markdown')
    result = PageResult(dict(source_sha256=body, source_size_bytes=size, media_type='application/pdf',
        page=number, page_count=count, geometry={'dpi': dpi}, strategy='RetainedGroqStructuredPage',
        structured_provider_artifacts={k: _pin(v) for k, v in sorted(artifacts.items())}),
        PageContent((block,), (observed,)))
    return result, settings
