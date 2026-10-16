import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('recovery_html', Path(__file__).resolve().parents[1] / 'scripts/classify_recovery_html.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class HtmlClassificationTests(unittest.TestCase):
    def test_navigation_does_not_fill_empty_document(self):
        raw = ('<title>Witness</title><nav>' + 'news ' * 200 + '</nav><div class="field-name-body"></div>').encode()
        self.assertEqual(module.classify(raw)['category'], 'empty_document_body')

    def test_attachment_is_not_transcript(self):
        result = module.classify(b'<title>Hearing</title><div class="field-name-body"><a href="file.pdf">Printer friendly version</a></div>')
        self.assertEqual(result['category'], 'attachment_page')
        self.assertEqual(result['links'][0]['href'], 'file.pdf')

    def test_explicit_absence_is_metadata(self):
        result = module.classify(b'<title>Witness</title><div class="field-name-body">No Prepared Statement.</div>')
        self.assertEqual(result['category'], 'historical_no_prepared_statement')

    def test_prose_in_document_body(self):
        raw = ('<title>Witness testimony</title><div class="field field-name-body other">' + 'testimony ' * 101 + '</div>').encode()
        self.assertEqual(module.classify(raw)['category'], 'substantial_document_body')

    def test_challenge_overrides_large_body(self):
        raw = ('<title>Session Verification</title><div class="field-name-body">' + 'challenge ' * 200 + '</div>').encode()
        self.assertEqual(module.classify(raw)['category'], 'error_or_challenge')

    def test_similar_class_does_not_match(self):
        raw = ('<title>Witness</title><div class="not-field-name-body">' + 'news ' * 200 + '</div>').encode()
        self.assertEqual(module.classify(raw)['category'], 'empty_document_body')

if __name__ == '__main__':
    unittest.main()
