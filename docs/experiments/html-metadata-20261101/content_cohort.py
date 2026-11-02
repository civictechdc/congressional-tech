"""Main-content outcomes over a retained sample. Usage: content_cohort.py MANIFEST BODIES_DIR OUT_DIR.

Writes content-cohort.json (counts) and content-cohort.md (20 side-by-side pages for a
person to read). Whole-page text and trafilatura share a parser family with the
selection and could miss the same words; the human read is the different basis.
"""
import gzip
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from trafilatura import extract

from congress_api.parsers.html_metadata import parse_document, read_html_metadata
from congress_api.parsers.main_content import block_text, select_main_content

manifest, bodies, out = json.loads(Path(sys.argv[1]).read_text())['bodies'], Path(sys.argv[2]), Path(sys.argv[3])
counts, hosts, marked, short, reasons = Counter(), Counter(), [], [], []
for row in manifest:
    body = gzip.decompress((bodies / f"{row['sha']}.gz").read_bytes())
    metadata = read_html_metadata(body)
    content = select_main_content(body, metadata)
    counts['outcome:' + content.outcome] += 1
    counts['with_candidate'] += bool(content.candidates)
    counts['reason:' + str(content.fallback_reason)] += 1
    reasons.append(dict(conflict=content.fallback_reason == 'conflicting_candidates'))
    counts['candidates:' + str(min(len(content.candidates), 3))] += 1
    for candidate in content.candidates:
        counts['property:' + candidate.property] += 1
    if content.candidates:
        hosts[urlsplit(row.get('url') or '').netloc or 'unknown'] += 1
    if content.outcome == 'marked_no_content':
        short.append(dict(sha=row['sha'], chars=content.candidates[0].char_count, text=content.candidates[0].text,
                          links=[link.href for link in content.candidates[0].links]))
    if content.outcome == 'marked':
        tree = parse_document(body)
        whole = block_text(tree.xpath('//body')[0])
        other = extract(body, include_comments=False, output_format='txt') or ''
        words = lambda text: set(re.findall(r'[a-z]{3,}', text.lower()))
        chosen = words(content.text)
        marked.append(dict(sha=row['sha'], url=row.get('url'), selected_chars=len(content.text), whole_chars=len(whole),
                           trafilatura_chars=len(other), selector=content.selector,
                           marked_words_not_in_trafilatura=len(chosen - words(other)),
                           marked_words_not_in_whole_page=len(chosen - words(whole)),
                           selected_head=content.text[:500], trafilatura_head=other[:500]))
result = dict(
    cohort=dict(bodies=len(manifest), raw_bodies_read=len(manifest), manifest='sample-manifest.json'),
    counts=dict(sorted(counts.items())), hosts=dict(hosts),
    marked=dict(n=len(marked), median_chars_removed_against_whole_page=statistics.median(m['whole_chars'] - m['selected_chars'] for m in marked),
                selected_chars=dict(min=min(m['selected_chars'] for m in marked), median=statistics.median(m['selected_chars'] for m in marked), max=max(m['selected_chars'] for m in marked)),
                bodies_with_marked_words_not_in_trafilatura=sum(m['marked_words_not_in_trafilatura'] > 0 for m in marked),
                bodies_with_marked_words_not_in_whole_page=sum(m['marked_words_not_in_whole_page'] > 0 for m in marked)),
    marked_no_content=short,
    no_real_instances=[name for name, key in (('ordinary articles from other hosts', len(hosts) > 1), ('multiple distinct candidates', any(item.get('conflict') for item in reasons))) if not key],
)
(out / 'content-cohort.json').write_text(json.dumps(result, indent=1) + '\n')
lines = ['# Main content side by side', '', 'Twenty marked pages for a person to read. Excerpts are the first 500 characters of each public page.', '']
for item in marked[:20]:
    lines += [f"## {item['url']}", '', f"`{item['sha']}`: selected {item['selected_chars']} characters, whole page {item['whole_chars']}, trafilatura {item['trafilatura_chars']}.", '',
              '**Selected**', '', '> ' + item['selected_head'].replace('\n', '\n> '), '', '**trafilatura**', '', '> ' + item['trafilatura_head'].replace('\n', '\n> '), '']
(out / 'content-cohort.md').write_text('\n'.join(lines))
print(json.dumps({k: result[k] for k in ('counts', 'hosts', 'marked', 'no_real_instances')}, indent=1))
print(*[(s['chars'], s['text'][:90], len(s['links'])) for s in short], sep='\n')
