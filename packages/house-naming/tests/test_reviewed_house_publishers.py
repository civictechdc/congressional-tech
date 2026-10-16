"""Publisher layouts checked against exact retained PDFs, October 2026."""
from urllib.parse import quote

import pytest
from house_naming import Engine


@pytest.fixture(scope='module')
def engine():return Engine()


@pytest.mark.parametrize('name,host,kind',[
    ('hearing_memo_--_leg_hrg_on_h.r._212_11.15.17.pdf','naturalresources.house.gov','committee-memorandum'),
    ('Dem-Memo-OI-Hrg-Anti-Doping-2017-02-28.pdf','democrats-energycommerce.house.gov','committee-memorandum'),
    ('072418_fc_markup_memo.pdf','financialservices.house.gov','committee-memorandum'),
    ('091113_mpt_memo.pdf','financialservices.house.gov','committee-memorandum'),
    ('hrgmemowp3_24.pdf','naturalresources.house.gov','committee-memorandum'),
    ('arnettdisclosure.pdf','naturalresources.house.gov','testimony-disclosure'),
    ('HHRG-112- SY20-TTF-RTrzupek-201200606.pdf','science.house.gov','testimony-disclosure'),
    ('merrick_witness_disclosure.pdf','smallbusiness.house.gov','testimony-disclosure'),
    ('6822_hearing_charter_-_detecting_and_quantifying_methane.pdf.pdf','science.house.gov','hearing-charter'),
    ('ianawitnesslistupdate07-23-13.pdf','naturalresources.house.gov','witness-list'),
    ('fcwtnslst5-7-14.pdf','naturalresources.house.gov','witness-list'),
    ('06.07.12_rcv6_woolsey.pdf','edworkforce.house.gov','committee-vote'),
    ('111th_fc_record_vote_--113.pdf','financialservices.house.gov','committee-vote'),
    ('Pallone-Amendment-SCD01-031616.pdf','democrats-energycommerce.house.gov','amendment'),
    ('7.14.10_amend9_petri.pdf','edworkforce.house.gov','amendment'),
    ('20180412HR-Advisory.pdf','waysandmeans.house.gov','meeting-notice'),
    ('emrhrgnotice08-02-13.pdf','naturalresources.house.gov','meeting-notice'),
    ('emrhrngntc-3-4-14.pdf','naturalresources.house.gov','meeting-notice'),
    ('Milleropeningstatement2693.pdf','edworkforce.house.gov','opening-statement'),
    ('docopeningstate9-9-14.pdf','naturalresources.house.gov','opening-statement'),
    ('03-05-13mcclintockopening.pdf','naturalresources.house.gov','opening-statement'),
    ('lambornopening2-27-14.pdf','naturalresources.house.gov','opening-statement'),
    ('2019-03-06 Coast Guard SSM.pdf','transportation.house.gov','committee-memorandum'),
    ('2017-03-28_-_water_ssm-updated.pdf','transportation.house.gov','committee-memorandum'),
    ('052318_housing_memo.pdf','financialservices.house.gov','committee-memorandum'),
    ('060816_tf_memo.pdf','financialservices.house.gov','committee-memorandum'),
    ('kendalltestimony9-10-14.pdf','naturalresources.house.gov','testimony'),
    ('10_3testimonymcmillan.pdf','naturalresources.house.gov','testimony'),
])
def test_checked_publisher_layout(engine,name,host,kind):
    result=engine.extract(name,source_url=f'https://{host}/uploadedfiles/{quote(name)}')
    assert result['metadata'].get('document_kind')==[kind]
    assert ''.join(piece['raw'] for piece in result['pieces'])==name
    for observation in result['observations']:
        for field in observation['fields']:
            assert name[field['start']:field['end']]==field['raw']
    assert {k:result[k] for k in engine.parse(name)}==engine.parse(name)


@pytest.mark.parametrize('name,host,forbidden',[
    ('arnettdisclosure.pdf','example.org','testimony-disclosure'),
    ('arnettdisclosure.pdf','naturalresources.house.gov.evil.test','testimony-disclosure'),
    ('Twitter_protected_whistleblower_disclosure.pdf','naturalresources.house.gov','testimony-disclosure'),
    ('financial_disclosure_report.pdf','naturalresources.house.gov','testimony-disclosure'),
    ('01-27-09_posey_amndt_on_recorded_votes.pdf','financialservices.house.gov','committee-vote'),
    ('bera_conference_os.pdf','science.house.gov','opening-statement'),
    ('lofgren_conference_os.pdf','science.house.gov','opening-statement'),
    ('HHRG-119-IF00-Wstate-HearingMemo-20250318.pdf','energycommerce.house.gov','committee-memorandum'),
    ('BILLS-119-HR123-OpeningStatementReformAct-ih.pdf','edworkforce.house.gov','opening-statement'),
    ('2014-08-20-ed_roundtable_ssm_addendum.pdf','transportation.house.gov','committee-memorandum'),
    ('Weissman.pdf','transportation.house.gov','committee-memorandum'),
    ('060816_tf_memo.pdf','example.org','committee-memorandum'),
    ('smithtestimonyrequirements.pdf','naturalresources.house.gov','testimony'),
])
def test_ambiguous_or_unscoped_words_do_not_supply_kind(engine,name,host,forbidden):
    result=engine.extract(name,source_url=f'https://{host}/{quote(name)}')
    assert forbidden not in result['metadata'].get('document_kind',[])


def test_www_publisher_and_literal_date_values_survive(engine):
    name='6-13-18_hearing_memo.pdf'
    original=engine.extract(name)['metadata']
    changed=engine.extract(name,source_url='https://www.smallbusiness.house.gov/file.pdf')['metadata']
    assert changed['document_kind']==['committee-memorandum']
    for field in ['date_token','short_date_token','extension']:
        assert changed.get(field)==original.get(field)


@pytest.mark.parametrize('name',['hearing_memo.xml','hearing_memo.jpg','hearing_memo.pdf.jpg'])
def test_new_document_layouts_do_not_promote_media_or_xml(engine,name):
    result=engine.extract(name,source_url='https://naturalresources.house.gov/'+name)
    assert 'committee-memorandum' not in result['metadata'].get('document_kind',[])


@pytest.mark.parametrize('name', [
    '050812RC2 - Lofgren-Berman Amdt016.pdf',
    'Roll Call Vote 7Nadler Amdt 6.pdf',
    '071012RC1 - Scott Amdt3.pdf',
    'Amendment 1 Roll Call.pdf',
])
def test_vote_record_keeps_amendment_reference_without_amendment_kind(engine, name):
    result = engine.extract(name, source_url='https://judiciary.house.gov/files/' + quote(name))
    assert result['metadata']['document_kind'] == ['committee-vote']
    assert result['metadata']['amendment_marker']
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    markers = [f for m in result['observations'] for f in m['fields']
               if f['name'] == 'amendment_marker']
    assert markers
    assert all(name[f['start']:f['end']] == f['raw'] for f in markers)
    # Without publisher-qualified vote wording, the literal amendment reading
    # remains available; this is not a global ban on amendment references.
    for host in ('example.org', 'judiciary.house.gov.example.org'):
        metadata = engine.extract(name, source_url=f'https://{host}/' + quote(name))['metadata']
        assert metadata['document_kind'] == ['amendment']


@pytest.mark.parametrize('name', [
    'Amendment 1 and Roll Call.pdf',
    'Roll Call and Amendment 1.pdf',
    'Amendment 1 & Roll Call.pdf',
    'Roll Call & Amendment 1.pdf',
])
def test_explicit_combined_amendment_and_vote_keep_both_genres(engine, name):
    result = engine.extract(name, source_url='https://judiciary.house.gov/' + quote(name))
    assert result['metadata']['document_kind'] == ['amendment', 'committee-vote']


@pytest.mark.parametrize('name', [
    '07272011 Roll Call 3- Sensenbrenner Amendment 3 TEXT.pdf',
    'Roll Call Vote 7Nadler Amdt 6 TEXT.pdf',
    'Roll_Call_Vote_7Nadler_Amdt_6_text.pdf',
])
def test_explicit_amendment_text_is_not_collapsed_into_vote_only(engine, name):
    # These publishers also name amendment-text variants after a roll call.
    # Keep the ambiguity until retained content can establish the document form.
    result = engine.extract(name, source_url='https://judiciary.house.gov/' + quote(name))
    assert result['metadata']['document_kind'] == ['amendment', 'committee-vote']


def test_vote_on_committee_print_keeps_literal_print_reference(engine):
    name = 'rc8_cmteprint(reconciliation)cawthorna11.pdf'
    result = engine.extract(name, source_url='https://edworkforce.house.gov/imo/media/doc/' + name)
    assert result['metadata']['document_kind'] == ['committee-vote']
    assert result['metadata']['print_token'] == ['cmteprint']


@pytest.mark.parametrize('name,host', [
    ('h.r._7683_-_respecting_the_first_amendment_on_campus_act_bill_text.pdf', 'edworkforce.house.gov'),
    ('2015-07-29-JEC-EEC-to-Lynch-DOJ-Fourth-Amendment-due-8-7.pdf', 'oversight.house.gov'),
    ('Second Amendment Rights Act Bill Text.pdf', 'edworkforce.house.gov'),
    ('14th_Amendment.pdf', 'judiciary.house.gov'),
    ('Twenty-First Amendment.pdf', 'judiciary.house.gov'),
])
def test_constitutional_topic_does_not_supply_publisher_amendment_kind(engine, name, host):
    result = engine.extract(name, source_url=f'https://{host}/' + quote(name))
    assert 'amendment' not in result['metadata'].get('document_kind', [])
    assert any(f['raw'].lower() == 'amendment' for m in result['observations'] for f in m['fields'])
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    if 'bill_text' in name.lower() or 'bill text' in name.lower():
        assert result['metadata']['document_kind'] == ['legislative-text']


@pytest.mark.parametrize('name', [
    'First Amendment to H.R. 7683.pdf',
    'First_Amendment_to_S._123.pdf',
    'First Amendment to Committee Rules.pdf',
    'Proposed First Amendment.pdf',
    'Offered Second Amendment.pdf',
    'Amendment to First Amendment Protections Act.pdf',
    'First Amendment 1.pdf',
    'Democratic Alternative to Committee Rules 114th Amendment - EBJ.pdf',
])
def test_operative_amendment_wording_survives_constitutional_topic_filter(engine, name):
    result = engine.extract(name, source_url='https://judiciary.house.gov/' + quote(name))
    assert result['metadata']['document_kind'] == ['amendment']
