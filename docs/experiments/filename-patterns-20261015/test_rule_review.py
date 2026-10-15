"""Behavioral checks for the isolated proposal workflow."""
import unittest

from rule_review import classify, select_samples, load_rules, context_evidence, role_gate


def record(name, host='naturalresources.house.gov', **extra):
    from urllib.parse import quote
    return {'filename': name, 'document_id': name, 'source_url': f'https://{host}/uploadedfiles/{quote(name)}',
            'source_urls': [], 'format': ['pdf'], 'record_role': ['document'], **extra}


def occurrence(label, heading=None, basis='retained_html_link'):
    return {'source_occurrence_scope': ['anchor'], 'source_association_basis': [basis],
            'source_link_url': ['https://naturalresources.house.gov/file.pdf'],
            'source_original_page_url': ['https://naturalresources.house.gov/event/1'],
            'source_link_label': [label], 'source_link_heading': [heading] if heading else []}


class RuleReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_rules()

    def result(self, name, host='naturalresources.house.gov', baseline=None, **extra):
        return classify(record(name, host, **extra), self.rules, baseline or [])

    def test_amendment_and_vote_remain_distinct(self):
        a = self.result('Chu 11 Amdt to Mgr TEXT.pdf', 'judiciary.house.gov')
        v = self.result('Chu 11 Amdt to Mgr RCV 2.pdf', 'judiciary.house.gov')
        self.assertEqual(a['proposed_kinds'], ['amendment'])
        self.assertEqual(v['proposed_kinds'], ['committee-vote'])

    def test_amendment_about_votes_is_not_a_vote_record(self):
        r = self.result('01-27-09_posey_amndt_on_recorded_votes.pdf', 'financialservices.house.gov')
        self.assertNotIn('committee-vote', r['proposed_kinds'])

    def test_related_statement_kinds_are_not_corroboration(self):
        r = self.result('opening_statement.pdf', baseline=['witness-statement'])
        self.assertEqual(r['status'], 'conflict')

    def test_pdf_in_hearing_directory_remains_a_document_candidate(self):
        r = record('hearing_memo.pdf', source_url='https://science.house.gov/hearings/hearing_memo.pdf')
        self.assertIsNone(role_gate(r))

    def test_ttf_and_statement_do_not_share_a_kind(self):
        t = self.result('HHRG-112- SY-TTF-TZurbuchen-20121212.pdf', 'science.house.gov')
        s = self.result('HHRG-112- SY-WState-TZurbuchen-20121212.pdf', 'science.house.gov')
        self.assertEqual(t['proposed_kinds'], ['testimony-disclosure'])
        self.assertNotIn('testimony-disclosure', s['proposed_kinds'])
        self.assertNotIn('witness-statement', s['proposed_kinds'])

    def test_marker_rules_need_publisher_scope(self):
        for host in ['example.org', 'naturalresources.house.gov.evil.test']:
            self.assertEqual(self.result('hearing_memo_06.14.16.pdf', host)['proposed_kinds'], [])

    def test_same_basename_is_evaluated_per_record(self):
        self.assertEqual(self.result('Jonesdisclosure.pdf')['proposed_kinds'], ['testimony-disclosure'])
        self.assertEqual(self.result('Jonesdisclosure.pdf', 'example.org')['proposed_kinds'], [])

    def test_whistleblower_disclosure_is_not_testimony_disclosure(self):
        self.assertEqual(self.result('Twitter_protected_whistleblower_disclosure.pdf')['proposed_kinds'], [])

    def test_topic_and_surname_are_not_kinds(self):
        for name in ['grijalva.pdf', 'Future_of_American_Energy.pdf', 'TT_Aloul.pdf', 'opening-night.pdf']:
            self.assertEqual(self.result(name)['proposed_kinds'], [])

    def test_memo_and_opening_conflict_is_retained(self):
        r = self.result('Dem-Memo-Opening-EP-hearing.pdf', 'democrats-energycommerce.house.gov')
        self.assertEqual(r['status'], 'conflict')

    def test_media_and_meeting_xml_are_role_review(self):
        for name in ['7.30.15-AI.wmv', 'HHRG-113-II00-20130904.xml', 'dip.xml', 'Other Documents.zip']:
            self.assertIsNotNone(role_gate(record(name)))
        self.assertIsNotNone(role_gate(record('memo.pdf', format=['text/html'])))

    def test_event_page_not_classified_as_document(self):
        r = record('hearing-memo', source_url='https://science.house.gov/hearings/hearing-memo')
        self.assertIsNotNone(role_gate(r))

    def test_conflicting_occurrences_abstain(self):
        r = self.result('hearing_memo.pdf', source_occurrences=[occurrence('Hearing Memo'), occurrence('Opening Statement')])
        self.assertEqual(r['status'], 'conflict')

    def test_untrusted_flat_context_does_not_corroborate(self):
        r = self.result('hearing_memo.pdf', source_link_label=['Hearing Memo'],
                        source_occurrences=[occurrence('Hearing Memo', basis='user_accepted_url_variant')])
        self.assertEqual(r['status'], 'proposed_filename_only')

    def test_scoped_publisher_label_corroborates(self):
        r = self.result('hearing_memo.pdf', source_occurrences=[occurrence('Hearing Memo')])
        self.assertEqual(r['status'], 'proposed_corroborated')

    def test_own_label_takes_precedence_over_broad_heading(self):
        evidence = context_evidence(record('x.pdf', source_occurrences=[occurrence('Truth in Testimony', 'Testimony')]))
        self.assertEqual({x['kind'] for x in evidence}, {'testimony-disclosure'})

    def test_baseline_disagreement_is_not_overwritten(self):
        r = self.result('hearing_memo.pdf', baseline=['transcript'])
        self.assertEqual(r['status'], 'conflict')
        self.assertEqual(r['baseline_kinds'], ['transcript'])

    def test_samples_include_boundary_and_source_diversity(self):
        names = [{'filename': n, 'lexical': t, 'domains': {d: 1}} for n,t,d in [
            ('memo.pdf','memo','a'),('memo-0.pdf','memo','a'),('memo-1.pdf','memo','a'),
            ('vote.pdf','vote','a'),('memo-other.pdf','memo','b')]]
        picked = select_samples(list(range(5)), names)
        self.assertEqual(len(set(picked)), 3)
        self.assertIn(3, picked)
        self.assertIn(4, picked)
        self.assertEqual(select_samples([0,1], names), [0,1])


if __name__ == '__main__':
    unittest.main()
