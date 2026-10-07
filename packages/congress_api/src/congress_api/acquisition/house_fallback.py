"""House XML fallback reads the shared committee-site collection, without HTTP."""

from collections import defaultdict
from urllib.parse import urlsplit

from congress_api.matching.committees import native_parent
from congress_api.models.content import content_bytes
from congress_api.parsers.committee_pages import document_groups, match_event, same_site
from congress_api.parsers.document_links import http_url


def committee_websites(rows):
    """Congress-scoped publisher URLs; no second list of committee domains."""
    sites = defaultdict(set)
    for row in rows:
        committee, detail = row.get('committee') or {}, row.get('detail') or {}
        url = http_url(detail.get('committeeWebsiteUrl'))
        if committee.get('chamber') == 'House' and url and (urlsplit(url).hostname or '').endswith('.house.gov'):
            sites[int(row['congress']), committee['systemCode']].add(url)
    return sites


def needs_fallback(meeting, saved, failed_urls=()):
    native = (meeting.get('meetingDocuments') or []) + (meeting.get('witnessDocuments') or [])
    urls = {row.get('url') for row in native} | {row[2] for row in saved.get('documents', [])}
    if urls.intersection(failed_urls):
        return 'known_failed_document'
    if saved.get('status') in {'absent', 'error'} or not urls:
        return 'missing_repository_documents'
    if saved.get('committee_fallback'):
        return 'refresh_retained_committee_page'
    return None


def merge_documents(saved, fallback):
    """Add separately cited groups, leaving all XML/API observations intact."""
    saved['committee_fallback'] = fallback
    groups = saved['evidence']['document_groups']
    old_urls = {f['url'] for g in groups if g.get('source') == 'committee_html' for f in g.get('files', [])}
    groups[:] = [g for g in groups if g.get('source') != 'committee_html']
    primary_urls = {f['url'] for g in groups for f in g.get('files', [])}
    saved['documents'] = [d for d in saved['documents'] if d[2] not in old_urls - primary_urls]
    known = {row[2] for row in saved['documents']}
    for page in fallback.get('pages', []):
        check = fallback['checks'][page['check_index']]
        selector = f"/committee_fallback/checks/{page['check_index']}/content"
        for group in document_groups(content_bytes(check['content']), page['url'], selector):
            # Distinct publisher observations survive even when XML has the
            # same URL. Only the old compact summary deduplicates downloads.
            groups.append(group)
            group['source_sha256'] = check['content']['sha256']
            url = group['files'][0]['url']
            if url not in known:
                known.add(url)
                saved['documents'].append([group['legacy_kind'], group['description'], url, []])

    if saved.get('status') in {'absent', 'error'}:
        saved['repository_status'] = saved['status']
        saved['status'], saved['page_status'] = 'page', 'committee_fallback'


class CommitteeFallback:
    """Match retained event pages once; XML workers never recrawl committee sites."""

    def __init__(self, rows, state):
        self.sites = committee_websites(rows)
        self.state = state
        self.by_day = defaultdict(list)
        for host, saved in state.items():
            for url, page in saved.get('pages', {}).items():
                if (event := page.get('event')) and page.get('raw_html'):
                    self.by_day[host, event['date']].append((url, page))

    def find(self, meeting, previous=None):
        homes = set()
        for committee in meeting.get('committees') or []:
            code = committee.get('systemCode', '')
            homes.update(self.sites.get((int(meeting['congress']), code), ()) or
                         self.sites.get((int(meeting['congress']), native_parent(code)), ()))
        report = dict(status='not_found_in_retained_pages' if homes else 'no_official_website',
                      pages=[], checks=[], coverage={})
        for home in sorted(homes):
            host = (urlsplit(home).hostname or '').removeprefix('www.')
            report['coverage'][host] = self.state.get(host, {}).get('coverage', {'status': 'not_collected'})
            for url, page in self.by_day[host, meeting.get('date', '')[:10]]:
                if not any(same_site(url, address) for address in [home, *self.state.get(host, {}).get('linked_sites', {})]):
                    continue
                proof = match_event(content_bytes(page['raw_html']), url, meeting)
                if proof and not any(p['url'] == url for p in report['pages']):
                    index = len(report['checks'])
                    report['checks'].append(dict(url=url, content=page['raw_html'],
                        retrieved_at=page.get('retrieved_at'), checked=page.get('checked'), mode='retained'))
                    report['pages'].append(dict(url=url, check_index=index, match=proof, has_documents=bool(page.get('documents'))))
        if len(report['pages']) > 1:
            report['candidates'] = report['pages']
            report['pages'] = []
            report['status'] = 'ambiguous'
        elif report['pages']:
            report['status'] = 'matched' if report['pages'][0]['has_documents'] else 'matched_without_documents'
        return report
