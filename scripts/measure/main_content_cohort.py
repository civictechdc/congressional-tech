"""Words the main-content selection loses or gains, against two other readers, both ways.

Usage: main_content_cohort.py MANIFEST BODIES_DIR OUT_DIR

MANIFEST is JSON ``{"bodies": [{"sha": ..., "url": ...}]}``; BODIES_DIR holds ``<sha>.gz`` or the
mirror layout ``bodies/sha256/<sha[:2]>/<sha><suffix>``. Every ``marked`` body is compared,
not a first-N sample. References: the same content:encoded element read by html5lib (a
different parser family that shares nothing with lxml but the bytes) and trafilatura's page
text. Ordered word sequences are compared with difflib, so a dropped middle paragraph is a
lost run, not hidden by a set of words that also occur elsewhere. Output is stratified by
(host, selector shape). Every body that loses words must be read in full by a person.
"""
import difflib
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

WORD = re.compile(r'\w+', re.U)
_BLOCKS = {'p', 'div', 'li', 'tr', 'td', 'th', 'dt', 'dd', 'dl', 'hr', 'br', 'table', 'caption', 'pre', 'figure',
           'figcaption', 'section', 'article', 'blockquote', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
_DROPPED = {'script', 'style', 'noscript', 'template'}


def words(text):
    return WORD.findall((text or '').replace('­', '').casefold())


def runs(selected, reference):
    """(lost, gained): word runs in reference missing from selected, and the reverse, in order."""
    a, b = words(selected), words(reference)
    lost, gained = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ('delete', 'replace'):
            gained.append(' '.join(a[i1:i2]))
        if tag in ('insert', 'replace'):
            lost.append(' '.join(b[j1:j2]))
    return lost, gained


def _html5lib_text(node):
    tag = node.tag.rsplit('}', 1)[-1].lower() if isinstance(node.tag, str) else None
    if tag in _DROPPED:
        return node.tail or ''
    sep = ' ' if tag in _BLOCKS else ''
    inner = (node.text or '') + ''.join(_html5lib_text(child) for child in node)
    return sep + inner + sep + (node.tail or '')


def html5lib_reference(body):
    """Text of the outermost content:encoded elements, read by html5lib; None unless exactly one."""
    import html5lib
    tree = html5lib.parse(body, treebuilder='etree', namespaceHTMLElements=False)
    found = [node for node in tree.iter() if 'content:encoded' in (node.get('property') or '').split()]
    inner = {child for node in found for child in node.iter() if child is not node}
    outer = [node for node in found if node not in inner]
    if len(outer) != 1:
        return None
    node = outer[0]
    return (node.text or '') + ''.join(_html5lib_text(child) for child in node)


def selector_shape(selector):
    return re.sub(r'\[\d+\]', '', selector or '')


def _body(root, sha):
    for path in (root / f'{sha}.gz', *sorted((root / 'bodies/sha256' / sha[:2]).glob(sha + '*'))):
        if path.exists():
            data = path.read_bytes()
            return gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data
    return None


def measure(manifest, bodies):
    from trafilatura import extract
    from congress_api.parsers.html_metadata import read_html_metadata
    from congress_api.parsers.main_content import select_main_content
    counts, strata, losing, missing = Counter(), defaultdict(Counter), [], []
    for row in manifest:
        body = _body(bodies, row['sha'])
        if body is None:
            missing.append(row['sha']); continue
        content = select_main_content(body, read_html_metadata(body))
        counts[f'outcome:{content.outcome}'] += 1
        counts[f'reason:{content.fallback_reason}'] += 1
        if content.outcome != 'marked':
            continue
        stratum = f"{urlsplit(row.get('url') or '').netloc or 'unknown'} {selector_shape(content.selector)}"
        result = dict(sha=row['sha'], url=row.get('url'), stratum=stratum, selected_words=len(words(content.text)))
        for name, reference in (('html5lib', html5lib_reference(body)),
                                ('trafilatura', extract(body, include_comments=False, output_format='txt'))):
            if reference is None:
                result[name] = None; strata[stratum][f'{name}_unavailable'] += 1; continue
            lost, gained = runs(content.text, reference)
            result[name] = dict(lost=lost, gained=gained)
            strata[stratum][f'{name}_losing'] += bool(lost)
        strata[stratum]['marked'] += 1
        if any((result[n] or {}).get('lost') for n in ('html5lib', 'trafilatura')):
            losing.append(result)
    return dict(bodies=len(manifest), missing=missing, counts=dict(sorted(counts.items())),
                strata={k: dict(v) for k, v in sorted(strata.items())}, losing=losing)


def main(argv):
    manifest, bodies, out = json.loads(Path(argv[1]).read_text())['bodies'], Path(argv[2]), Path(argv[3])
    result = measure(manifest, bodies)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'main-content-cohort.json').write_text(json.dumps(result, indent=1) + '\n')
    print(json.dumps({k: result[k] for k in ('bodies', 'counts', 'strata')}, indent=1))
    print('missing bodies:', len(result['missing']), 'bodies losing words:', len(result['losing']))


if __name__ == '__main__':
    main(sys.argv)
