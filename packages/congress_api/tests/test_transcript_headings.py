"""transcript_headings reads who a GPO printed hearing seats at the table (ct-sfra)."""
from congress_api.lake import transcript_headings
from congress_api.parsers.gpo_headings import name_key, transcript_entries

PRINT = """
                    COMMITTEE ON ENERGY AND COMMERCE

                          FRED UPTON, Michigan
                                 Chairman

JOE BARTON, Texas                    HENRY A. WAXMAN, California
  Chairman Emeritus                    Ranking Member
MIKE ROGERS, Michigan                FRANK PALLONE, Jr., New Jersey
ERIC A. ``RICK'' CRAWFORD, Arkansas  JOE COURTNEY, Connecticut

                Dave Conover, Republican Staff Director

                  JAMES M. JEFFORDS, Vermont, Chairman

                            C O N T E N T S

Noem, Hon. Kristi L., a Representative in Congress from South Dakota.....     5

                        WEDNESDAY, APRIL 25, 2012

    The subcommittee met, pursuant to call, at 10:00 a.m.
    Also present: Representative Hurt and Hon. G.K.
    Butterfield.
    Staff present: Ann Lee.

 OPENING STATEMENT OF HON. FRANK PALLONE, Jr., A REPRESENTATIVE IN
                  CONGRESS FROM THE STATE OF NEW JERSEY

    Mr. Pallone. Thank you.

STATEMENTS OF HON. KRISTI L. NOEM, A REPRESENTATIVE IN CONGRESS FROM THE
STATE OF SOUTH DAKOTA; AND HON. ROBERT HURT, A REPRESENTATIVE IN CONGRESS
              FROM THE COMMONWEALTH OF VIRGINIA

    [The prepared statement of Mrs. Noem follows:]

Prepared Statement of Hon. Tim Murphy, a Representative in Congress

    STATEMENT OF KATHERINE H. STEVENSON, ASSOCIATE DIRECTOR, BUSINESS
SERVICES, NATIONAL PARK SERVICE; ACCOMPANIED BY TIMOTHY R. SPISAK, ACTING
    ASSISTANT DIRECTOR, MINERALS AND REALTY; AND JANE ROE AND JOHN DOE

                    STATEMENTS OF COMMITTEE MEMBERS

  STATEMENT OF CHARLES G. ``CHIP'' GROAT, DIRECTOR, U.S. GEOLOGICAL SURVEY

    [Whereupon, at 4:15 p.m., the subcommittee was adjourned.]

                         SUBMITTED MATERIAL

   STATEMENT OF HON. JOHN McCAIN, U.S. SENATOR FROM ARIZONA

                        THURSDAY, APRIL 26, 2012

            STATEMENT OF HON. JOHN McCAIN, U.S. SENATOR FROM ARIZONA

    Senator McCain. The text stops here, mid-day.
"""


def entries(kind=None):
    return [(e['kind'], e['family'], e['given']) for e in transcript_entries(PRINT) if kind in (None, e['kind'])]


def test_roster_page_lists_the_committee_with_state_and_role():
    roster = [(e['family'], e['given'], e['style']) for e in transcript_entries(PRINT) if e['kind'] == 'roster']
    assert ('upton', 'f', 'Michigan') in roster  # The centred chairman is a column too.
    assert ('barton', 'j', 'Texas') in roster and ('rogers', 'm', 'Michigan') in roster
    assert ('pallone', 'f', 'New Jersey') in roster
    # Two spaces between long columns; a second roster after a staff line; no staff member.
    assert {('crawford', 'e', 'Arkansas'), ('courtney', 'j', 'Connecticut'), ('jeffords', 'j', 'Vermont, chair')} <= set(roster)
    assert not [r for r in roster if r[0] == 'conover']
    assert all(e['line'] is None for e in transcript_entries(PRINT) if e['kind'] == 'roster')


def test_headings_in_the_proceedings_name_each_person_once_per_heading():
    said = [e for e in entries() if e[0] != 'roster']
    assert said == [
        ('present', 'hurt', ''), ('present', 'butterfield', 'g'),  # not on the committee, at the hearing
        ('opening', 'pallone', 'f'),
        ('statement', 'noem', 'k'), ('statement', 'hurt', 'r'),
        ('statement', 'stevenson', 'k'),
        ('accompanying', 'spisak', 't'), ('accompanying', 'roe', 'j'), ('accompanying', 'doe', 'j'),
        ('statement', 'groat', 'c'),
        # The appendix's McCain heading is not read; the second day's, after its convening line, is.
        ('statement', 'mccain', 'j'),
    ]


def test_a_heading_keeps_its_style_and_line():
    noem = next(e for e in transcript_entries(PRINT) if e['family'] == 'noem')
    assert noem['name'] == 'HON. KRISTI L. NOEM'
    assert noem['style'] == 'A REPRESENTATIVE IN CONGRESS FROM THE STATE OF SOUTH DAKOTA'
    assert PRINT.split('\n')[noem['line'] - 1].startswith('STATEMENTS OF HON. KRISTI L. NOEM')
    spisak = next(e for e in transcript_entries(PRINT) if e['family'] == 'spisak')
    assert spisak['style'] == 'ACTING ASSISTANT DIRECTOR, MINERALS AND REALTY'


def test_a_print_without_contents_or_dates_is_read_from_its_start():
    text = "STATEMENT OF JANE ROE, COUNSEL\n\n    [Whereupon, the hearing was adjourned.]\n\nSTATEMENT OF ANN LEE\n"
    assert [(e['kind'], e['family']) for e in transcript_entries(text)] == [('statement', 'roe')]


def test_a_mixed_case_line_is_an_inserted_document_not_a_heading():
    text = "WEDNESDAY, MAY 1, 2019\n\nStatement of Hon. Dianne Feinstein, U.S. Senator\nSTATEMENT OF the American Bar\n"
    assert transcript_entries(text) == []


def test_name_key_drops_titles_suffixes_nicknames_and_accents():
    assert name_key("HON. FRANK PALLONE") == ('pallone', 'f')
    assert name_key("Bill Pascrell Jr.") == ('pascrell', 'b')
    assert name_key("ERIC A. ``RICK'' CRAWFORD") == ('crawford', 'e')
    assert name_key("THE HONORABLE NYDIA M. VELÁZQUEZ") == ('velazquez', 'n')
    assert name_key("REAR ADMIRAL RONALD J. RABAGO") == ('rabago', 'r')
    assert name_key("G.K. BUTTERFIELD") == ('butterfield', 'g')
    assert name_key("Michelle Lujan Grisham") == ('grisham', 'm')
    assert name_key("HON. LUCILLE ROYBAL-ALLARD") == ('allard', 'l')
    assert name_key("O'ROURKE") == ('orourke', '')
    assert name_key("") == ('', '')


def test_rows_build_the_lake_schema_and_read_bodies_that_are_not_utf8():
    body = ("<html><body><pre>" + PRINT + "</pre></body></html>").encode('utf-8') + b'\xff'
    row = transcript_headings.build_row('ab' * 32, 'gpo_html', body, parser_version='v')
    assert (row['status'], row['error_type']) == ('completed', None)
    assert [e['family'] for e in row['entries'] if e['kind'] == 'statement'] == ['noem', 'hurt', 'stevenson', 'groat', 'mccain']
    table = transcript_headings.table([row])
    assert table.schema == transcript_headings.ARROW_SCHEMA
    assert table.to_pylist()[0]['entries'][0]['kind'] == 'roster'


def test_only_the_gpo_html_source_is_read():
    try:
        transcript_headings.build_row('ab' * 32, 'mods', b'', parser_version='v')
    except ValueError:
        return
    raise AssertionError('another source must refuse')


def test_the_version_is_one_stable_digest_for_the_one_source():
    versions = transcript_headings.current_versions()
    assert set(versions) == {'gpo_html'} and len(versions['gpo_html']) == 64
    assert transcript_headings.current_versions() == versions
