"""Publisher layouts checked against exact retained PDFs, October 2026."""
from urllib.parse import quote

import pytest
from house_naming import Engine


@pytest.fixture(scope='module')
def engine():return Engine()


@pytest.mark.parametrize('name', [
    'RC2_Huffman1_to_Stauber_ANS_to_HR_2925.pdf',
    'RC_7_Rosendale_ANS_to_H.R._200.pdf',
    'RC_4_Grijalva_3_Substitute_amendment_to_Stauber_016_ANS_to_HR_3195.pdf',
])
def test_historical_natural_resources_vote_publisher(engine, name):
    result = engine.extract(name, source_url='https://republicans-naturalresources.house.gov/' + quote(name))
    assert result['metadata']['document_kind'] == ['committee-vote']
    assert result['metadata']['amendment_marker']
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    assert all(name[f['start']:f['end']] == f['raw']
               for observation in result['observations'] for f in observation['fields'])


@pytest.mark.parametrize('host', ['example.org', 'republicans-naturalresources.house.gov.example.org',
                                 'unreviewed.house.gov'])
def test_historical_vote_publisher_requires_exact_host(engine, host):
    name = 'RC2_Huffman1_to_Stauber_ANS_to_HR_2925.pdf'
    result = engine.extract(name, source_url=f'https://{host}/' + quote(name))
    assert result['metadata']['document_kind'] == ['amendment']


@pytest.mark.parametrize('name,expected', [
    ('RC2_Huffman1_to_Stauber_ANS_to_HR_2925_TEXT.pdf', ['amendment', 'committee-vote']),
    ('Roll Call and Amendment 1.pdf', ['amendment', 'committee-vote']),
    ('Amendment 1 on Recorded Votes.pdf', ['amendment']),
])
def test_historical_vote_publisher_keeps_combined_and_topic_controls(engine, name, expected):
    result = engine.extract(name, source_url='https://republicans-naturalresources.house.gov/' + quote(name))
    assert sorted(result['metadata']['document_kind']) == expected


@pytest.mark.parametrize('name,expected', [
    ('Goetze_-_Witness_Disclosure_Statement.pdf', ['testimony-disclosure']),
    ('craig_fabian_witnessdisclosurestatement.pdf', ['testimony-disclosure']),
    ('Craig_Fabian_WitnessDisclosureStatement.pdf', ['testimony-disclosure']),
    ('Odysseus_Lanier_-_Witness_Disclosure_STMT.pdf', ['testimony-disclosure']),
    ('7-25-2013_Scherman_-_Disclosure_Stmt.pdf', ['testimony-disclosure']),
    ('Jones_Disclosure_Statement.pdf', ['testimony-disclosure']),
    ('Odysseus_Lanier_Disclosure_Statement_Attachment.pdf', ['attachment', 'testimony-disclosure']),
    ('Disclosure and Statement.pdf', ['statement', 'testimony-disclosure']),
    ('Statement and Disclosure.pdf', ['statement', 'testimony-disclosure']),
    ('Disclosure_Statement_and_Opening_Statement.pdf', ['opening-statement', 'testimony-disclosure']),
])
def test_disclosure_statement_is_one_phrase_without_losing_combined_forms(engine, name, expected):
    result = engine.extract(name, source_url='https://smallbusiness.house.gov/' + quote(name))
    assert sorted(result['metadata']['document_kind']) == sorted(expected)
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    assert all(name[f['start']:f['end']] == f['raw']
               for observation in result['observations'] for f in observation['fields'])
    assert {k: result[k] for k in engine.parse(name)} == engine.parse(name)


@pytest.mark.parametrize('name,host', [
    ('Witness_Disclosure_Statement.pdf', 'example.org'),
    ('Witness_Disclosure_Statement.pdf', 'smallbusiness.house.gov.example.org'),
    ('Financial_Disclosure_Statement.pdf', 'smallbusiness.house.gov'),
    ('Protected_Disclosure_Statement.pdf', 'smallbusiness.house.gov'),
])
def test_disclosure_statement_keeps_publisher_and_subject_exclusions(engine, name, host):
    result = engine.extract(name, source_url=f'https://{host}/' + quote(name))
    assert 'testimony-disclosure' not in result['metadata'].get('document_kind', [])


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
def test_reviewed_judiciary_text_variant_selects_amendment(engine, name):
    # All 15 retained variants are amendment text, often with vote annotations.
    result = engine.extract(name, source_url='https://judiciary.house.gov/' + quote(name))
    assert result['metadata']['document_kind'] == ['amendment']
    assert result['metadata']['amendment_marker']
    assert any(f.get('category') == 'committee-vote'
               for m in result['observations'] for f in m['fields'])
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    assert all(name[f['start']:f['end']] == f['raw']
               for m in result['observations'] for f in m['fields'])
    assert {k: result[k] for k in engine.parse(name)} == engine.parse(name)


@pytest.mark.parametrize('name,host,expected', [
    ('Roll Call Vote 7Nadler Amdt 6 TEXT.pdf', 'naturalresources.house.gov', ['amendment', 'committee-vote']),
    ('Roll Call Vote 7Nadler Amdt 6 TEXT.pdf', 'judiciary.house.gov.example.org', ['amendment']),
    ('Roll Call Vote 7Nadler Amdt 6 TEXT.doc', 'judiciary.house.gov', ['amendment', 'committee-vote']),
    ('Roll Call Vote 7 and Amendment 6 TEXT.pdf', 'judiciary.house.gov', ['amendment', 'committee-vote']),
    ('Roll Call Vote 7 & Amendment 6 TEXT.pdf', 'judiciary.house.gov', ['amendment', 'committee-vote']),
    ('Roll Call Vote 7Nadler Amdt 6 TEXT and Vote Sheet.pdf', 'judiciary.house.gov', ['amendment', 'committee-vote']),
    ('Roll Call Report TEXT.pdf', 'judiciary.house.gov', ['committee-vote', 'report']),
    ('Roll Call Vote 7Nadler Amdt 6.pdf', 'judiciary.house.gov', ['committee-vote']),
    ('Swalwell- Representational Disclosures.pdf', 'science.house.gov', []),
    ('hr_3476_graves_amendment_21_tp_ans_cbra_disclosure_notification.pdf', 'naturalresources.house.gov', ['amendment']),
    ('Witness Disclosure Statement.pdf', 'science.house.gov', ['testimony-disclosure']),
    ('Amendment 21 and Witness Disclosure.pdf', 'naturalresources.house.gov', ['amendment', 'testimony-disclosure']),
    ('Amendment-in-the-Nature-of-a-Substitute-to-VE-LEtter-FY2024.pdf', 'waysandmeans.house.gov', ['amendment', 'letter']),
])
def test_reviewed_amendment_form_boundaries(engine, name, host, expected):
    result = engine.extract(name, source_url=f'https://{host}/' + quote(name))
    assert sorted(result['metadata'].get('document_kind', [])) == expected
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    assert all(name[f['start']:f['end']] == f['raw']
               for m in result['observations'] for f in m['fields'])


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


@pytest.mark.parametrize('name,host,target', [
    ('rc_10_fav_report_on_hr_3588.pdf', 'naturalresources.house.gov', 'report'),
    ('07.13.11_rcv_7_report.pdf', 'edworkforce.house.gov', 'report'),
    ('rc_37_wilson_motion_to_report.pdf', 'edworkforce.house.gov', 'report'),
    ('rc9_mceachin_002_to_authorization_and_oversight_plan.pdf', 'naturalresources.house.gov', 'oversight-plan'),
    ('Oversight Plan Vote Sheet.pdf', 'judiciary.house.gov', 'oversight-plan'),
])
def test_vote_action_and_plan_target_remain_literal_references(engine, name, host, target):
    result = engine.extract(name, source_url=f'https://{host}/' + quote(name))
    assert result['metadata']['document_kind'] == ['committee-vote']
    assert any(f.get('category') == target for m in result['observations'] for f in m['fields'])
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    assert all(name[f['start']:f['end']] == f['raw']
               for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name,kinds', [
    ('Report on Recorded Votes.pdf', ['report']),
    ('Report about Roll Call.pdf', ['report']),
    ('Oversight Plan on Recorded Votes.pdf', ['oversight-plan']),
    ('Report and Roll Call.pdf', ['committee-vote', 'report']),
    ('Roll Call & Report.pdf', ['committee-vote', 'report']),
    ('Oversight Plan and Vote Sheet.pdf', ['committee-vote', 'oversight-plan']),
    ('Authorization and Oversight Plan and Vote Sheet.pdf', ['committee-vote', 'oversight-plan']),
    ('Authorization and Oversight Plan.pdf', ['oversight-plan']),
    ('Vote Sheet & Oversight Plan.pdf', ['committee-vote', 'oversight-plan']),
    ('Roll Call Report TEXT.pdf', ['committee-vote', 'report']),
    ('Oversight Plan Vote Sheet TEXT.pdf', ['committee-vote', 'oversight-plan']),
])
def test_vote_topics_and_explicit_combined_documents_keep_primary_genres(engine, name, kinds):
    result = engine.extract(name, source_url='https://judiciary.house.gov/' + quote(name))
    assert sorted(result['metadata']['document_kind']) == kinds


@pytest.mark.parametrize('host', ['example.org', 'judiciary.house.gov.example.org'])
def test_unqualified_vote_action_names_keep_report_reading(engine, host):
    name = 'rc_37_wilson_motion_to_report.pdf'
    assert engine.extract(name, source_url=f'https://{host}/' + name)['metadata']['document_kind'] == ['report']


@pytest.mark.parametrize('name,host,kinds', [
    ('Testimony-Sheehan-Dem-Memo-EP-Hrg-on-Improving-the-Hydropower-Licensing-Process-2018-06-07.pdf', 'democrats-energycommerce.house.gov', ['testimony']),
    ('Testimony-HHS-Dem-Memo-FC-Hrg-on-Federal-Efforts-to-Combat-the-Opioid-Crisis-A-Status-Update-on-CARA-2017-10-25_2.pdf', 'democrats-energycommerce.house.gov', ['testimony']),
    ('FP-Opening-Memo-EE-Hrg-on-CFATS-A-Progress-Report-2018-06-14.pdf', 'democrats-energycommerce.house.gov', ['opening-statement']),
    ('Dem-Memo-EE-Hrg-on-CFATS-A-Progress-Report-2018-06-14.pdf', 'democrats-energycommerce.house.gov', ['committee-memorandum']),
    ('Memo-CMT-Patent-Demand-Letters-2015-2-24.pdf', 'democrats-energycommerce.house.gov', ['committee-memorandum']),
    ('memo_--_fc_markup_of_committee_print_05.06.25.pdf', 'naturalresources.house.gov', ['committee-memorandum']),
    ('FP-Opening-HE-Hrg-on-Memeber-Day-Testimony-and-Proposal-on-the-Opiod-Crisis-2017-10-11_0.pdf', 'democrats-energycommerce.house.gov', ['opening-statement']),
    ('FP-Opening-EE-HR-806-Nuclear-Waste-Policy-Amendments-Act-of-2017-2017-06-14.pdf', 'democrats-energycommerce.house.gov', ['opening-statement']),
    ('EEC Statement on Amendment to HR 4011 - Press Version1.pdf', 'oversight.house.gov', ['statement']),
    ('06.08.17 -RM EBJ STATEMENT ON AMENDMENT IN THE NATURE OF A SUBSTITUTE.pdf', 'science.house.gov', ['statement']),
    ('jct-letter-on-amendment-to-h.r-9173-and-h.r-9175.pdf', 'waysandmeans.house.gov', ['letter']),
    ('20171106-JCT-Estimated-Revenue-Effects-of-Amendment-in-the-Nature-of-a-Substitute-to-H.R.-1.pdf', 'waysandmeans.house.gov', ['revenue-estimate']),
])
def test_primary_genre_keeps_document_topics_as_literal_fields(engine, name, host, kinds):
    result = engine.extract(name, source_url=f'https://{host}/' + quote(name))
    assert sorted(result['metadata']['document_kind']) == kinds
    # Topic labels remain inspectable, even though they no longer supply kinds.
    assert {f['category'] for m in result['observations'] for f in m['fields'] if f.get('category')} - set(kinds)
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    assert all(name[f['start']:f['end']] == f['raw'] for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name,kinds', [
    ('Briefing Memo_ECCCPC Hearing_2019.06.20_Cars_Final with Witness List_1.pdf', ['committee-memorandum', 'witness-list']),
    ('Testimony and Committee Memo-2018-06-07.pdf', ['committee-memorandum', 'testimony']),
    ('Testimony with Committee Memo-2018-06-07.pdf', ['committee-memorandum', 'testimony']),
    ('FP-Opening-and-Committee-Memo.pdf', ['committee-memorandum', 'opening-statement']),
    ('Dem-Memo-and-Report.pdf', ['committee-memorandum', 'report']),
    ('Dem-Memo-with-Letter.pdf', ['committee-memorandum', 'letter']),
    ('FP-Opening-CHIP-CHC-Opening-Remarks-10-04-2017.pdf', ['opening-remarks', 'opening-statement']),
    ('Briefing Memo Witness List.pdf', ['committee-memorandum', 'witness-list']),
    ('Memo-EE-Markup-TSCA-Modernization-Act-Attachment-2015-5-14.pdf', ['attachment', 'committee-memorandum']),
    ('Statement and Amendment 1.pdf', ['amendment', 'statement']),
    ('Letter & Amendment 1.pdf', ['amendment', 'letter']),
    ('Amendment 1 to H.R. 123.pdf', ['amendment']),
])
def test_explicit_components_survive_primary_genre_selection(engine, name, kinds):
    result = engine.extract(name, source_url='https://democrats-energycommerce.house.gov/' + quote(name))
    assert sorted(result['metadata']['document_kind']) == kinds


@pytest.mark.parametrize('host', ['example.org', 'democrats-energycommerce.house.gov.example.org'])
def test_unqualified_memo_prefix_does_not_remove_literal_letter_kind(engine, host):
    name = 'Memo-CMT-Patent-Demand-Letters-2015-2-24.pdf'
    assert engine.extract(name, source_url=f'https://{host}/' + quote(name))['metadata']['document_kind'] == ['letter']
