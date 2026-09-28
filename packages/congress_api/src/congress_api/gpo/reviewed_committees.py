"""Individually reviewed GPO committee assignments where MODS has no authority ID.

These decisions identify documents, not meetings. The publisher's native fields
stay untouched; the explorer retains this table as a separate source snapshot.
Reviewed 2026-09-28 against official metadata, covers, testimony and calendars.
"""

REVIEWED = {'CHRG-106shrg63232': {'congress': 106,
                       'committee_codes': ['ssev00'],
                       'explanation': 'Cover explicitly names Senate Environment and Public Works, '
                                      'alongside its Transportation and Infrastructure '
                                      'subcommittee. The 106th Congress official committee list '
                                      'identifies ssev00. Do not infer a separate meeting from '
                                      'this multi-date volume.',
                       'source_urls': ['https://www.govinfo.gov/metadata/pkg/CHRG-106shrg63232/mods.xml',
                                       'https://www.govinfo.gov/content/pkg/CHRG-106shrg63232/html/CHRG-106shrg63232.htm',
                                       'https://api.congress.gov/v3/committee/106']},
 'CHRG-106shrg63628': {'congress': 106,
                       'committee_codes': ['ssfr00'],
                       'explanation': 'Cover explicitly names Senate Foreign Relations and two '
                                      'subcommittees. The 106th Congress official committee list '
                                      'identifies ssfr00; historical subcommittee names are '
                                      'preserved without guessing their identifiers.',
                       'source_urls': ['https://www.govinfo.gov/metadata/pkg/CHRG-106shrg63628/mods.xml',
                                       'https://www.govinfo.gov/content/pkg/CHRG-106shrg63628/html/CHRG-106shrg63628.htm',
                                       'https://api.congress.gov/v3/committee/106']},
 'CHRG-107hhrg83338': {'congress': 107,
                       'committee_codes': ['hsap00', 'hsap11'],
                       'explanation': 'The retained transcript names Robert Mueller and June 21, '
                                      '2002. FBI official testimony matches speaker, date and FBI '
                                      'reorganization subject and explicitly identifies the House '
                                      'Appropriations Commerce, Justice, State, Judiciary and '
                                      'Related Agencies subcommittee. The 107th Congress list '
                                      'supports parent hsap00 and child hsap11.',
                       'source_urls': ['https://www.govinfo.gov/metadata/pkg/CHRG-107hhrg83338/mods.xml',
                                       'https://www.govinfo.gov/content/pkg/CHRG-107hhrg83338/html/CHRG-107hhrg83338.htm',
                                       'https://archives.fbi.gov/archives/news/testimony/the-new-fbi-focus',
                                       'https://api.congress.gov/v3/committee/107']},
 'CHRG-108hhrg87731': {'congress': 108,
                       'committee_codes': ['hsap00', 'hsap03'],
                       'explanation': 'Opening statement explicitly identifies this as the '
                                      'District of Columbia Appropriations subcommittee fiscal '
                                      '2004 budget hearing, April 9, 2003; the 108th Congress '
                                      'committee list supports hsap03 and parent hsap00.',
                       'source_urls': ['https://www.govinfo.gov/metadata/pkg/CHRG-108hhrg87731/mods.xml',
                                       'https://www.govinfo.gov/content/pkg/CHRG-108hhrg87731/html/CHRG-108hhrg87731.htm',
                                       'https://api.congress.gov/v3/committee/108']},
 'CHRG-109shrg25756': {'congress': 109,
                       'committee_codes': ['ssap00'],
                       'explanation': 'MODS corporate author explicitly lists United States / '
                                      'Congress / Senate / Committee on Appropriations, supported '
                                      'by the 109th Congress list. PDF cover is a DHS '
                                      'Congressional Budget Justification, not a hearing '
                                      'transcript. Associate this document with the '
                                      'source-credited committee without inventing a hearing.',
                       'source_urls': ['https://www.govinfo.gov/metadata/pkg/CHRG-109shrg25756/mods.xml',
                                       'https://www.govinfo.gov/content/pkg/CHRG-109shrg25756/html/CHRG-109shrg25756.htm',
                                       'https://api.congress.gov/v3/committee/109',
                                       'https://www.govinfo.gov/content/pkg/CHRG-109shrg25756/pdf/CHRG-109shrg25756.pdf'],
                       'category': 'supporting',
                       'source_document_type': 'Congressional Budget Justification'},
 'CHRG-109shrg26254': {'congress': 109,
                       'committee_codes': ['sseg00'],
                       'explanation': 'Root MODS names Committee on Energy and Natural Resources '
                                      'without an authorityId; the cover and October 25, 2005 '
                                      'opening identify the Senate committee. The 109th Congress '
                                      'list supports sseg00.',
                       'source_urls': ['https://www.govinfo.gov/metadata/pkg/CHRG-109shrg26254/mods.xml',
                                       'https://www.govinfo.gov/content/pkg/CHRG-109shrg26254/html/CHRG-109shrg26254.htm',
                                       'https://api.congress.gov/v3/committee/109']},
 'CHRG-112hhrg71540': {'congress': 112,
                       'committee_codes': ['hsap00', 'hsap18'],
                       'explanation': 'PDF page 1 names the Military Construction and Veterans '
                                      'Affairs subcommittee, Richard Griffin, and March 9, 2011. '
                                      'Matching VA OIG official testimony explicitly names House '
                                      'Appropriations and the subcommittee. The 112th Congress '
                                      'list supports hsap18 and parent hsap00.',
                       'source_urls': ['https://www.govinfo.gov/metadata/pkg/CHRG-112hhrg71540/mods.xml',
                                       'https://www.govinfo.gov/content/pkg/CHRG-112hhrg71540/html/CHRG-112hhrg71540.htm',
                                       'https://www.vaoig.gov/sites/default/files/document/2023-08/VAOIG-statement-20110309-griffin.pdf',
                                       'https://api.congress.gov/v3/committee/112']},
 'CHRG-113hhrg85023': {'congress': 113,
                       'committee_codes': ['hsap00', 'hsap18'],
                       'explanation': 'Transcript and PDF name all four witnesses and March 13, '
                                      '2013. Official House event 100414 matches all four '
                                      'witnesses, date and subject and explicitly identifies '
                                      'Military Construction, Veterans Affairs and Related '
                                      'Agencies (Appropriations). Its AP/AP18 source path '
                                      'corroborates hsap18 and parent hsap00. No meeting '
                                      'association is created by this committee decision.',
                       'source_urls': ['https://www.govinfo.gov/metadata/pkg/CHRG-113hhrg85023/mods.xml',
                                       'https://www.govinfo.gov/content/pkg/CHRG-113hhrg85023/html/CHRG-113hhrg85023.htm',
                                       'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=100414',
                                       'https://api.congress.gov/v3/committee/113']},
 'CHRG-118hhrg55711': {'congress': 118,
                       'category': 'committee_print',
                       'source_document_type': 'COMMITTEE PRINT',
                       'committee_codes': ['hsgo00'],
                       'explanation': 'Cover and May 15, 2024 opening explicitly identify House '
                                      'Oversight and Accountability, Serial CP:118-11. Committee '
                                      'identity is hsgo00 in the 118th Congress list (which uses '
                                      'the current name Oversight and Government Reform); retain '
                                      'the source-era name. This is a business-meeting committee '
                                      'print, not proof of a distinct hearing.',
                       'source_urls': ['https://www.govinfo.gov/metadata/pkg/CHRG-118hhrg55711/mods.xml',
                                       'https://www.govinfo.gov/content/pkg/CHRG-118hhrg55711/html/CHRG-118hhrg55711.htm',
                                       'https://api.congress.gov/v3/committee/118']}}

REVIEWED['CHRG-111shrg86304'] = {
    'congress': 111,
    'explanation': 'The printed title page says 113th Congress, but its proceeding date is June 8, 2010 and the GovInfo package metadata identifies the 111th Congress. The catalog retains Congress 111; the conflicting printed label remains in the linked source.',
    'source_urls': [
        'https://www.govinfo.gov/metadata/pkg/CHRG-111shrg86304/mods.xml',
        'https://www.govinfo.gov/content/pkg/CHRG-111shrg86304/html/CHRG-111shrg86304.htm',
    ],
}

REVIEWED['CHRG-110shrg41912'] = {
    'congress': 110,
    'explanation': 'The publisher errata says the printed Hearing on Pending Legislation title was an error and should read Markup of Pending Legislation. The package retains both its proceeding file and the errata sheet; they do not establish two meetings.',
    'source_urls': [
        'https://www.govinfo.gov/content/pkg/CHRG-110shrg41912/html/CHRG-110shrg41912-err.htm',
        'https://www.govinfo.gov/metadata/pkg/CHRG-110shrg41912/mods.xml',
    ],
}

def reviewed(row):
    decision = REVIEWED.get(row.get("package_id"))
    return decision if decision and str(row.get("congress")) == str(decision["congress"]) else None
