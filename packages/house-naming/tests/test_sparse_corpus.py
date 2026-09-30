"""Literal gaps from the complete 1,317-name review, plus ambiguity controls."""
import pytest

from house_naming import Engine
from house_naming.corpus import filename_review_category, residual_fields, DESCRIPTIVE_FIELDS
from house_naming.filename_corpus import build_corpus


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in (*result['observations'], *result['suppressed']):
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    residual_fields(result, field_names=DESCRIPTIVE_FIELDS, include_unstructured=True)
    return result


def values(result, key):
    return [f['raw'] for m in result['observations'] for f in m['fields'] if f['name'] == key]


@pytest.mark.parametrize('name,expected', [
    ('h1406_rh.xml', {'measure_token':'h', 'measure_number':'1406', 'version_token':'rh'}),
    ('h1549_ih.xml', {'measure_number':'1549', 'version_token':'ih'}),
    ('h2642_eas.xml', {'measure_number':'2642', 'version_token':'eas'}),
    ('hc25_rh.xml', {'measure_token':'hc', 'measure_number':'25', 'version_token':'rh'}),
    ('hj59_eas.xml', {'measure_token':'hj', 'measure_number':'59', 'version_token':'eas'}),
    ('h8872_rh_xml.pdf', {'filename_format_token':'xml', 'extension':'pdf'}),
    ('RCP_H1048_xml.pdf', {'print_token':'RCP', 'measure_number':'1048', 'filename_format_token':'xml'}),
    ('rcp_h2616_h2617_xml_0.pdf', {'measure_number':'2617', 'filename_format_token':'xml'}),
    ('RCP_277_xml.pdf', {'print_token':'RCP', 'local_number_token':'277', 'filename_format_token':'xml'}),
    ('GAO-24-107597.pdf', {'agency_identifier':'GAO-24-107597'}),
    ('Treaty Doc. 117-1.pdf', {'citation_marker':'Treaty Doc', 'citation_congress':'117', 'citation_number':'1'}),
    ('Treaty Doc. 115-31.pdf', {'citation_number':'31'}),
    ('JCX-11-22.pdf', {'series_token':'JCX', 'series_number':'11', 'series_year_token':'22'}),
    ('JCT x-32-21.pdf', {'series_token':'JCT x', 'series_number':'32', 'series_year_token':'21'}),
    ('JCX1022.pdf', {'series_identifier':'1022'}),
    ('x-16-221.pdf', {'series_identifier':'16-221'}),
    ('PFLUGE_184_xml.pdf', {'local_prefix':'PFLUGE', 'local_number_token':'184', 'filename_format_token':'xml'}),
    ('barr_006_xml.pdf', {'local_prefix':'barr', 'local_number_token':'006'}),
    ('willtx_002_xml.pdf', {'local_prefix':'willtx', 'local_number_token':'002'}),
    ('auchin_002_xml_draft.pdf', {'local_prefix':'auchin', 'draft_label':'draft'}),
    ('TT_Smith.pdf', {'local_code_token':'TT', 'subject_token':'Smith'}),
    ('tt_Smith.pdf', {'local_code_token':'tt', 'subject_token':'Smith'}),
    ('sfr-Smith.pdf', {'local_code_token':'sfr', 'subject_token':'Smith'}),
    ('MGR_01.pdf', {'local_code_token':'MGR'}),
    ('updated_ans.pdf', {'local_code_token':'ans', 'qualifier_wording':'updated'}),
    ('attachment_a_-_question_12.pdf', {'item_token':'a', 'question_identifier':'12'}),
    ('Exhibit B5_2021XXXX_title.pdf', {'item_token':'B5', 'partial_date_token':'2021XXXX'}),
    ('III.-A.-Witness-Testimonies-AY.pdf', {'outline_identifier':'III.-A.'}),
    ('rev_Q1a Data China_Redacted1.pdf', {'component_identifier':'1a', 'qualifier_wording':'Redacted', 'local_number_token':'1'}),
])
def test_source_components(engine, name, expected):
    result = checked(engine, name)
    for key, raw in expected.items():
        assert raw in values(result, key), (key, result)


@pytest.mark.parametrize('name', ['ALB19A19.pdf','FLO21C77.pdf','ELL26080.pdf','MDM19E06.pdf','HEN205141.pdf'])
def test_drafting_identifier_is_atomic(engine, name):
    result = checked(engine, name)
    assert values(result,'drafting_identifier') == [name[:-4]]
    assert not values(result, 'date_token')
    assert not values(result, 'congress')


@pytest.mark.parametrize('name,source,target', [
    ('BILL-TO-BILL_h2868_rh_xml_to_RCP_H2868etc_xml.pdf', 'h2868_rh_xml', 'RCP_H2868etc_xml'),
    ('bill-to-bill_h3838_rh_xml-57-28-to_rcp_h3838_xml_0.pdf', 'h3838_rh_xml-57-28', 'rcp_h3838_xml_0'),
])
def test_comparison_keeps_each_reference_on_its_own_side(engine, name, source, target):
    result = checked(engine, name)
    assert values(result, 'comparison_source') == [source]
    assert values(result, 'comparison_target') == [target]
    sides = [f for m in result['observations'] for f in m['fields'] if f['name'] in {'comparison_source','comparison_target'}]
    refs = [f for m in result['observations'] for f in m['fields'] if f['name']=='measure_number']
    assert len(refs) == 2
    assert all(sum(side['start'] <= f['start'] < f['end'] <= side['end'] for f in refs)==1 for side in sides)
    assert not values(result, 'congress')


@pytest.mark.parametrize('name,label', [
    ('PortmanOpeningStatement.pdf.pdf','OpeningStatement'),
    ('CommerceTestimonyMulligan.pdf','Testimony'),
    ('chief_jthomasmangertestimony.pdf','testimony'),
    ('mr_paul_ewilliamstestimonysenatebudgetcommittee.pdf','testimony'),
    ('RearAdmiralChase.PreparedStatement.pdf','PreparedStatement'),
    ('BioCiOExternal.pdf','Bio'),('shortbio-weimer.pdf','shortbio'),
    ('Smith Answers for the Record.pdf','Answers for the Record'),
    ('Smith Responses for the Record.pdf','Responses for the Record'),
    ('Smith Responses.pdf','Responses'),
    ('Responses to Senate Judiciary.pdf','Responses'),
    ('Responses to questions from Senator Smith.pdf','Responses'),
    ('Master Amendment List.pdf','Master Amendment List'),('Exhibit List.pdf','Exhibit List'),
    ('Appendix.pdf','Appendix'),('Attachment.pdf','Attachment'),('Slide 4.pdf','Slide'),
    ('Issue Brief.pdf','Issue Brief'),('Brochure.pdf','Brochure'),('Flyer.pdf','Flyer'),
    ('Pamphlet.pdf','Pamphlet'),('Graphic.pdf','Graphic'),('Scatterplot.pdf','Scatterplot'),
    ('Bill Text.pdf','Bill Text'),('Legislation Text.pdf','Legislation Text'),
    ('Committee Memo.pdf','Committee Memo'),('Revenue Estimate.pdf','Revenue Estimate'),
    ("Chairman's Mark.pdf", "Chairman's Mark"),
    ("Description of the Chairman's Mark.pdf", "Description of the Chairman's Mark"),
])
def test_literal_wording(engine, name, label):
    assert label in values(checked(engine, name), 'label')


@pytest.mark.parametrize('raw,label', [
    ('Tesitmony','Testimony'),('Tesimony','Testimony'),('Testiomony','Testimony'),
    ('Testimomy','Testimony'),('Testmiony','Testimony'),('tedtimony','Testimony'),
    ('Statemet','Statement'),('statmement','Statement'),('TRASNCRIPTION','Transcription'),
    ('Questionaire','Questionnaire'),('Quetions','Questions'),('reponses','Responses'),('Wtiness List','Witness List'),
])
def test_alias_keeps_raw_spelling_and_identifies_reading(engine, raw, label):
    result = checked(engine, 'Smith-'+raw+'.pdf')
    field, = [f for m in result['observations'] if m['rule'].startswith('document-alias-') for f in m['fields']]
    assert (field['raw'],field['label']) == (raw,label)
    assert not field['code'] and not field['vocabulary_url']


@pytest.mark.parametrize('name,qualifiers', [
    ('Carey FINAL.pdf',['FINAL']),('Kenneth JT Trosper-Updated.pdf',['Updated']),
    ('Baldwin_01 (as modified again).pdf',['as modified again']),
    ('Welch2ModifiedSigned.pdf',['Modified','Signed']),
    ('Pages from GFI Production 02 (OCR).pdf',['OCR']),
    ('Smith-Cleared.pdf',['Cleared']),('Smith-Unofficial.pdf',['Unofficial']),
])
def test_independent_terminal_qualifiers(engine, name, qualifiers):
    result=checked(engine,name)
    assert values(result,'qualifier_wording') == qualifiers
    assert not values(result,'revision_number')


def test_opaque_prefix_does_not_hide_descriptive_wording(engine):
    for text,field,raw in [('enrichment-modernization-act-discussion-draft','draft_label','discussion-draft'),
                           ('sbc-affordability-report-final','label','report')]:
        name='0123456789abcdef0123456789abcdef.'+text+'.pdf'
        result=checked(engine,name)
        assert values(result,'opaque_identifier')==['0123456789abcdef0123456789abcdef']
        assert raw in values(result,field)


@pytest.mark.parametrize('name,expected', [('202103xx.pdf',['2021-03']),('2021XXXX.pdf',['2021']),('202113xx.pdf',[])])
def test_partial_date_does_not_invent_a_day(engine,name,expected):
    result=checked(engine,name)
    field,=[f for m in result['observations'] for f in m['fields'] if f['name']=='partial_date_token']
    assert field['candidates']==expected
    assert not values(result,'date_token')


def test_four_digit_prefix_keeps_identifier_alternative(engine):
    result=checked(engine,'0205-Smith.pdf')
    assert '0205' in values(result,'generic_identifier')
    assert values(result,'possible_month_day_token')==['0205']
    assert not values(result,'date_token')
    assert not values(checked(engine,'9975-Smith.pdf'),'possible_month_day_token')


def test_noncanonical_report_does_not_relax_strict_validation(engine):
    result=checked(engine,'CRPT117hrpt13.pdf')
    assert values(result,'congress')==['117']
    assert values(result,'publication_number')==['13']
    assert not result['valid']


@pytest.mark.parametrize('name', ['Testimonial.pdf','understatement.pdf','reStatementSuffix.pdf','shortbiology.pdf',
    'Responses to Market Conditions.pdf','National Response Plan.pdf','Questionable.pdf',
    'HHRG-119-IF00-Wstate-Testimony-20250318.pdf'])
def test_word_fragments_and_owned_person_slots_are_protected(engine,name):
    assert not values(checked(engine,name),'label')


@pytest.mark.parametrize('name', ['Public Health Questionnaire.pdf','Final report discusses Smith SJQ.pdf',
    'SJQ answers about Final Assessment.pdf','Final Program Opening Remarks.pdf'])
def test_title_words_are_not_independent_qualifiers(engine,name):
    assert not values(checked(engine,name),'qualifier_wording')


@pytest.mark.parametrize('name,category', [('Default.aspx','web-endpoint'),('Error.aspx','web-endpoint'),
    ('index.cfm','web-endpoint'),('waf.htm','web-endpoint'),('mets.xml','metadata-file'),('premis.xml','metadata-file'),
    ('master.m3u8','media-or-stream'),('offered.zip','container'),('43753.pdf','generic-identifier'),
    ('113-506.pdf','generic-identifier'),('Budd_4.pdf','unclassified-name-or-title'),('Testimony.pdf','extracted-syntax')])
def test_audit_categories_do_not_claim_missing_document_types(engine,name,category):
    assert filename_review_category(checked(engine,name)) == category


def test_corpus_publishes_review_categories(tmp_path):
    result=build_corpus(['master.m3u8','offered.zip','mets.xml','Budd_4.pdf','Testimony.pdf'],tmp_path)
    assert result['filename_review_categories']=={'media-or-stream':1,'container':1,'metadata-file':1,
        'unclassified-name-or-title':1,'extracted-syntax':1}


@pytest.mark.parametrize('name,field,value', [
    ('h6323fs_rh_xml.pdf','local_modifier','fs'),
    ('RCP_3935_2_xml_0.pdf','local_modifier','2'),
    ('CJS RCP FINAL_xml.pdf','qualifier_wording','FINAL'),
    ('updated_ans_for_website.pdf','local_code_token','ans'),
    ('44602-ltbotestimony.pdf','label','testimony'),
    ('drmollydahltestimonysenatebudgetcommittee1.pdf','label','testimony'),
    ('bell_kolbe_testimonies_fy271.pdf','label','testimonies'),
    ('Brown Jackson Responses1.pdf','label','Responses'),
    ('FINAL SAA USMCA.pdf','qualifier_wording','FINAL'),
])
def test_remaining_observed_variants(engine,name,field,value):
    assert value in values(checked(engine,name),field)


@pytest.mark.parametrize('name,number', [
    ('BILLS-118-AmendmenttoHR467-B001303-Amdt-3.pdf','467'),
    ('BILLS-119-AMDtoHR9393-H9393-AMD_01XMLRepJames-J000307-Amdt-AMDtoHR9393-H9393-AMD_01XMLRepJames.pdf','9393'),
])
def test_joined_explicit_amendment_target_reuses_measure_reader(engine,name,number):
    assert number in values(checked(engine,name),'measure_number')


def test_internal_member_reference_requires_caller_roster_and_boundary(engine):
    name='BILLS-118pih-HR___TheOnlineDatingSafetyActof2023RepValadao.pdf'
    assert not values(engine.extract(name),'member_surname_token')
    result=engine.extract(name,member_surnames={'118':['Valadao']})
    assert values(result,'member_surname_token')==['Valadao']
    assert not values(engine.extract(name,member_surnames={'119':['Valadao']}),'member_surname_token')
    for token in ['RepChair','RepMem','RepValadaotest']:
        result=engine.extract('BILLS-118pih-HR___Title'+token+'.pdf',member_surnames={'118':['Valadao']})
        assert not values(result,'member_surname_token')
    for m in result['observations']:
        for f in m['fields']:
            assert result['input'][f['start']:f['end']]==f['raw']


def test_rcp_inside_owned_witness_subject_is_not_refined(engine):
    result=checked(engine,'HHRG-119-IF00-Wstate-RCP_H1048_xml-20250318.pdf')
    assert not values(result,'measure_number')
    assert not values(result,'print_token')


def test_rcp_refinement_stops_at_prose(engine):
    result=checked(engine,'RCP_H1048_xml_some_other_title_h99_xml.pdf')
    rcp=[m for m in result['observations'] if m['rule']=='rcp-short-measure']
    assert [f['raw'] for m in rcp for f in m['fields'] if f['name']=='measure_number']==['1048']


@pytest.mark.parametrize('name,field,raw', [
    ('021214testimony).docx','label','testimony'),
    ('11jul2018oBoyleSTMNT.pdf','label','STMNT'),
    ('grassley061819statement','label','statement'),
    ('AF Military Justice Process Slide_03-06-19.pdf','date_token','03-06-19'),
    ('aaro-slides-112124','short_date_token','112124'),
    ('bacontestimony03062019','date_token','03062019'),
    ('s-res-406-as-amended','qualifier_wording','as-amended'),
])
def test_full_corpus_regressions_preserve_existing_information(engine,name,field,raw):
    assert raw in values(checked(engine,name),field)


def test_drafting_id_replaces_incidental_short_date_but_retains_suppressed_reading(engine):
    result=checked(engine,'FLO23798.pdf')
    assert values(result,'drafting_identifier')==['FLO23798']
    assert not values(result,'short_date_token')
    assert any(m['rule']=='short-date-unpadded' and m['raw']=='23798' for m in result['suppressed'])


def test_q_component_does_not_invent_question_or_quarter_role(engine):
    result=checked(engine,'Exhibit 14_202112xx_DRAFT_ NOT DELIVERED_2021 Q4 Information Security Report1.pdf')
    assert values(result,'component_marker')==['Q']
    assert values(result,'component_identifier')==['4']
    assert not values(result,'question_identifier')
    assert not values(result,'quarter_number')


def test_longer_roster_surname_cannot_backtrack_to_a_shorter_person(engine):
    name='BILLS-118-HR5555-M001215-Amdt-5555-FC-AINS_01XMLfiledbyRepMiller-MeekstoHR5555.pdf'
    result=engine.extract(name,member_surnames={'118':['Miller','Miller-Meeks']})
    assert 'Miller' not in values(result,'member_surname_token')
    result=engine.extract('BILLS-118pih-TitleRepMiller-Meeks.pdf',member_surnames={'118':['Miller','Miller-Meeks']})
    assert values(result,'member_surname_token')==['Miller-Meeks']


def test_short_supplemental_report_keeps_local_modifiers(engine):
    result=checked(engine,'h615nr_supp_rpt.pdf')
    assert values(result,'measure_number')==['615']
    assert values(result,'local_modifier')==['nr']
    assert values(result,'document_abbreviation')==['supp_rpt']
    assert not values(result,'congress') and not values(result,'version_token')


def test_modified_chairman_mark_is_literal_wording(engine):
    result=checked(engine,'Clean_Energy_for_America_Act_Chairmans_Modified_Mark.pdf')
    assert 'Chairmans_Modified_Mark' in values(result,'label')


def test_appendix_keeps_printed_letter_identifier(engine):
    result=checked(engine,'Appendix B5.pdf')
    assert values(result,'item_token')==['B5']


def test_bare_witness_alias_does_not_infer_statement_type(engine):
    result=checked(engine,'Wtiness-Jones.pdf')
    assert values(result,'label')==['Wtiness']
    assert not values(result,'document_token')


def test_appendix_heading_does_not_take_a_trailing_date(engine):
    result=checked(engine,'omarova-testimony-and-appendix-91818')
    assert values(result,'short_date_token')==['91818']
    assert '91818' not in values(result,'item_token')
