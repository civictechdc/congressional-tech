"""Literal legislative wording must not become verified status or identity."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def observe(engine, name, rule):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in result['observations']:
        for f in m['fields']:
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
            assert name[f['start']:f['end']] == f['raw']
    fields = [f for m in result['observations'] if m['rule'] == rule for f in m['fields']]
    assert all(f['code'] is None and f['context'] is None and not f['candidates'] for f in fields)
    return result, fields


@pytest.mark.parametrize('name,expected', [
    ('S.123_Managers_Substitute_Amendment.pdf', 'Managers_Substitute_Amendment'),
    ('s123_managers_substitute_amendmentpdf', 'managers_substitute_amendment'),
    ('S.123_Managers_Substitute _Amendment.pdf.pdf', 'Managers_Substitute _Amendment'),
    ('s123_managers_substitute-_amendmentpdf', 'managers_substitute-_amendment'),
    ('S.Res.10_Managers_Preamble_Amendment.pdf', 'Managers_Preamble_Amendment'),
    ('S.Res.10_Managers_Resolving_Clause_Amendment.pdf', 'Managers_Resolving_Clause_Amendment'),
    ('S.Res.10_Managers_Title_Amendment.pdf', 'Managers_Title_Amendment'),
    ("H.R.123_Manager's_Substitute_Amendment2.pdf", "Manager's_Substitute_Amendment"),
    ('S.123_Manager’s_Substitute_Amendment.pdf', 'Manager’s_Substitute_Amendment'),
    ('s-res-123-managers-preamble-amendment-2', 'managers-preamble-amendment'),
    ('123ManagersSubstituteAmendment.pdf', 'ManagersSubstituteAmendment'),
])
def test_explicit_managers_amendment_components(engine, name, expected):
    _, fields = observe(engine, name, 'managers-amendment-wording')
    assert [(f['name'], f['raw']) for f in fields] == [('label', expected)]


@pytest.mark.parametrize('name,expected', [
    ("FY24 CJS Manager's Package.pdf", "Manager's Package"),
    ('fy24-interior-managers-package&download=1', 'managers-package'),
    ('Managers Package Summaries 2.8.24 (FINAL) (Post Mark Up)(2).pdf', 'Managers Package'),
    ('managers_packages.pdf', 'managers_packages'),
])
def test_package_wording_does_not_assign_contents(engine, name, expected):
    result, fields = observe(engine, name, 'managers-package-wording')
    assert [f['raw'] for f in fields] == [expected]
    assert not any(m['rule'] == 'managers-amendment-wording' for m in result['observations'])


@pytest.mark.parametrize('name,expected', [
    ('S. 123 As Reported.pdf', 'As Reported'),
    ('S. 123 (Reported Out).pdf', 'Reported Out'),
    ('s-123-reported-outpdf', 'reported-out'),
    ('s-123-as-reported2', 'as-reported'),
    ('S123_asreported_WAL12345.pdf', 'asreported'),
    ('S.123_Reported.pdf', 'Reported'),
    ('s123_reportedpdf', 'reported'),
    ('Items Reported Favorably.pdf', 'Reported Favorably'),
    ('BILLS-113-HR4660ih(asfiled).pdf', 'asfiled'),
    ('BILLS-119HR2asIntroducedih.pdf', 'asIntroduced'),
    ('BILLS-119HR2asamendedih.pdf', 'asamended'),
    ('HRPT-119-HR2-AsFiled.pdf', 'AsFiled'),
    ('S.123 As Reported&download=1', 'As Reported'),
    ('03-01-23_h._res._123_as_amended_tally_sheet.pdf', 'as_amended'),
    ('Senate Commerce Hearing - Greg Guice (as filed).pdf', 'as filed'),
])
def test_edition_wording_preserves_official_codes_and_prior_text(engine, name, expected):
    result, fields = observe(engine, name, 'edition-wording')
    assert [(f['name'], f['raw']) for f in fields] == [('qualifier_wording', expected)]
    assert all('not verified' in f['note'] for f in fields)
    if name.startswith('BILLS-'):
        versions = [f for m in result['observations'] for f in m['fields'] if f['name'] == 'version_token']
        assert [f['raw'] for f in versions] == ['ih']
        assert versions[0]['code'] == 'ih'
        if 'asfiled' in name:
            assert any(f['name'] == 'annotation' and f['raw'] == 'asfiled' for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name,expected', [
    ('BILLS-119-HR2ih-STRSubcommitteeMarkup.pdf', 'SubcommitteeMarkup'),
    ('BILLS-119-FC-AP-FY2026-AP00-FY2026DefenseFullCommitteeMark.pdf', 'FullCommitteeMark'),
    ('BILLS-119-SC-AP-FY2026-LegBranch-SubcommitteeMark.pdf', 'SubcommitteeMark'),
    ('BILLS-119pih-DIOAFY2026SubcommitteeMark.pdf', 'SubcommitteeMark'),
    ('full-committee-markup-of-defense-appropriations-acts', 'full-committee-markup'),
    ('subcommittee-markup-of-the-fy2026-interior-and-environment-bill', 'subcommittee-markup'),
    ('Full Committee Mark Up.pdf', 'Full Committee Mark Up'),
    ('Subcommittee Markpdf.pdf', 'Subcommittee Mark'),
    ('PreFullCommitteeMark.pdf', 'FullCommitteeMark'),
])
def test_committee_mark_wording_retains_the_printed_scope(engine, name, expected):
    _, fields = observe(engine, name, 'committee-mark-wording')
    assert [(f['name'], f['raw']) for f in fields] == [('label', expected)]


@pytest.mark.parametrize('rule,name', [
    ('managers-amendment-wording', 'Pharmacy Benefit Managers.pdf'),
    ('managers-amendment-wording', 'S123_Managers.pdf'),
    ('managers-amendment-wording', 'PreManagersSubstituteAmendment.pdf'),
    ('managers-amendment-wording', 'ManagersSubstituteAmendmentman.pdf'),
    ('managers-amendment-wording', 'Topic%20ManagersSubstituteAmendment.pdf'),
    ('managers-package-wording', 'AssetManagerPackages.pdf'),
    ('managers-package-wording', 'ManagersPackaging.pdf'),
    ('edition-wording', 'Unreported.pdf'),
    ('edition-wording', 'WasReported.pdf'),
    ('edition-wording', 'AsReportedness.pdf'),
    ('edition-wording', 'reported to board.pdf'),
    ('edition-wording', 'TexasAmended.pdf'),
    ('edition-wording', 'Topic%20AsReported.pdf'),
    ('committee-mark-wording', 'SubcommitteeMarket.pdf'),
    ('committee-mark-wording', 'FullCommitteeMarketing.pdf'),
    ('committee-mark-wording', 'presubcommitteemark.pdf'),
    ('committee-mark-wording', '%FullCommitteeMark.pdf'),
    ('committee-mark-wording', 'Topic%20FullCommitteeMark.pdf'),
    ('managers-amendment-wording', 'HHRG-119-IF00-Wstate-Managers_Substitute_Amendment-20250318.pdf'),
    ('managers-package-wording', 'HHRG-119-IF00-Wstate-Managers_Package-20250318.pdf'),
    ('edition-wording', 'HHRG-119-IF00-Wstate-As_Reported-20250318.pdf'),
    ('committee-mark-wording', 'HHRG-119-IF00-Wstate-FullCommitteeMark-20250318.pdf'),
])
def test_word_boundaries_and_person_slots_stay_protected(engine, rule, name):
    _, fields = observe(engine, name, rule)
    assert fields == []


def test_contradictory_printed_scope_does_not_rewrite_source_scope(engine):
    name = 'BILLS-119-SC-AP-FY2026-AP00-FY2026NSRPFullCommitteeMark.pdf'
    result, fields = observe(engine, name, 'committee-mark-wording')
    assert [f['raw'] for f in fields] == ['FullCommitteeMark']
    assert any(f['name'] == 'scope_token' and f['raw'] == 'SC' for m in result['observations'] for f in m['fields'])


def test_existing_summary_and_fallback_remain_available(engine):
    name = 'Managers Package Summaries 2.8.24 (FINAL) (Post Mark Up)(2).pdf'
    result, _ = observe(engine, name, 'managers-package-wording')
    assert any(m['rule'] == 'summary-component-wording' for m in result['observations'])
    assert any(m['rule'] == 'assumed-name' for m in result['observations'])
