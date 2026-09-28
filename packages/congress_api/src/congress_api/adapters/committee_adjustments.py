"""Reviewed exceptions to source classifications and omissions.

These are curated decisions with public evidence, not altered API responses.
Additions are bounded to the documented Congress; no future term is assumed.
"""

ADJUSTMENTS = (
    {
        'code': 'jcfm00', 'first_congress': 106, 'last_congress': 106,
        'values': {'committee_type': 'commission_or_caucus'},
        'explanation': 'The Medicare Commission was a bipartisan commission. Historical meeting notices are available in the Federal Register; these notices are outside the current meeting collection.',
        'evidence': [{'url': 'https://www.govinfo.gov/content/pkg/FR-1999-01-13/pdf/FR-1999-01-13.pdf',
                      'description': 'Page 2237 contains the National Bipartisan Commission on the Future of Medicare public meeting notice for January 26, 1999.'}],
    },
    {
        'code': 'scnc00', 'first_congress': 99,
        'values': {'committee_type': 'commission_or_caucus', 'website': 'https://www.drugcaucus.senate.gov/'},
        'explanation': 'Commission or Caucus describes its organizational form. The Senate Drug Caucus also has standing-committee status; the original source classification is retained.',
        'evidence': [{'url': 'https://www.drugcaucus.senate.gov/about/',
                      'description': 'The official history describes its creation as a commission in 1985, subsequent caucus name, and standing-committee status.'}],
    },
    {
        'code': 'slia00', 'first_congress': 103,
        'values': {'committee_type': 'other', 'website': 'https://www.indian.senate.gov/'},
        'explanation': 'Indian Affairs became permanent in 1984 and changed its name in 1993. Permanent status alone does not establish a Standing classification.',
        'evidence': [{'url': 'https://www.indian.senate.gov/about/',
                      'description': 'The committee history distinguishes its original select status, permanent status, and name change.'}],
    },
    {
        'code': 'hshf00', 'first_congress': 1, 'add_congresses': [119],
        'values': {'committee_type': 'other', 'name': 'Committee of the Whole House on the State of the Union',
                   'website': 'https://live.house.gov/'},
        'explanation': 'The House conducts floor business in committee form. Floor proceedings are outside this committee-meeting collection.',
        'evidence': [{'url': 'https://history.house.gov/Records-and-Research/Committees-Bibliography/Committee-History/',
                      'description': 'The House explains the full name and floor-business role of the Committee of the Whole.'},
                     {'url': 'https://live.house.gov/?date=2026-01-14',
                      'description': 'The 119th Congress floor record reports the House rising from the Committee of the Whole to report H.R. 7006.'}],
    },
    {
        'code': 'jocp00', 'first_congress': 110, 'last_congress': 112,
        'values': {'committee_type': 'other', 'website': 'https://www.senate.gov/general/common/generic/COP_redirect.htm'},
        'terminated': '2011-04-03',
        'explanation': 'Terminated April 3, 2011; historical records remain available. The Senate print series does not change the panel\'s joint identity.',
        'evidence': [{'url': 'https://home.treasury.gov/news/press-releases/tg1091',
                      'description': 'Treasury testimony dated March 4, 2011 identifies the final hearing and states that the panel ends April 3, 2011.'},
                     {'url': 'https://www.senate.gov/general/common/generic/COP_redirect.htm',
                      'description': 'The Senate provides a gateway to the former panel\'s archive.'}],
    },
    {
        'code': 'sowg00', 'first_congress': 106, 'add_congresses': [119],
        'values': {'committee_type': 'other', 'name': 'Senate National Security Working Group'},
        'explanation': 'Official records establish continuing authority in the 119th Congress. Public meeting coverage is not established by the committee lists.',
        'evidence': [{'url': 'https://www.govinfo.gov/content/pkg/CRPT-119srpt38/html/CRPT-119srpt38.htm',
                      'description': 'Senate Report 119-38 provides funding for the working group and states that it operates without future expiration of authority.'}],
    },
)
