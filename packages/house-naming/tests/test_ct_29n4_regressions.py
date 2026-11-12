"""Regressions for ct-29n4: Truth in Testimony disclosure names and name-clash reader slips."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name, source_url=None):
    result = engine.extract(name, source_url=source_url)
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for match in (*result['observations'], *result['suppressed']):
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
    assert all(result[k] == v for k, v in engine.parse(name).items())
    return result['metadata']


@pytest.mark.parametrize('name,url', [
    ('Web_Hedren_TruthinTestimony04.09.19.pdf', 'https://democrats-edworkforce.house.gov/Web_Hedren_TruthinTestimony04.09.19.pdf'),
    ('Web_Shappley_TruthinTestimony04.09.19.pdf', 'https://democrats-edworkforce.house.gov/Web_Shappley_TruthinTestimony04.09.19.pdf'),
    ('MuhinduraPascalineTruthinTestimonyForm031120215.pdf', 'https://democrats-edworkforce.house.gov/MuhinduraPascalineTruthinTestimonyForm031120215.pdf'),
    ('MarrLinseyTruthinTestimonyForm031120211.pdf', 'https://democrats-edworkforce.house.gov/MarrLinseyTruthinTestimonyForm031120211.pdf'),
    ('MichaelsDavidTruthinTestimonyForm03112021.pdf', 'https://democrats-edworkforce.house.gov/MichaelsDavidTruthinTestimonyForm03112021.pdf'),
    ('Pages-from-Feldstein-TruthinTestimony-011315-FC.pdf', 'https://waysandmeans.house.gov/Pages-from-Feldstein-TruthinTestimony-011315-FC.pdf'),
    ('Pages-from-HoltzEakin-TruthinTestimony-011315-FC.pdf', 'https://waysandmeans.house.gov/Pages-from-HoltzEakin-TruthinTestimony-011315-FC.pdf'),
    ('Pages_from_Johnson_Truth_inTestimony31313.pdf', 'https://waysandmeans.house.gov/Pages_from_Johnson_Truth_inTestimony31313.pdf'),
    ('Hill_TruthInTestimony.pdf', 'https://waysandmeans.house.gov/Hill_TruthInTestimony.pdf'),
    ('DeFontesTruthinTestimonyDisclosure02142013.pdf', 'https://intelligence.house.gov/DeFontesTruthinTestimonyDisclosure02142013.pdf'),
    ('EnglerTruthinTestimony02142013.pdf', 'https://intelligence.house.gov/EnglerTruthinTestimony02142013.pdf'),
    ('morelltruthintestimony.pdf', 'https://intelligence.house.gov/morelltruthintestimony.pdf'),
    ('ECEBDF950BC6A00C2D4E43919DEF37C0A2691EE3218BFED43E88F5E2843A72B0.macauley-truthintestimony.pdf', 'https://science.house.gov/x.pdf'),
    ('20160907HL-Truthi-in-Testimony-Wynn.pdf', 'https://waysandmeans.house.gov/20160907HL-Truthi-in-Testimony-Wynn.pdf'),
    ('7_29_14_SS_Biggs_Trurth_in_Testimony.pdf', 'https://waysandmeans.house.gov/7_29_14_SS_Biggs_Trurth_in_Testimony.pdf'),
    ('truth_in_testimomy_slater_Copy.pdf', 'https://waysandmeans.house.gov/truth_in_testimomy_slater_Copy.pdf'),
    ('Pages-from-Grinberg-Truth-in-Testimon.pdf', 'https://waysandmeans.house.gov/Pages-from-Grinberg-Truth-in-Testimon.pdf'),
    ('Bronfenbrennertruthintestimonysigned1.pdf', 'https://democrats-edworkforce.house.gov/Bronfenbrennertruthintestimonysigned1.pdf'),
    ('mandiatruthintestimonydisclosure02142013.pdf', 'https://intelligence.house.gov/mandiatruthintestimonydisclosure02142013.pdf'),
    ('Gibboney-Truth-in-Testimony.pdf', 'https://oversight.house.gov/Gibboney-Truth-in-Testimony.pdf'),
    ('Martin Truth in Testimony.pdf', 'https://democrats-budget.house.gov/Martin%20Truth%20in%20Testimony.pdf'),
    ('Truth in Testimony Form.pdf', 'https://democrats-appropriations.house.gov/Truth%20in%20Testimony%20Form.pdf'),
    ('4A7378BB45766EB85140FBE3A8EC5DA97B4E320ECFF7749AB9DD63265ED13D50.truth-in-testimony-form-blanton.pdf', 'https://cha.house.gov/x.pdf'),
    ('117-truth-in-testimony-form_arunross_redacted&download=1', 'https://democrats-science.house.gov/download/x'),
    ('abdallah-truth-in-testimony&download=1', 'https://democrats-science.house.gov/download/abdallah-truth-in-testimony'),
    ('corlette-truth-in-testimony', 'https://democrats-edworkforce.house.gov/download/corlette-truth-in-testimony'),
    ('Taylor Testimony.Truth in Testimony.pdf', 'https://oversightdemocrats.house.gov/Taylor%20Testimony.Truth%20in%20Testimony.pdf'),
    ('Lindsey Testimony.Truth in Testimony.pdf', 'https://oversightdemocrats.house.gov/Lindsey%20Testimony.Truth%20in%20Testimony.pdf'),
])
def test_truth_in_testimony_names_classify_as_disclosure(engine, name, url):
    meta = checked(engine, name, url)
    assert meta.get('document_kind') == ['testimony-disclosure']
    assert meta.get('document_family') == ['disclosure']


def test_truth_in_testimony_preserves_coordinated_and_official_slots(engine):
    combined = checked(engine, 'Testimony and Truth in Testimony.pdf')
    assert sorted(combined.get('document_kind', [])) == ['testimony', 'testimony-disclosure']
    official = checked(engine, 'HHRG-119-IF00-Wstate-TruthinTestimony-20250318.pdf')
    assert official.get('document_kind') == ['witness-statement']
    assert official.get('document_family') == ['statement']


@pytest.mark.parametrize('name', [
    'ANS to the Committee Print Offered by Mr. Scott.pdf',
    'ECR-Committee-Print-GOP-Reconciliation-Text-AINS-1.pdf',
    'ans_to_ti_committee_print_reconciliation.pdf',
    'ANS_CommitteePrint(ReconciliationDirectives).pdf',
    'Garland Contempt Report re Hur Report Materials_ANS.pdf',
    'VE-Letter-AINS.pdf',
])
def test_ans_and_ains_to_prints_reports_and_letters_classify_as_amendment(engine, name):
    meta = checked(engine, name)
    assert meta.get('document_kind') == ['amendment']
    assert meta.get('document_family') == ['amendment']


@pytest.mark.parametrize('name,url', [
    ('Chu-Amendment-2-Result.pdf', 'https://waysandmeans.house.gov/Chu-Amendment-2-Result.pdf'),
    ('H.R.-4818-Beyer-Amendment-3-Result.pdf', 'https://waysandmeans.house.gov/H.R.-4818-Beyer-Amendment-3-Result.pdf'),
    ('Sewell-Amendment-7-Result.pdf', 'https://waysandmeans.house.gov/Sewell-Amendment-7-Result.pdf'),
    ('Beyer-Amendment-5-to-H.R.-9462-Final-Tally.pdf', 'https://waysandmeans.house.gov/Beyer-Amendment-5-to-H.R.-9462-Final-Tally.pdf'),
    ('Sanchez-Amendment-1-to-H.R.-8245-Final-Tally.pdf', 'https://waysandmeans.house.gov/Sanchez-Amendment-1-to-H.R.-8245-Final-Tally.pdf'),
    ('Doggett-Amendment-1-to-H.R.-8621-Vote-Tally.pdf', 'https://waysandmeans.house.gov/Doggett-Amendment-1-to-H.R.-8621-Vote-Tally.pdf'),
    ('H.R.-7986-AINS-Vote-Tally.pdf', 'https://waysandmeans.house.gov/H.R.-7986-AINS-Vote-Tally.pdf'),
    ('Schweikerts-motion-to-submit-documents-Vote-Tally.pdf', 'https://waysandmeans.house.gov/Schweikerts-motion-to-submit-documents-Vote-Tally.pdf'),
])
def test_ways_and_means_tally_and_result_names_classify_as_vote_record(engine, name, url):
    meta = checked(engine, name, url)
    assert meta.get('document_family') == ['vote-record']


@pytest.mark.parametrize('name', [
    'h.r.-1418-animal-drug-user-fee-amendments-of-2023.pdf',
    'H_R_1418_Animal_Drug_User_Fee_Amendments_of_2023_1_887f56fa39.pdf',
    'discussion_draft__-_cofa_amendments_act_of_2023.pdf',
    'h.r-4273,-over-the-counter-monograph-drug-user-fee-amendments.pdf',
])
def test_act_titles_containing_amendments_do_not_classify_as_amendment_collection(engine, name):
    meta = checked(engine, name)
    assert 'amendment' not in meta.get('document_family', [])
    assert 'amendment-collection' not in meta.get('document_kind', [])


@pytest.mark.parametrize('name', [
    '61422_Amendments.zip',
    'HR_1418_Amendments.pdf',
    'fy24-homeland-adopted-amendments&download=1',
])
def test_genuine_amendments_collections_keep_amendment_family(engine, name):
    meta = checked(engine, name)
    assert meta.get('document_kind') == ['amendment-collection']
    assert meta.get('document_family') == ['amendment']


@pytest.mark.parametrize('name', [
    '04B1FCAFD47C5A5AC1BDE6BE9C4D39E537CDD0E9FB2C098765A2B1C2206252BE.on-the-motion-to-report-h.-res.-1475-unfavorably-to-the-house-as-amended-.pdf',
    'VOTE-4-21-15-Favorably-Report-H.-J.-Res.-43.pdf',
])
def test_motion_to_report_roll_call_classifies_as_vote_record_not_report(engine, name):
    meta = checked(engine, name)
    assert meta.get('document_kind') == ['committee-vote']
    assert meta.get('document_family') == ['vote-record']


@pytest.mark.parametrize('name', [
    'CRENSHAW_bio-early-01.final_.pdf',
    'CRENSHAW_bio_early_01_final_75cd99ca35.pdf',
])
def test_legislative_draft_bio_slug_is_not_biography(engine, name):
    meta = checked(engine, name)
    assert 'biography' not in meta.get('document_family', [])
    assert 'biography' not in meta.get('document_kind', [])


def test_explanatory_statement_keeps_its_own_family_outside_witness_statement_slot(engine):
    meta = checked(engine, 'Explanatory Statement Homeland Security.pdf')
    assert meta.get('document_kind') == ['explanatory-statement']
    assert meta.get('document_family') == ['explanatory-statement']
