"""The cohort measure sees a dropped middle paragraph in both directions."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('main_content_cohort', ROOT / 'scripts/measure/main_content_cohort.py')
cohort = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cohort)

FULL = 'Alpha one.\nBravo two.\nCharlie three.'
DROPPED = 'Alpha one.\nCharlie three.'


def test_a_dropped_middle_paragraph_is_a_lost_run():
    assert cohort.runs(DROPPED, FULL) == (['bravo two'], [])


def test_an_added_paragraph_is_a_gained_run():
    assert cohort.runs(FULL, DROPPED) == ([], ['bravo two'])


def test_reordered_words_are_not_hidden_by_a_word_set():
    lost, gained = cohort.runs('Charlie three. Alpha one.', 'Alpha one. Charlie three.')
    assert lost and gained


def test_html5lib_reads_the_marked_element_with_block_breaks():
    body = (b'<html><body><nav>Nav</nav><div property="content:encoded"><p>A<b>b</b></p>'
            b'<table><tr><td>2006</td><td>6,658</td></tr></table><script>x()</script></div></body></html>')
    assert cohort.words(cohort.html5lib_reference(body)) == ['ab', '2006', '6', '658']
