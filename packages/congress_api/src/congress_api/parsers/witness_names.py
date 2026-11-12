"""Names and affiliations in GPO witness lines and committee pages.

Read civil, clerical and military titles, suffixes and credentials, including
surname-first GPO lines. Return plain fields for the inventory and transcriber;
contents headings and offices are not names. No transcription dependency.
"""

from __future__ import annotations

import re

## Military ranks, full ("Lieutenant General", "Rear Admiral Upper Half", "Master Chief Petty Officer")
## or abbreviated ("Lt. Gen.", "Tech. Sgt.", "LTG", "CAPT"), kept in their own `rank` field per
## owner decision 2026-11-10 (ct-wy4c / ct-17op). Civil titles ("Mr.", "The Honorable", "Chief") stay out.
MILITARY_RANK_PHRASE = (
    r"(?:Sergeant Major of the (?:Army|Marine Corps)"
    r"|Master Chief Petty Officer of the Navy"
    r"|Chief Master Sergeant of the (?:Air|Space) Force"
    r"|(?:Command |First )?Sergeant Major|(?:Chief |Senior )?Master Sergeant"
    r"|(?:Master |Senior )?Chief Petty Officer|Senior Chief|Petty Officer(?: (?:First|Second|Third) Class)?"
    r"|Chief Warrant Officer(?: [2-5]| (?:Two|Three|Four|Five))?|Warrant Officer(?: 1)?"
    r"|Rear Admiral(?: \(?(?:Upper|Lower) Half\)?)?|Vice Admiral"
    r"|(?:Lieutenant|Major|Brigadier) General|Lieutenant (?:Colonel|Commander|Junior Grade)"
    r"|(?:First|Second) Lieutenant|(?:Gunnery|Technical|Staff|First) Sergeant|Sergeant First Class"
    r"|Lance Corporal|Private First Class|Senior Airman|Airman First Class"
    r"|(?:Rear|Vice) (?:Adm\.?|Admiral)|(?:Lt|Maj|Brig)\.? (?:Gen\.?|General)|Lt\.? (?:Col\.?|Colonel|Cmdr\.?|Commander)|(?:1st|2nd) (?:Lt\.?|Lieutenant)"
    r"|(?:(?:Command )?Sgt\.? Maj|Master Sgt|Tech\.? Sgt|Staff Sgt|1st Sgt)\.?|CWO-?[2-5]|CW[2-5]"
    r"|General|Gen\.|GEN|LTG|MG|BG|LtGen|LTGEN|MajGen|MAJGEN|BrigGen|BRIGGEN|BGen|BGEN"
    r"|Admiral|Adm\.|ADM|VADM|RADM|RDML"
    r"|Colonel|Col\.|COL|LTC|LtCol|LTCOL"
    r"|Commander|Cmdr\.|CDR|LCDR"
    r"|Major|Maj\.|MAJ"
    r"|Captain|Capt\.|CAPT|CPT"
    r"|Lieutenant|Lt\.|LT|1LT|2LT|LTJG|Ensign|ENS"
    r"|Sergeant|Sgt\.|SGT|SMA|SMMC|CMSAF|MCPON|CSM|SGM|SgtMaj|SGTMAJ|MSG|MSgt|MSGT|GySgt|GYSGT|TSgt|TSGT|SSG|SSgt|SSGT|SFC|1SG|CMSgt|CMSGT|SMSgt|SMSGT"
    r"|MCPO|SCPO|CPO"
    r"|Corporal|Cpl\.|CPL|LCpl|LCPL|Specialist|Spc\.|SPC|Seaman|Private|Pvt\.|PFC|SrA|SRA)"
)

MILITARY_RANK = re.compile(r"^(" + MILITARY_RANK_PHRASE + r")(?:\s+|(?<=\.)(?=[A-Z]))")

## a title before a name: civil ("Mr.", "The Honorable", "the Honorable", "Ambassador"), clerical, civic, or a
## military rank phrase ("Lieutenant General", "Master Chief Petty Officer", "Lt. Gen.", "Tech. Sgt.", "LTG"),
## with "(Ret.)" after it; GPO occasionally drops the space after a period ("The Hon.Cedric Richmond", ct-uz8q).
## Rank modifier words ("Senior", "Petty", "Warrant", "Upper", "Lower", "Half") match only inside MILITARY_RANK_PHRASE,
## never standalone on organization names ("Senior Executives Association").
_CIVIL_OR_CIVIC_TITLE = (
    "(?:"
    + "|".join(
        """Hon Honorable Honorables Mr Ms Mrs Mx Dr Prof Professor Rev Reverend Pastor Rabbi Sister Sir Senator Sen Representative Rep Ambassador Amb
    Governor Gov Mayor President Officer Detective Sheriff Chief""".split()
    )
    + r")\.?"
)
TITLE_PART = r"(?:" + MILITARY_RANK_PHRASE + r"|" + _CIVIL_OR_CIVIC_TITLE + r")"

_PREFIX_BRANCH_RET = (
    r"(?: (?:USA|USN|USAF|USMC|USCG|USSF|USPHS|USAR|USNR|USAFR|USMCR|USCGR))?"
    r"(?: [(\[](?:(?:USA|USN|USAF|USMC|USCG|USSF|USPHS|USAR|USNR|USAFR|USMCR|USCGR),? )?(?:Dr|[Rr]et(?:ired)?|RET)\.?[)\]])?"
)

TITLE = re.compile(
    r"^(?:[Tt]he )?(" + TITLE_PART + ")(?: " + TITLE_PART + r")*" + _PREFIX_BRANCH_RET + r"(?: +|(?<=\.)(?=[A-Z]))"
)

CIVIL_PREFIX = re.compile(
    r"^(?:[Tt]he )?(?:Hon\.?|Honorables?|Mr\.?|Ms\.?|Mrs\.?|Miss|Mx\.?|Dr\.?|Prof\.?|Professor|Rev\.?|Reverend"
    r"|Pastor|Rabbi|Sister|Sir|Senator|Sen\.?|Representative|Rep\.?|Ambassador|Amb\.?|Governor|Gov\.?"
    r"|Mayor)(?: +|(?<=\.)(?=[A-Z]))"
)
_CIVIL_PREFIX_CI = re.compile(CIVIL_PREFIX.pattern, re.I)

SUFFIX = re.compile(r"^(Jr|Sr|II|III|IV)\.?$")

PARTICLE_SURNAME = re.compile(r"^(?:(?:van|von|de|den|del|der|della|di|da|du|la|le|ten|ter) )+[A-Z][\w'’-]*$")

## Degrees and licensures that may stand before the given name in surname-first GPO lines ("Woodruff, Ph.D., MPH, Tracey",
## "Lotzar, M.S.W., Eliyahu", "Claussen, CPA, Doug"); two-letter given-name initials ("J.H.", "T.J.") stay out.
DEGREE = re.compile(
    r"^(?:(?:Ph|PH|[Ee][Dd]|[Pp]sy|PSY|[Pp]harm|PHARM|[Ss][Cc])\.? ?D|[Dd][Rr]\.? ?P\.? ?H|D\.?P\.?H|D\.?D\.?S|D\.?M\.?D|D\.?V\.?M|V\.?M\.?D"
    r"|D\.?O|O\.?D|D\.?P\.?M|D\.?N\.?P|D\.?P\.?A|D\.?B\.?A|D\.?H\.?A|M\.?D|J\.?D|LL\.?[BM]|Esq"
    r"|M\.?P\.?H|M\.?S\.?P\.?H|M\.?H\.?S|M\.?H\.?A|M\.?B\.?A|M\.?P\.?A|M\.?P\.?P|M\.?S\.?W|M\.?S\.?N"
    r"|C\.?P\.?A|R\.?N)\.?$"
)

## Explicit academic degrees, professional licensure/fellowships, religious orders, and military service/retirement
## post-nominals ("Ph.D.", "M.D.", "MPH", "MHS", "DFAPA", "USAF", "USN (Ret.)", "(USA, Ret.)", "(Ret.)").
## Never arbitrary 2-6 uppercase letters, which caught corporate titles ("CEO"), suffixes ("III"), places ("CA",
## "D.C."), and organization acronyms ("NASA", "AARP", "AMVETS") (ct-6mvl, ct-17op).
_BRANCH_ABBR = r"(?:USA|U\.S\.A\.|USN|U\.S\.N\.|USAF|U\.S\.A\.F\.|USMC|U\.S\.M\.C\.|USCG|U\.S\.C\.G\.|USSF|U\.S\.S\.F\.|USPHS|U\.S\.P\.H\.S\.|USAR|USNR|USAFR|USMCR|USCGR|ARNG|USARNG|ANG)"
_BRANCH_FULL = r"(?:U\.S\.|US|United States)\s+(?:Army|Navy|Air Force|Marine Corps|Coast Guard|Space Force|Public Health Service)(?: Reserve)?"
_RET_SUFFIX = r"[(\[]?(?:[Rr]et(?:ired)?\.?|RET)[)\]]?"

_SINGLE_CREDENTIAL = (
    r"(?:"
    r"(?:Ph|PH|[Ee][Dd]|[Pp]sy|PSY|[Pp]harm|PHARM|[Ss][Cc])\.? ?D\.?|D\.?Phil\.?|D\.?Sc\.?|[Dd][Rr]\.? ?P\.? ?H\.?|D\.?P\.?H\.?|Dr\.?\s*sc\.?\s*h\.?\s*c\.?"
    r"|M\.?D\.?|M\.?B\.?B\.?S\.?|D\.?O\.?|J\.?D\.?|LL\.?[BM]\.?|S\.?J\.?D\.?|Esq\.?"
    r"|D\.?D\.?S\.?|D\.?M\.?D\.?|D\.?V\.?M\.?|V\.?M\.?D\.?|O\.?D\.?|D\.?P\.?M\.?"
    r"|D\.?N\.?P\.?|D\.?N\.?S\.?|D\.?S\.?W\.?|D\.?P\.?A\.?|D\.?B\.?A\.?|D\.?H\.?A\.?|Th\.?D\.?|D\.?Min\.?"
    r"|M\.?P\.?H\.?|M\.?S\.?P\.?H\.?|M\.?S\.?H\.?A\.?|M\.?H\.?S\.?|M\.?H\.?A\.?|M\.?B\.?A\.?|M\.?P\.?A\.?|M\.?P\.?P\.?|E\.?M\.?H\.?L\.?"
    r"|M\.?S\.?W\.?|M\.?S\.?N\.?|M\.?Ed\.?|M\.?Div\.?|M\.?A\.?C\.?C\.?|M\.?S\.?C\.?I\.?|M\.?S\.?C\.?|M\.?O\.?H\.?|M\.?B\.?I\.?|M\.?T\.?M\.?&H\.?|[Mm]\.?[Ss]c\.?|M\.?A\.?|M\.?S\.?|M\.?M\.?"
    r"|B\.?S\.?N\.?|B\.?S\.?C\.?P\.?|B\.?A\.?|B\.?S\.?|B\.?E\.?"
    r"|R\.?N\.?|R\.?N\.?P\.?|A\.?P\.?R\.?N\.?|C\.?R\.?N\.?P\.?|C\.?R\.?N\.?A\.?|F\.?N\.?P\.?(?:-B\.?C\.?)?|N\.?P\.?|P\.?A\.?-C\.?|L\.?P\.?N\.?"
    r"|[A-Z.]{2,8}-B\.?C\.?|N\.?C\.?S\.?N\.?|C\.?H\.?P\.?N\.?"
    r"|L\.?C\.?S\.?W\.?|L\.?I\.?C\.?S\.?W\.?|L\.?I\.?S\.?W\.?(?:-S)?|L\.?M\.?S\.?W\.?|L\.?S\.?W\.?|L\.?P\.?C\.?|L\.?M\.?F\.?T\.?|R\.?D\.?N\.?|R\.?D\.?|L\.?D\.?|R\.?Ph\.?|RPH"
    r"|C\.?P\.?A\.?|C\.?G\.?M\.?A\.?|C\.?F\.?A\.?|C\.?F\.?P\.?|P\.?E\.?|P\.?G\.?|C\.?E\.?G\.?|C\.?H\.?G\.?|D\.?E\.?E\.?|A\.?I\.?A\.?|F\.?A\.?I\.?A\.?|A\.?A\.?E\.?|C\.?A\.?E\.?"
    r"|B\.?C\.?S\.?C\.?P\.?|B\.?C\.?A\.?C\.?P\.?|C\.?G\.?P\.?|B\.?C\.?D\.?|C\.?V\.?A\.?|C\.?A\.?A\.?D\.?C\.?|C\.?P\.?H\.?Q\.?|C\.?P\.?E\.?|C\.?R\.?C\.?|C\.?E\.?D\.?S\.?|C\.?P\.?S\.?T\.?(?:-[A-Z])?"
    r"|A\.?B\.?I\.?M\.?|A\.?B\.?P\.?P\.?|D\.?A\.?C\.?V\.?P\.?M\.?|D\.?A\.?C\.?P\.?V\.?|M\.?I\.?S\.?A\.?(?:\s+II)?"
    r"|C\.?M\.?B\.?|C\.?P\.?C\.?U\.?|F\.?S\.?A\.?|M\.?A\.?I\.?|S\.?R\.?A\.?|P\.?M\.?P\.?|C\.?I\.?S\.?S\.?P\.?"
    r"|C\.?F\.?M\.?|C\.?E\.?M\.?|C\.?S\.?P\.?|E\.?F\.?O\.?|A\.?P\.?R\.?|A\.?C\.?V\.?S\.?O\.?|S\.?H\.?C\.?E\.?|[MF]\.?A\.?S\.?C\.?E\.?"
    r"|F\.?A\.?[A-Z.]{2,8}|F\.?A\.?[Ee]d\.?|F\.?A\.?C\.?[A-Z]{1,4}\.?|F\.?C\.?A\.?P\.?|F\.?C\.?P\.?|F\.?S\.?B\.?I\.?|F\.?S\.?A\.?H\.?M\.?|F\.?R\.?C\.?P\.?|F\.?F\.?S\.?M\.?B\.?|F\.?I\.?D\.?S\.?A\.?|F\.?I\.?C\.?D\.?|F\.?iaedp|D\.?F\.?A\.?P\.?A\.?|F\.?A\.?P\.?A\.?"
    r"|M\.?A\.?C\.?P\.?|M\.?A\.?C\.?O\.?I\.?"
    r"|D\.?A\.?B\.?V\.?P\.?(?:\([A-Z]+\))?"
    r"|O\.?P\.?|S\.?J\.?|O\.?F\.?M\.?|R\.?S\.?M\.?|C\.?S\.?C\.?"
    r"|" + _BRANCH_ABBR + r"(?:,?\s*" + _RET_SUFFIX + r")?"
    + r"|" + _BRANCH_FULL + r"(?:,?\s*" + _RET_SUFFIX + r")?"
    + r"|[(\[](?:(?:" + _BRANCH_ABBR + r"|" + _BRANCH_FULL + r"),?\s+)?(?:[Rr]et(?:ired)?\.?|RET)[)\]]"
    + r"|[(\[](?:[Rr]et(?:ired)?\.?|RET),?\s+(?:" + _BRANCH_ABBR + r"|" + _BRANCH_FULL + r")[)\]]"
    + r"|[(\[]" + _BRANCH_ABBR + r"[)\]]\s*,?\s*(?:[Rr]et(?:ired)?\.?|RET)"
    + r")"
)

CREDENTIAL = re.compile(r"^" + _SINGLE_CREDENTIAL + r"(?:(?:\s+|,\s*)" + _SINGLE_CREDENTIAL + r")*\.?$")

_RET_PAREN_INLINE = re.compile(
    r"[(\[](?:(?:" + _BRANCH_ABBR + r"|" + _BRANCH_FULL + r"),?\s+)?(?:[Rr]et(?:ired)?\.?|RET)[)\]]"
    r"|[(\[](?:[Rr]et(?:ired)?\.?|RET),?\s+(?:" + _BRANCH_ABBR + r"|" + _BRANCH_FULL + r")[)\]]"
    r"|[(\[]" + _BRANCH_ABBR + r"[)\]]\s*,?\s*(?:[Rr]et(?:ired)?\.?|RET)"
)

_TRAILING_RET_PAREN = re.compile(
    r"\s*(" + _RET_PAREN_INLINE.pattern + r")$"
)

CONNECTIVE = {"and", "of", "for", "the", "to", "in", "on", "from", "by", "with", "at"}

## a post rather than a person ("State Director"), a name GPO ran together with the post ("Byrum, John Executive
##  Director"), or a document listed among the witnesses ("Printed Hearing Record") holds a noun of office or of paper
NOT_A_NAME = {
    "director", "manager", "officer", "president", "secretary", "administrator", "commissioner", "commissioners",
    "chairman", "chairwoman", "counsel", "attorney", "founder", "owner", "executive", "specialist", "professional",
    "coordinator", "advocate", "advocacy", "superintendent", "treasurer", "record", "testimony", "statement",
    "hearing", "panel", "witnesses",
}

## Single-segment affiliation classification (ct-6mvl): when only one comma-separated segment follows the name,
## an organization ("U.S. Small Business Administration", "U.S. Senate", "National Mining Association") belongs in
## `organization` with empty `position`; a personal role or Member style ("U.S. Senator from the State of Delaware",
## "Private Landowner", "Director of National Intelligence") stays in `position`.
_ORG_PREFIX = re.compile(
    r"^(?:The\s+)?(?:U\.?S\.?\s+|United States\s+)?(?:(?:Department|Office|Bureau|Agency|Board|Commission|Committee"
    r"|Subcommittee|Court|House)\s+of\b|Senate\b|House of Representatives\b)"
)
_ORG_NOUN = re.compile(
    r"\b(?:Departments?|Offices?|Administrations?|Agenc(?:y|ies)|Bureaus?|Services?|Commissions?|Associations?"
    r"|Institutes?|Institutions?|Foundations?|Federations?|Unions?|Leagues?|Societ(?:y|ies)|Coalitions?"
    r"|Committees?|Subcommittees?|Councils?|Boards?|Chambers?|Centers?|Clinics?|Hospitals?|Universit(?:y|ies)"
    r"|Colleges?|Schools?|Academ(?:y|ies)|Laborator(?:y|ies)|Labs?|Museums?|Librar(?:y|ies)|Corporations?|Corp\b"
    r"|Compan(?:y|ies)|Co\b|Inc\b|L\.?L\.?C\b|L\.?L\.?P\b|Ltd\b|Groups?|Partnerships?|Banks?|Bancorp|Lending"
    r"|Technologies|Systems|Solutions|Industries|Enterprises|Airlines|Railroads?|Railways?|Communications"
    r"|Networks?|Alliances?|Funds?|Trusts?|Projects?|Programs?|Initiatives?|Authorit(?:y|ies)|Conferences?"
    r"|Commands?|Task Force|Air Force|Space Force|Armed Forces|Marine Corps|Coast Guard|National Guard"
    r"|U\.?S\.?\s+(?:Army|Navy|Senate)|United States\s+(?:Army|Navy|Senate)|Senate|House of Representatives"
    r"|Courts?|Tribes?|Pueblos?|Ministries|Ministry|Embass(?:y|ies)|Church(?:es)?|Archdioceses?|Dioceses?"
    r"|Charities|Clubs?|Legion|Veterans of|Disabled American Veterans|Paralyzed Veterans"
    r"|AMVETS|AARP|AFL-CIO|NAACP|ACLU|NFIB|NASA|NOAA|EPA|FDA|FCC|FTC|GAO|CBO|OMB|FEMA|TSA|CDC|NIH|SAMHSA|OSHA"
    r"|NLRB|EEOC|FERC|CFTC|FDIC|CFPB)\b"
)
_PERSONAL_ROLE = re.compile(
    r"\b(?:Directors?|Managers?|Officers?|Presidents?|Vice[- ]Presidents?|Secretar(?:y|ies)|Undersecretar(?:y|ies)"
    r"|Administrators?|Commissioners?|Chair(?:man|woman|person|s)?|Co-Chairs?|Ranking Member|Counsel|Attorney"
    r"|Lawyer|Founders?|Co-Founders?|Owner(?!-Operator\b)|Co-Owner|Executive|CEO|C\.E\.O\.|CFO|COO|CIO|CTO|EVP|SVP"
    r"|Specialists?|Coordinators?|Advocate|Superintendents?|Treasurers?|Comptrollers?|Auditors?|Inspectors?"
    r"|(?!General (?:Services|Motors|Electric|Dynamics|Foods|Mills)\b)Generals?|Admirals?|Colonels?|Commanders?|Majors?|Captains?|Lieutenants?|Sergeants?"
    r"|Speakers?|Clerks?|Parliamentarians?|Senators?|Representative|Delegates?|Congress(?:man|woman)|Members?|Ambassadors?|Governors?|Mayors?|Sheriff"
    r"|Judges?|Justices?|Magistrates?|Solicitors?|Prosecutors?|Deans?|Provosts?|Chancellors?|Principals?"
    r"|Professors?|Fellows?|Scholars?|Analysts?|Economists?|Scientist|Researchers?|Historians?|Authors?|Editors?|Astronauts?"
    r"|Journalists?|Correspondents?|Physician|Doctor|Surgeon|Nurse|Pharmacist|Psychologist|Therapist"
    r"|Partners?|Consultants?|Advis[eo]rs?|Lobbyists?|Chiefs?|Heads?|Leads?|Spokes(?:person|man|woman)|Trustees?"
    r"|Nominees?|Candidates?|to be\b|Acting\b|Former\b|Retired\b|Emeritus\b"
    r"|Resident|Citizen|Landowner|Rancher|Farmer|Grower|Miner|Teacher|Student|Parent"
    r"|Mother|Father|Wife|Husband|Widow|Veteran)\b",
    re.I,
)


def _is_organization_only(segment: str) -> bool:
    """True when a lone post-name segment names an organization rather than a personal role or Member style."""
    s = segment.strip()
    if not s:
        return False
    probe = s.title() if s.isupper() else s
    if (_ORG_PREFIX.search(s) or _ORG_PREFIX.search(probe)) and not re.match(
        r"^(?:a |the |former |acting )?(?:U\.?S\.? |United States )?(?:Senator|Representative|Delegate|Member)\b",
        s,
        re.I,
    ):
        return True
    return bool(_ORG_NOUN.search(s) or _ORG_NOUN.search(probe)) and not bool(
        _PERSONAL_ROLE.search(s) or _PERSONAL_ROLE.search(probe)
    )


def is_name(text: str) -> bool:
    """Could this be a person's name? GPO's witness lines include contents lines ("Answers to questions from
    the following ...") and the broken-off end of a position ("Security Officer and Security Services
    Administrator"); neither is two to six capitalised words without a connective, a noun of office or paper, or a digit."""
    words = [w.strip(",.-/").lower() for w in text.split()]
    return (
        2 <= len(words) <= 6
        and text[:1].isupper()
        and not any(c.isdigit() for c in text)
        and not (CONNECTIVE | NOT_A_NAME) & set(words)
    )


## GPO's footnote marker, "\1\" or "\*\", set after the item it annotates (a contents label, a name, a position)
FOOTNOTE = re.compile(r"\s*\\(?:\d+|\*)\\")

## a contents label GPO sets before a witness's name ("Prepared statement", "Submitted questions:", "Additional
##  information from", "Response to question submitted for the record by"), ended by its footnote marker, a dot leader
##  and page, or nothing at all; a page can carry GPO's character-entity residue ("60<greek-l>", "00 deg.")
ANSWER_WORDS = (
    r"(?:answers? to (?:submitted |additional )?questions|submitted questions"
    r"|responses? to (?:(?:submitted |additional |written )?questions|question submitted for the record))"
)
LABEL_WORDS = (
    r"(?:(?:supplement to |joint )?(?:opening |prepared |written )?statements?(?: and attachments)?(?: \d+)?(?: of)?"
    r"|" + ANSWER_WORDS
    + r"|additional (?:information|materials?)(?: supplied)?(?: (?:submitted )?for the record)?)"
)
LABEL_END = r"(?:\s*\\(?:\d+|\*)\\)*(?:\s*\.{3,}\s*(?:[\d\-]+\S*(?: deg\.)?)?)?"
CONTENTS_LABEL = re.compile(
    r"^\s*" + LABEL_WORDS + r":?(?:(?:\s*\\(?:\d+|\*)\\)+" + LABEL_END + r"|\s*\.{3,}\s*(?:[\d\-]+\S*(?: deg\.)?)?)\s*",
    re.I,
)
## the same label with no marker, before a name: "Prepared statement Erik D. Olson", "Submitted questions: Avalos, ...",
## "Answers to Submitted Questions, Mr. Jeff Hopkins", "Response to question submitted for the record by Jeanine Derby"
UNMARKED_LABEL = re.compile(
    r"^\s*(?:" + ANSWER_WORDS + LABEL_END + r",|" + LABEL_WORDS + LABEL_END + r"(?::|\s+(?:from|with|by))?)\s+(?=[A-Z])",
    re.I,
)
## a name that is still a contents label once read: the line names an entry, not a person
LABEL_NAME = re.compile(r"^\W*" + LABEL_WORDS + r"\b", re.I)

## GPO's footnote text, which runs on into the next witness's line ("... is available at http://...pdf. \2\ Mr. Peress
##  did not answer ... by the time of publication. David Mallino, ..."): a line holding it names, at most, whoever
##  follows its last sentence; one holding nothing after it names no one
FOOTNOTE_TEXT = re.compile(
    r"(?:has|have|are|is) been retained in|retained in the files|(?:is|are) available (?:at|as part)"
    r"|by the time of (?:publication|printing)|^\W*time of (?:publication|printing)",
    re.I,
)
FOOTNOTE_END = re.compile(
    r"(?:\.pdf|EventID=\d+|time of (?:publication|printing))\.\s+|retained in the files of the Committee\s+",
    re.I,
)

## a dot leader and the page list after it ("........ 62-75 ", "..... 102-115, 115-123 ", "....... 39,40 ")
LEADER = re.compile(r"\s*\.{4,}\s*(?:\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*,?)?\s*")
## the items a leader can end: a contents label or entry, never a witness's position
ENTRY_WORDS = re.compile(
    r"^\W*(?:" + LABEL_WORDS + r"|insert for the record|letters?\b|response|charts?\b|slides?\b|articles?\b)",
    re.I,
)


def split_leaders(text: str) -> str:
    """GPO's dot leader separates two items on one line: a name from its position ("Kay E. Brown...... Director,
    ..."), a witness's line from its contents entry ("..., Department of Energy...... Insert for the record"), or a
    contents entry and its pages from the next witness's line ("Slides...... 62-75 Hines, William H., ..."). Keep
    the witness: the first item when it is a name, else the last item written as a witness line (a name and a
    position, so a bare Member's name between two entries is not one); a line of entries keeps its first."""
    items = [item.strip(" ,") for item in LEADER.split(text) if item.strip(" ,")]
    if len(items) <= 1:
        return items[0] if items else ""
    if not ENTRY_WORDS.match(items[0]) and is_name(_name_of(items[0])):
        return ", ".join([items[0], *(item for item in items[1:] if not ENTRY_WORDS.match(item))])
    people = [item for item in items[1:] if "," in item and not ENTRY_WORDS.match(item) and is_name(_name_of(item))]
    return people[-1] if people else items[0]


def drop_footnote_text(text: str) -> str:
    """The line after GPO's footnote text, or "" when footnote text runs to its end."""
    if not FOOTNOTE_TEXT.search(text):
        return text
    ends = list(FOOTNOTE_END.finditer(text))
    rest = text[ends[-1].end() :] if ends else ""
    return "" if FOOTNOTE_TEXT.search(rest) else rest


def strip_contents_markers(text: str) -> str:
    """A GPO line without footnote text, contents labels and footnote markers: "Prepared statement \\1\\ Answers to
    submitted questions\\2\\ John Bozzella, ..." is John Bozzella's line. A label with no marker is dropped only
    when a name follows it, so "Prepared statement on H.R. 841" stays as GPO wrote it."""
    text = drop_footnote_text(text)
    while label := CONTENTS_LABEL.match(text):
        text = text[label.end() :]
    if (label := UNMARKED_LABEL.match(text)) and is_name(_name_of(text[label.end() :])):
        text = text[label.end() :]
    return split_leaders(FOOTNOTE.sub("", text)).strip()


def _name_of(text: str) -> str:
    return witness(text)["name"]


_TOP_COMMA = re.compile(r",(?![^(\[]*[)\]])")
_PAREN_RANK_BRANCH = re.compile(
    r"\s*\(\s*(" + MILITARY_RANK_PHRASE + r")\s*,\s*(" + _BRANCH_ABBR + r"(?:\s*,\s*(?:[Rr]et(?:ired)?\.?|RET))?)\s*\)$"
)
_MID_NAME_DEGREE_ROLE = re.compile(
    r"^(\S+(?:\s+\S+)+?)\s+((?:(?:Ph|PH|[Ee][Dd]|[Pp]sy|PSY|[Pp]harm|PHARM|[Ss][Cc])\.? ?D|M\.?D|J\.?D|D\.?O|D\.?V\.?M|D\.?D\.?S)\.?|"
    + _RET_PAREN_INLINE.pattern
    + r")\s+"
    r"(?!(?:[Cc]andidate|[Ss]tudent)\b)([A-Za-z(\[][\w'’&()\[\]-]*(?:\s+[\w'’&.,()\[\]-]+)*)$"
)


def _split_witness_commas(text: str) -> list[str]:
    """Split on commas while keeping commas inside military retirement parentheticals (`(USA, Ret.)`) intact."""
    protected: list[str] = []

    def _stash(m: re.Match[str]) -> str:
        protected.append(m.group(0))
        return f"\x00RET{len(protected) - 1}\x00"

    masked = _RET_PAREN_INLINE.sub(_stash, text)
    out: list[str] = []
    for seg in masked.split(","):
        s = seg.strip()
        if not s:
            continue
        for idx, val in enumerate(protected):
            s = s.replace(f"\x00RET{idx}\x00", val)
        out.append(s)
    return out


def _is_mid_degree_role_tail(tail: str) -> bool:
    """True when text after a space-separated mid-line degree is a role/affiliation rather than a surname or credential."""
    t = tail.strip()
    if not t or CREDENTIAL.match(t):
        return False
    return bool(
        _PERSONAL_ROLE.search(t)
        or _ORG_NOUN.search(t)
        or re.search(r"\b(?:Witness|Economics|Policy|Law|Medicine)\b", t, re.I)
    )
_LEADING_SEG_CREDENTIAL = re.compile(
    r"^(" + _SINGLE_CREDENTIAL + r"(?:(?:\s+|,\s*)" + _SINGLE_CREDENTIAL + r")*)\.*"
    r"(?:\s+(?!(?:[Cc]andidate|[Ss]tudent)\b)(?=[A-Za-z(\[])|;\s*|(?<=[)\]])\s*/\s*(?=[A-Za-z]))"
)


def peel_leading_position_credentials(
    position: str | None, credentials: str | None = None
) -> tuple[str | None, str | None]:
    """Peel leading degree or service-branch qualifiers from `position` into `credentials` (`ct-17op` P0-3c).

    Handles standalone credential positions (`"USAF (Ret.)"`, `"MD, MPH, FAAP"`) and comma-delimited
    prefixes (`"Ph.D., Adjunct Fellow"`, `"USMC, Chairman"`, `"USAF, Retired, of Hawaii, to be ..."`),
    without touching prose roles (`"USA Hockey"`, `"U.S. Army Veteran"`, `"Ph.D. in Accounting..."`,
    `"Ph.D Candidate"`, `"CPA and Small Business Owner"`).
    """
    pos = re.sub(r"\s+", " ", (position or "").strip())
    existing = [c.strip() for c in (credentials or "").split(",") if c.strip()]
    if not pos:
        return (None, ", ".join(existing) if existing else None)

    peeled: list[str] = []
    if CREDENTIAL.match(pos) and not re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, pos):
        peeled.append(pos)
        pos = ""
    else:
        segs = _split_witness_commas(pos)
        while len(segs) >= 2:
            if (
                len(segs) >= 3
                and re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, segs[0])
                and re.fullmatch(r"[Rr]et(?:ired)?\.?|RET", segs[1])
            ):
                peeled.append(f"{segs[0]}, {segs[1]}")
                segs = segs[2:]
                continue
            if CREDENTIAL.match(segs[0]):
                peeled.append(segs.pop(0))
                continue
            break
        if peeled and segs:
            if lead_m := _LEADING_SEG_CREDENTIAL.match(segs[0]):
                tok = lead_m.group(1).strip()
                rem = segs[0][lead_m.end() :].strip()
                if rem and not re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, tok):
                    peeled.append(tok)
                    segs[0] = rem
        if peeled:
            pos = ", ".join(segs)

    merged: list[str] = list(existing)
    seen_norm = {m.replace(".", "").lower() for m in merged}
    for item in peeled:
        norm = item.replace(".", "").lower()
        if item and norm not in seen_norm:
            merged.append(item)
            seen_norm.add(norm)
    return (pos or None, ", ".join(merged) if merged else None)


def _extract_rank_from_prefix(prefix: str, remainder: str, *, min_name_words: int) -> tuple[str, str]:
    """Extract a military rank and any attached `(Ret.)` from a matched title prefix when `remainder` names a person."""
    p = re.sub(r"\s+", " ", prefix.strip())
    ret_cred = ""
    if ret_m := re.search(
        r"\s*((?:" + _BRANCH_ABBR + r"\s+)?[(\[](?:(?:" + _BRANCH_ABBR + r"),?\s+)?(?:[Rr]et(?:ired)?\.?|RET)[)\]])$",
        p,
    ):
        ret_cred = ret_m.group(1).strip()
        p = p[: ret_m.start()].strip()
    if dr_m := re.search(r"\s*[(\[]Dr\.?[)\]]$", p, re.I):
        p = p[: dr_m.start()].strip()
    # Strip leading civil courtesy ("The Honorable Lieutenant General ...") before checking for a military rank.
    while cm := CIVIL_PREFIX.match(p + " "):
        p = (p + " ")[cm.end() :].strip()
    if not p:
        return "", ret_cred
    if re.fullmatch(MILITARY_RANK_PHRASE, p):
        parts = [s.strip() for s in _TOP_COMMA.split(remainder) if s.strip()]
        first_seg = parts[0] if parts else ""
        first_seg_clean = re.sub(r"\s*[(\[][^)\]]*[)\]]?$", "", first_seg).strip()
        ambiguous = p in ("General", "Major", "Captain", "Commander")
        needed = min_name_words if ambiguous else 1
        if (len(first_seg_clean.split()) >= needed or (len(parts) >= 2 and len(first_seg_clean.split()) == 1)) and not (
            p in ("General", "Major") and _ORG_NOUN.search(first_seg_clean)
        ):
            return p, ret_cred
    return "", ret_cred


def _pop_trailing_credentials_from_words(words: list[str], *, min_words: int) -> list[str]:
    """Pop trailing credential tokens (e.g. 'MD MS', 'USAF', 'USA') from a word list, preserving printed order."""
    popped: list[str] = []
    while len(words) > min_words and CREDENTIAL.match(words[-1]) and not SUFFIX.match(words[-1]):
        popped.append(words.pop())
    popped.reverse()
    return popped


def split_rank_and_credentials(
    name: str | None,
    *,
    honorific: str | None = None,
    given: str | None = None,
    family: str | None = None,
    suffix: str | None = None,
    retired: str | None = None,
    strip_civil_from_name: bool = False,
) -> dict[str, str | None]:
    """Extract `rank` and `credentials` verbatim for structured or flat publishers (`house_xml`, `congress_gov`).

    Preserves civil honorifics (`Mr.`, `Dr.`, `The Honorable`) as the publisher writes them unless
    `strip_civil_from_name` is requested, while moving military ranks out of `name`/`honorific`/`given` into `rank`
    and degrees/service-branch/retirement post-nominals out of `name`/`family`/`suffix`/`retired` into `credentials`.
    """
    rank_val: str | None = None
    cred_parts: list[str] = []

    hon = re.sub(r"\s+", " ", (honorific or "").strip()) or None
    giv = re.sub(r"\s+", " ", (given or "").strip()) or None
    fam = re.sub(r"\s+", " ", (family or "").strip()) or None
    suf = re.sub(r"\s+", " ", (suffix or "").strip()) or None
    ret = re.sub(r"\s+", " ", (retired or "").strip()) or None
    nm = re.sub(r"\s+", " ", (name or "").strip()) or None

    # 1. Structured `honorific` / `given` (house_xml)
    giv_creds: list[str] = []
    if hon:
        cand = hon
        while cm := _CIVIL_PREFIX_CI.match(cand + " "):
            cand = (cand + " ")[cm.end() :].strip()
        if cand and re.fullmatch(MILITARY_RANK_PHRASE, cand):
            rank_val = cand
            if nm and nm.startswith(hon + " "):
                nm = nm[len(hon) + 1 :].strip() or None
            elif nm and cand in nm:
                nm = re.sub(r"^" + re.escape(cand) + r"\s+", "", nm).strip() or None
            hon = None
    if giv:
        if rank_val and rank_val in ("Lt.", "Lt", "Maj.", "Maj", "Brig.", "Brig", "Rear", "Vice"):
            if gm := re.match(r"^(General|Gen\.?|Admiral|Adm\.?|Colonel|Col\.?|Commander|Cmdr\.?)\s+(.+)$", giv):
                rank_val = f"{rank_val} {gm.group(1)}"
                after_giv = gm.group(2).strip()
                if nm and nm.startswith(giv):
                    nm = (after_giv + nm[len(giv) :]).strip() or None
                giv = after_giv
        elif not rank_val:
            if rm := MILITARY_RANK.match(giv):
                after_giv = giv[rm.end() :].strip()
                if after_giv:
                    rank_val = rm.group(1).strip()
                    if after_giv.lower().startswith(("(ret.) ", "(retired) ")):
                        ret_tok, after_giv = after_giv.split(" ", 1)
                        giv_creds.append(ret_tok)
                        after_giv = after_giv.strip()
                    if nm and nm.startswith(giv):
                        nm = (after_giv + nm[len(giv) :]).strip() or None
                    giv = after_giv
        if strip_civil_from_name and giv and not rank_val:
            while cm_g := _CIVIL_PREFIX_CI.match(giv):
                after_g = giv[cm_g.end() :].strip()
                if not after_g:
                    break
                if not hon:
                    hon = cm_g.group(0).strip()
                giv = after_g

    # 2. Structured `suffix` / `retired` (house_xml) — run before `family` so `Paxton Jr.` + `<suffix>USMC</suffix>`
    # frees `suf` to receive `Jr.` (`ct-17op` P0-3d).
    suf_creds: list[str] = []
    if suf:
        suf_tokens = [t.strip() for t in _TOP_COMMA.split(suf) if t.strip()]
        if (
            len(suf_tokens) >= 2
            and re.fullmatch(r"[Rr]et(?:ired)?\.?|RET", suf_tokens[-1])
            and re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, suf_tokens[-2])
        ):
            suf_tokens[-2] = f"{suf_tokens[-2]}, {suf_tokens[-1]}"
            suf_tokens.pop()
        kept_suf: list[str] = []
        for tok in suf_tokens:
            if SUFFIX.match(tok):
                kept_suf.append(tok)
            elif CREDENTIAL.match(tok):
                suf_creds.append(tok)
            else:
                kept_suf.append(tok)
        suf = ", ".join(kept_suf) if kept_suf else None
    if ret:
        suf_creds.append(ret)

    # 3. Structured `family` carrying `, Jr., USMC`, `II USAF`, `, Ph.D.`, or `(USA, Ret.)` (house_xml)
    fam_creds: list[str] = []
    if fam:
        fam_ret: str | None = None
        if ret_m := _TRAILING_RET_PAREN.search(fam):
            fam_ret = ret_m.group(1).strip()
            fam = fam[: ret_m.start()].rstrip(" ,")
        fam_segs = [s.strip() for s in _TOP_COMMA.split(fam) if s.strip()]
        if (
            len(fam_segs) >= 3
            and re.fullmatch(r"[Rr]et(?:ired)?\.?|RET", fam_segs[-1])
            and re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, fam_segs[-2])
        ):
            fam_segs[-2] = f"{fam_segs[-2]}, {fam_segs[-1]}"
            fam_segs.pop()
        trailing_segs: list[str] = []
        while len(fam_segs) > 1 and CREDENTIAL.match(fam_segs[-1]):
            trailing_segs.append(fam_segs.pop())
        trailing_segs.reverse()
        fam_space_str: str | None = None
        if fam_segs:
            last_words = fam_segs[-1].split()
            fam_space_creds = _pop_trailing_credentials_from_words(last_words, min_words=1)
            if fam_space_creds:
                fam_space_str = " ".join(fam_space_creds)
                if fam_ret and re.fullmatch(_BRANCH_ABBR, fam_space_creds[-1]):
                    fam_space_str = f"{fam_space_str} {fam_ret}"
                    fam_ret = None
            if len(last_words) > 1 and SUFFIX.match(last_words[-1]) and not suf:
                suf = last_words.pop()
            fam_segs[-1] = " ".join(last_words)
        if len(fam_segs) > 1 and SUFFIX.match(fam_segs[-1]) and not suf:
            suf = fam_segs.pop()
        fam = ", ".join(s for s in fam_segs if s) or None
        fam_creds = [c for c in [*trailing_segs, fam_space_str, fam_ret] if c]

    # 4. Flat or reconstructed `name` (`congress_gov` or `house_xml` full_name)
    flat_creds: list[str] = []
    if nm:
        orig_nm = nm
        rank_changed_nm = False
        civil_changed_nm = False
        if strip_civil_from_name and nm:
            if hon and nm.lower().startswith(hon.lower() + " "):
                after_hon = nm[len(hon) + 1 :].strip()
                if after_hon:
                    nm = after_hon
                    civil_changed_nm = True
            peeled_nm_civil: list[str] = []
            while cm := _CIVIL_PREFIX_CI.match(nm):
                rem = nm[cm.end() :].strip()
                tok = cm.group(0).strip()
                unambig = tok.lower().rstrip(".") in {
                    "mr",
                    "ms",
                    "mrs",
                    "miss",
                    "mx",
                    "dr",
                    "the honorable",
                    "honorable",
                    "hon",
                    "rabbi",
                    "pastor",
                    "rev",
                    "reverend",
                    "sister",
                    "sir",
                    "prof",
                    "professor",
                }
                if not rem or (len(rem.split()) < 2 and (not unambig or _is_organization_only(rem))):
                    break
                if not peeled_nm_civil or peeled_nm_civil[-1].lower() != tok.lower():
                    peeled_nm_civil.append(tok)
                nm = rem
                civil_changed_nm = True
            if not hon and peeled_nm_civil:
                hon = " ".join(peeled_nm_civil)
        if not rank_val:
            probe = nm
            civil_prefix = ""
            if cm := CIVIL_PREFIX.match(probe):
                civil_prefix = probe[: cm.end()]
                probe = probe[cm.end() :]
            if rm := MILITARY_RANK.match(probe):
                after = probe[rm.end() :].strip()
                if pre_ret := re.match(
                    r"^([(\[](?:(?:" + _BRANCH_ABBR + r"),?\s+)?(?:[Rr]et(?:ired)?\.?|RET)[)\]])\s+(.+)$",
                    after,
                ):
                    flat_creds.append(pre_ret.group(1))
                    after = pre_ret.group(2).strip()
                after_first = re.sub(r"\s*[(\[][^)\]]*[)\]]?$", "", _TOP_COMMA.split(after)[0]).strip()
                if len(after_first.split()) >= 2 and not (
                    rm.group(1).strip() in ("General", "Major") and _ORG_NOUN.search(after_first)
                ):
                    rank_val = rm.group(1).strip()
                    nm = ("" if strip_civil_from_name else civil_prefix) + after
                    rank_changed_nm = True
        # Strip a duplicated rank word left immediately after an extracted rank ("Lieutenant General General Scott A. Spellmon",
        # "Major General MG Robert Worley II").
        if rank_val and nm:
            if dup_rm := MILITARY_RANK.match(nm):
                dup_after = nm[dup_rm.end() :].strip()
                if len(_TOP_COMMA.split(dup_after)[0].split()) >= 2:
                    nm = dup_after
                    rank_changed_nm = True
            elif nm.lower().startswith(("(ret.) ", "(retired) ")):
                ret_tok, nm = nm.split(" ", 1)
                flat_creds.append(ret_tok)
                nm = nm.strip()
                rank_changed_nm = True
        # Trailing parenthetical `(RANK, BRANCH[, RET])` on `nm` ("Dr. Stephen Redd (RADM, USPHS)")
        trailing_ret: str | None = None
        if prb := _PAREN_RANK_BRANCH.search(nm):
            if not rank_val:
                rank_val = prb.group(1).strip()
            trailing_ret = prb.group(2).strip()
            nm = nm[: prb.start()].rstrip()
            rank_changed_nm = True
        elif ret_m := _TRAILING_RET_PAREN.search(nm):
            trailing_ret = ret_m.group(1).strip()
            nm = nm[: ret_m.start()].rstrip()
        # Handle mid-name `<Name> Ph.D. <Role/DuplicateSurname>` ("Dr. Dennis Coates Ph.D. Economics", "Mr. Simon Marti, Ph.D. Marti")
        if ", Ph.D. " in nm or ", M.D. " in nm:
            head_nm, tail_nm = nm.split(",", 1)
            if dm := re.match(r"^\s*(Ph\.?D\.?|M\.?D\.?)\s+(\S+)$", tail_nm):
                if head_nm.strip().endswith(" " + dm.group(2)):
                    flat_creds.append(dm.group(1))
                    nm = head_nm.strip()
        elif (mid_m := _MID_NAME_DEGREE_ROLE.match(nm)) and _is_mid_degree_role_tail(mid_m.group(3)):
            nm = mid_m.group(1).strip()
            flat_creds.append(mid_m.group(2).strip())
        # Comma-separated trailing credentials on `nm`
        nm_parts = [p.strip() for p in _TOP_COMMA.split(nm) if p.strip()]
        if (
            len(nm_parts) >= 3
            and re.fullmatch(r"[Rr]et(?:ired)?\.?|RET", nm_parts[-1])
            and re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, nm_parts[-2])
        ):
            nm_parts[-2] = f"{nm_parts[-2]}, {nm_parts[-1]}"
            nm_parts.pop()
        comma_creds: list[str] = []
        while len(nm_parts) > 1:
            last_seg = nm_parts[-1]
            if CREDENTIAL.match(last_seg):
                comma_creds.append(nm_parts.pop())
                continue
            if rk_m := re.fullmatch(
                r"(?:("
                + MILITARY_RANK_PHRASE
                + r")(?:\s+([(\[]?(?:[Rr]et(?:ired)?\.?|RET)[)\]]?(?:\s+"
                + _BRANCH_ABBR
                + r")?|"
                + _BRANCH_ABBR
                + r"(?:\s+[(\[]?(?:[Rr]et(?:ired)?\.?|RET)[)\]]?)?))?"
                r"|(Col|Capt|Maj|Gen|Adm|Cmdr|Sgt|Cpl)\s+([(\[]?(?:[Rr]et(?:ired)?\.?|RET)[)\]]?(?:\s+"
                + _BRANCH_ABBR
                + r")?|"
                + _BRANCH_ABBR
                + r"\s+[(\[]?(?:[Rr]et(?:ired)?\.?|RET)[)\]]?))",
                last_seg,
            ):
                rk_tok = (rk_m.group(1) or rk_m.group(3) or "").strip()
                ret_tok = (rk_m.group(2) or rk_m.group(4) or "").strip()
                if not rank_val and rk_tok:
                    rank_val = rk_tok
                    rank_changed_nm = True
                if ret_tok:
                    comma_creds.append(ret_tok)
                nm_parts.pop()
                continue
            # State nursing licensure code (`NC`) at the end of a credential list ("MSN, CRNA, Col (Ret) USAFR, NC")
            if len(nm_parts) >= 3 and re.fullmatch(r"[A-Z]{2}", last_seg) and any(
                CREDENTIAL.match(p) for p in nm_parts[1:-1]
            ):
                comma_creds.append(nm_parts.pop())
                continue
            break
        comma_creds.reverse()
        nm = ", ".join(nm_parts)
        # Space-separated trailing credentials / rank at the end of `nm` (e.g. `Austin Ph.D`, `Jones PharmD, ..., CAPT`)
        nm_words = nm.split()
        if len(nm_words) > 2 and re.fullmatch(MILITARY_RANK_PHRASE, nm_words[-1]) and not SUFFIX.match(nm_words[-1]):
            cand_rk = nm_words[-1]
            if cand_rk not in ("General", "Major", "Captain", "Commander") and (comma_creds or trailing_ret):
                if not rank_val:
                    rank_val = nm_words.pop()
                    rank_changed_nm = True
        space_creds = _pop_trailing_credentials_from_words(nm_words, min_words=2)
        if space_creds:
            flat_creds.append(" ".join(space_creds))
        flat_creds.extend(comma_creds)
        if trailing_ret:
            if flat_creds and "ret" not in flat_creds[-1].lower() and re.fullmatch(_BRANCH_ABBR, flat_creds[-1]):
                flat_creds[-1] = f"{flat_creds[-1]} {trailing_ret}"
            else:
                flat_creds.append(trailing_ret)
        if rank_changed_nm or civil_changed_nm or flat_creds or fam_creds or suf_creds or giv_creds:
            nm = " ".join(nm_words).rstrip(",") or None
        else:
            nm = orig_nm

    for c in [*giv_creds, *fam_creds, *suf_creds, *flat_creds]:
        if c and c not in cred_parts:
            cred_parts.append(c)

    return {
        "name": nm,
        "honorific": hon,
        "rank": rank_val,
        "credentials": ", ".join(cred_parts) if cred_parts else None,
        "given": giv,
        "family": fam,
        "suffix": suf,
    }


def witness(text: str) -> dict:
    """A witness from GPO's line for them. GPO writes the line three ways: "Mr. Nels Leader, Vice President,
    Bread Alone Bakery", "Richard J. Powell, Executive Director, ClearPath", and surname first, "Campbell, Jr.,
    J.H., President and CEO, Associated Grocers". A name written in order has at least two words before the
    first comma, so a single word there (or a lower-case particle surname, "van Welie, Gordon") is a surname,
    alone or with its suffix ("Chodak III, Dr. Paul"). Military ranks and credentials are returned verbatim in
    `rank` and `credentials` (owner decision 2026-11-10, ct-17op)."""
    text = strip_contents_markers(text)
    text = re.sub(
        r"^\s*(?:(?:opening |prepared |written )?(?:statements?|testimony|remarks) (?:of|by|from)|accompanied by:?|witness(?:es)?:?|panel \w+:?)\s+",
        "",
        text.strip(),
        flags=re.I,
    )
    # Strip bill parentheticals ("Gary Kennedy (H.R. 1963)") and former markers ("(Fmr.)"), keeping retirement
    # parentheticals ("(Ret.)", "(USA, Ret.)") so they land in `credentials` rather than disappearing.
    text = re.sub(r"\s*\([^)]*\d[^)]*\)|\s*[(\[](?:\w+ )?(?:fmr|former)\.?[)\]]", "", text, flags=re.I)

    rank = ""
    pre_creds: list[str] = []
    post_creds: list[str] = []

    title = TITLE.match(text)
    after_title = text[title.end() if title else 0 :]
    if title:
        rank, title_ret = _extract_rank_from_prefix(title.group(0), after_title, min_name_words=2)
        if title_ret:
            pre_creds.append(title_ret)

    parts = _split_witness_commas(after_title)
    name, rest = (parts[0] if parts else ""), parts[1:]
    if len(name.split()) == 2 and SUFFIX.match(name.split()[1]):
        name, rest = name.split()[0], [name.split()[1]] + rest
    elif len(name.split()) == 2 and DEGREE.match(name.split()[1]) and rest:
        # "Osterholm Ph.D., M.P.H., Michael T., Director..." (missing comma between surname and degree)
        name, rest = name.split()[0], [name.split()[1]] + rest
    elif (mid_m := _MID_NAME_DEGREE_ROLE.match(name)) and _is_mid_degree_role_tail(mid_m.group(3)):
        # "Jason Fichtner Ph.D. Senior Research Fellow, Mercatus Center" / "William H. Janes (U.S. Army, Ret.) Director"
        name = mid_m.group(1).strip()
        rest = [mid_m.group(2).strip(), mid_m.group(3).strip(), *rest]

    is_particle_surname = bool(
        name
        and " " in name
        and PARTICLE_SURNAME.match(name)
        and rest
        and not _is_organization_only(rest[0])
        and rest[0].strip(",.-/").lower() not in NOT_A_NAME
    )
    is_leading_acronym = bool(
        re.fullmatch(r"[A-Z]{2,6}", name)
        and rest
        and any(c.islower() for c in rest[0])
        and (" " in rest[0] or rest[0].lower() == "resolution")
    )
    if name and (" " not in name or is_particle_surname) and rest and not is_leading_acronym:
        suffix = rest.pop(0) if SUFFIX.match(rest[0]) else ""
        if rest and _TRAILING_RET_PAREN.fullmatch(rest[0]):
            pre_creds.append(rest.pop(0).strip())  # "Priddy, (Ret.), COL Ronald N., ..."
        ## "Woodruff, Ph.D., MPH, Tracey" / "Acheson, M.D., F.R.C.P., David W.K.": degrees (and >=3-letter dotted
        ## fellowships right after a degree) stand before the given name; 2-letter initials ("J.H.", "D.C.") are the given name.
        after = next(
            (
                i
                for i, s in enumerate(rest)
                if not (
                    CREDENTIAL.match(s)
                    or re.fullmatch(r"(?:[A-Z]\.){3,6}(?:-[A-Z]\.?)*", s)
                    or (
                        i > 0
                        and re.fullmatch(r"[A-Z]\.[A-Z]\.", s)
                        and i + 1 < len(rest)
                        and is_name(f"{TITLE.sub('', rest[i + 1] + ' ').strip()} {name}")
                    )
                )
            ),
            None,
        )
        if rest and DEGREE.match(rest[0]):
            if (
                after
                and TITLE.fullmatch(rest[after] + " ")
                and after + 1 < len(rest)
                and is_name(f"{rest[after + 1]} {name}")
            ):
                # "Quarles, Ph.D., Hon., Ryan F., Commissioner..."
                pre_creds.extend(rest[:after])
                rest = [f"{rest[after]} {rest[after + 1]}", *rest[after + 2 :]]
                given_raw = rest.pop(0)
            elif after and is_name(f"{TITLE.sub('', rest[after] + ' ').strip()} {name}"):
                pre_creds.extend(rest[:after])
                rest = rest[after:]
                given_raw = rest.pop(0) if rest else ""
            elif after and after > 1 and is_name(f"{TITLE.sub('', rest[after - 1] + ' ').strip()} {name}"):
                pre_creds.extend(rest[: after - 1])
                rest = rest[after - 1 :]
                given_raw = rest.pop(0) if rest else ""
            elif after and _is_organization_only(rest[after]):
                # Mononymous entry with degree + organization ("Ellenbogen, Ph.D., Science Museum of Minnesota")
                pre_creds.extend(rest[:after])
                rest = rest[after:]
                given_raw = ""
            else:
                given_raw = rest.pop(0) if rest else ""
        else:
            given_raw = rest.pop(0) if rest else ""
        if given_raw:
            if not title and (given_title := TITLE.match(given_raw + " ")):
                title = given_title
                g_after = (given_raw + " ")[given_title.end() :].strip()
                g_rank, g_ret = _extract_rank_from_prefix(given_title.group(0), g_after, min_name_words=1)
                if g_rank:
                    rank = g_rank
                if g_ret:
                    pre_creds.append(g_ret)
            given_clean = TITLE.sub("", given_raw + " ").strip()
            if ret_m := _TRAILING_RET_PAREN.search(given_clean):
                post_creds.append(ret_m.group(1).strip())
                given_clean = given_clean[: ret_m.start()].strip()
            given = given_clean.split()
            given_space_creds = _pop_trailing_credentials_from_words(given, min_words=1)
            if given_space_creds:
                post_creds = [" ".join(given_space_creds), *post_creds]
            if given and SUFFIX.match(given[-1]):
                suffix = given.pop()  # "Mehan, G. Tracy III"
            if not suffix and rest and SUFFIX.match(rest[0]):
                suffix = rest.pop(0)  # "Jacoby, GEN Charles H., Jr., USA"
            name = " ".join(filter(None, [*given, name, suffix]))
        else:
            name = " ".join(filter(None, [name, suffix]))
    elif rest and SUFFIX.match(rest[0]):
        name = f"{name} {rest.pop(0)}"

    # Capture trailing retirement parenthetical on `name` before stripping non-credential parentheticals
    # ("Elton John (Via Videoconference)", "Tom Malinowski [D-NJ]", "Lorne W. Craner (former Assistant Secretary").
    name_ret = ""
    if ret_m := _TRAILING_RET_PAREN.search(name):
        name_ret = ret_m.group(1).strip()
        name = name[: ret_m.start()].rstrip()
    name = re.sub(r"\s*[(\[][^)\]]*[)\]]?$", "", name)

    words = name.split()
    space_creds = _pop_trailing_credentials_from_words(words, min_words=2)
    name = " ".join(words)
    if space_creds and name_ret and re.fullmatch(_BRANCH_ABBR, space_creds[-1]):
        post_creds.append(" ".join(space_creds) + " " + name_ret)
    else:
        if space_creds:
            post_creds.append(" ".join(space_creds))
        if name_ret:
            post_creds.append(name_ret)

    # Degrees and service-branch credentials immediately follow the name (comma-separated, or space/semicolon-separated
    # before a role or parenthetical when not followed by `Candidate` / `Student`, e.g. "Ph.D. Director", "JD (Minority Witness)").
    while rest:
        if (
            len(rest) >= 2
            and re.fullmatch(_BRANCH_ABBR + r"|" + _BRANCH_FULL, rest[0])
            and re.fullmatch(r"[Rr]et(?:ired)?\.?|RET", rest[1])
        ):
            post_creds.append(f"{rest[0]}, {rest[1]}")
            rest = rest[2:]
            continue
        if (
            rest[0] == "D.C."
            and len(rest) >= 2
            and len(name.split()) >= 2
            and not _is_organization_only(name)
            and _PERSONAL_ROLE.search(rest[1])
        ):
            post_creds.append("D.C.")
            rest.pop(0)
            continue
        s0 = rest[0].rstrip(".") if rest[0].endswith("..") else rest[0]
        if (
            not rank
            and len(name.split()) >= 2
            and not _is_organization_only(name)
            and re.fullmatch(MILITARY_RANK_PHRASE, s0)
            and (
                s0.isupper()
                or "." in s0
                or (
                    len(rest) >= 2
                    and bool(
                        re.match(
                            r"^(?:" + _BRANCH_ABBR + r"|" + _BRANCH_FULL + r"|[(\[](?:[Rr]et|[A-Z]))",
                            rest[1],
                        )
                    )
                )
            )
        ):
            rank = s0
            rest.pop(0)
            continue
        if CREDENTIAL.match(s0):
            post_creds.append(s0)
            rest.pop(0)
            continue
        if lead_m := _LEADING_SEG_CREDENTIAL.match(rest[0]):
            cred_tok = lead_m.group(1).strip()
            rem_seg = rest[0][lead_m.end() :].strip()
            post_creds.append(cred_tok)
            if rem_seg:
                rest[0] = rem_seg
            else:
                rest.pop(0)
            continue
        break

    # Strip retirement parentheticals inside remaining affiliation segments ("Director, on behalf of (Ret.) :").
    rest = [re.sub(r"\s*[(\[](?:\w+ )?ret(?:ired)?\.?[)\]]", "", s, flags=re.I).strip() for s in rest]
    rest = [s for s in rest if s]

    credentials = ", ".join([*pre_creds, *post_creds])
    honorific = title.group(1) if title else ""
    if len(rest) == 1 and (is_name(name) or (name.isupper() and is_name(name.title()))) and _is_organization_only(rest[0]):
        position, organization = "", rest[0]
    else:
        position, organization = (rest[0] if rest else ""), ", ".join(rest[1:])
    return {
        "name": name,
        "honorific": honorific if honorific in ("Mr.", "Ms.", "Mrs.", "Dr.") else "",
        "rank": rank,
        "credentials": credentials,
        "position": position,
        "organization": organization,
    }


def person_key(name: str) -> str:
    """'Hon. Ben Cline' -> 'cline-ben'; 'Mr. Dunham' -> 'dunham'."""
    parts = [
        p
        for p in re.sub(r"[^\w\s-]", "", name).lower().split()
        if p
        not in (
            "hon", "the", "mr", "ms", "mrs", "dr", "senator", "representative",
            "chairman", "chairwoman", "chair", "jr", "sr", "ii", "iii",
        )
    ]
    if not parts:
        return "unknown"
    return parts[-1] if len(parts) == 1 else f"{parts[-1]}-{parts[0]}"
