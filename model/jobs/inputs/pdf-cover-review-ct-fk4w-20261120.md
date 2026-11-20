# Qualified PDF Cover Evidence & Residual Contradiction Review — 20 November 2026 (`ct-fk4w`)

## 1. Scope & Ownership Decisions

1. **Single maintained cover-evidence path (`pdf_cover_evidence.classify_selected_covers`):**
   - Consumes qualified selected `pdf_text` from `body-text-selection-v13` (`accepted-selection `identity.sha256` `bbeb4e1c94e195ac8ec5085578331543b2b2f709e77d2c83e523474e07bbe10b`), slicing Page 1 `[:2048]` (`body_text_slices.slice_pages(..., max_pages=1)[:2048]`) into maintained `model/sql/body-signals.sql` and `model/registries/page-signals.json`.
   - Page-1 restriction and SQL negative guards (`is_crs_memo_or_testimony`, `is_committee_report`, `is_support_letter`, removal of bare `MEMORANDUM` from `cover:meeting-notice`, and CRS banner/domain/phone requirement on `cover:crs-report`) eliminate page-2 footnote citations, committee staff memos citing CRS, support letters citing questionnaires, and committee reports quoting CBO cost estimates.
   - Retains the 2 directly source-reviewed 115th-Congress disclosure bodies from `pdf-cover-review-ct-fk4w-20261117.md` (`00472521603f9b066f5fead27a3ad15f4f6c8d16fc52f066709f546b842abc69` Gudes and `008bdb052fca58f4d411e3cc8a24bd3fab486cbaf753bf9549066bb1b5bc345f` Colosimo) where the conservative regex abstains; Saperstein (`0201014207ca22f3f4519fadbd5ade2f75fe23064fc1aeac629cd0eeac2eb637`) is classified directly by `classify_selected_covers`.
2. **Explicit single-name kind-correction policy (`model/sql/body-cover-kinds.sql`):**
   - Verified Tier-1 PDF cover kinds apply **only** when a document currently has:
     - an empty `document_kind` (`[]`),
     - an ambiguous Clerk/committee upload slot filename (`-Bio-`, `-SD-`, `-Wstate-`), or
     - a single generic/slot kind (`witness-biography`, `biography`, `support-document`, `supporting-material`, `witness-support`, `meeting-support`).
   - Specific non-slot publisher labels (`bill`, `bill-numbered`, `amendment`, `committee-report`, `committee-print`, `published-hearing`, `committee-transcript`, `vote-record`) are never overwritten by cover heuristics, and publisher `filename` / meeting associations are never mutated.
   - Ambiguous or unverified bodies abstain and retain their existing filename-derived kinds; OCR completion alone never changes a kind.
3. **Misfiled publisher transcript preserved (`event 101019`):**
   - `0674d6153bdf15d9b591390cf3f76e6845a06a997f4252769ef1363ded548609` (`HHRG-113-WM02-Transcript-20130620.pdf` on June 20, 2013 Ways and Means Health Subcommittee `101019`) is confirmed by Page-1 text to be the GPO print for the July 10, 2013 hearing *"THE DELAY OF THE EMPLOYER MANDATE"* (`Serial No. 113–HL06`, `21–104`), sharing bytes with `https://waysandmeans.house.gov/wp-content/uploads/2017/07/20130710HL.pdf` while `CHRG-113hhrg21104.pdf` sits on July 10 meeting `101127`. Per `ct-fk4w` scope, the House's publisher filing and `HHRG-113-WM02-Transcript-20130620.pdf` identity are preserved rather than inventing a synthetic source reassignment (`transcript-print-covers.sql` already normalizes its kind/family to `published-hearing`).
4. **Residual multi-source filename contradictions (`model/registries/saved-name-decisions.json`):**
   - All **24** remaining undecided non-slot `official` vs `committee` filename contradictions on release `2ec7ae83a852` were read from Page-1 PDF text and recorded in `model/registries/saved-name-decisions.json` (`84 -> 108` entries; `0` unmet, `0` unused):
     - `21` Natural Resources / Education & Labor roll-call tally sheets (`CRPT-115-II00-Vote*`, `CRPT-116-ED00-Vote*`) where committee filenames (`rc_*_fav_report_*`, `*_toReport_*`) meant motion to favorably report (`decision = "official"`).
     - `2` Amendments in the Nature of a Substitute (`d10ef863d669afcd...` `BILLS-114-HRes-R000570-Amdt-1.pdf` and `3f40b5a7d8523289...` `BILLS-118-OversightPlan-S001195-Amdt-1.pdf`) whose committee filenames mentioned the target `Committee-Print` / `Oversight-Plan` (`decision = "official"`).
     - `1` Amendment in the Nature of a Substitute to H.R. 2789 (`919838d0b98f1320...`) misnamed `BILLS-118HR2789ih.pdf` in the House repository while committee copy `3DBE62036240C41F942F7C58746B69EB5C4A450566F73A6EC88B65CF3014C166.ans-to-hr2789.pdf` accurately names the ANS (`decision = "committee"`).
   - For the `459` competing multi-source official-pair documents (`official_leads AND NOT committee_speaks`), `body-cover-kinds.sql` updates `14` documents with verified Page-1 cover kinds while leaving the remaining slot-pair documents (predominantly witness statement + biography or statement + Truth-in-Testimony combined packets uploaded to multiple Clerk slots) conservatively unchanged without inventing filenames.

## 2. Release Coverage & Missing / Refused / Excluded Accounting (`2ec7ae83a852`)

- **PDF documents in release:** `298,013` documents across `297,691` distinct PDF `saved_body` digests.
- **Qualified selected `pdf_text` available in local v12/v13 export:** `296,798` bodies (`99.70%`).
- **Unavailable / excluded / post-export incremental PDF bodies (`893`):** `{"incremental_post_v12_export": 893}` (remains conservatively unresolved; no blanket empty-work-list prerequisite).
- **Eligible cover-policy PDF bodies inspected:** `126,554` of `126,849` eligible PDF bodies.
- **Qualified PDF cover evidence rows written:** `1,379` (`1,378` from `classify_selected_covers` + `2` Nov-17 source-reviewed 115th-Congress disclosure forms).

## 3. Before / After Kind Transitions on `2ec7ae83a852` (`1,379` documents)

- Single-source empty/slot documents updated: `1,096`
- Multi-source slot documents updated: `269`
- Competing official-pair documents updated: `14`

| `before_kind -> after_kind` | Documents |
|---|---:|
| `<empty> -> testimony-disclosure` | 545 |
| `witness-biography -> testimony-disclosure` | 276 |
| `meeting-support -> meeting-notice` | 217 |
| `meeting-support -> witness-list` | 136 |
| `meeting-support -> subpoena` | 49 |
| `witness-statement -> testimony-disclosure` | 41 |
| `witness-support -> testimony-disclosure` | 35 |
| `meeting-support -> crs-report` | 16 |
| `<empty> -> meeting-notice` | 10 |
| `<empty> -> crs-report` | 8 |
| `meeting-support -> testimony-disclosure` | 7 |
| `<empty> -> witness-list` | 6 |
| `meeting-support -> federal-register-notice` | 6 |
| `biography -> testimony-disclosure` | 5 |
| `<empty> -> cost-estimate` | 4 |
| `<empty> -> gao-report` | 4 |
| `meeting-support -> gao-report` | 4 |
| `meeting-support -> cost-estimate` | 3 |
| `meeting-support -> staff-report` | 3 |
| `<empty> -> subpoena` | 1 |
| `meeting-notice,meeting-support -> subpoena` | 1 |
| `witness-statement -> cost-estimate` | 1 |
| `witness-support -> crs-report` | 1 |

## 4. Stratified Direct Source-Text Review Sample Across Every Transition

- **`<empty> -> cost-estimate`** — `hr5078.pdf` (`0337dfca6259`, doc `0337dfca62590d69`): `CONGRESSIONAL BUDGET OFFICE COST ESTIMATE August 1, 2014   H.R. 5078 Waters of the United States Regulatory Overreach Protection Act of 2014  As ordered reported by the House Commi`
- **`<empty> -> crs-report`** — `20210820_CRS_AfghanistanFAQ_R46879.pdf` (`28bf48c5379b`, doc `28bf48c5379b0d6c`): `U.S. Military Withdrawal and Taliban Takeover in Afghanistan: Frequently Asked Questions August 20, 2021 Congressional Research Service https://crsreports.congress.gov R46879  Cong`
- **`<empty> -> gao-report`** — `20090507GAO.pdf` (`13d58814fce3`, doc `13d58814fce3bb9f`): `GAO  United States Government Accountability Office Report to the Subcommittee on National Security and Foreign Affairs, Committee on Oversight and Government Reform, House of Repr`
- **`<empty> -> meeting-notice`** — `DB59D55AEEB004CA648CDB4660B53C36FC0FE6B4134C6D07646A70B7315BAB3C.2024.05.16-full-committee-markup.pdf` (`16228294b491`, doc `16228294b4916e9c`): `COMMITTEE ON FOREIGN AFFAIRS FULL COMMITTEE MARKUP NOTICE U.S. HOUSE OF REPRESENTATIVES WASHINGTON, DC 20515-6128  Michael T. McCaul (R-TX), Chairman  May 13, 2024  Revised  TO: ME`
- **`<empty> -> subpoena`** — `subpoenafinal111202.pdf` (`cba5c00521e5`, doc `cba5c00521e5cb2c`): `SUBPOENA BY AUTHORITY OF THE HOUSE OF REPRESENTATIVES OF THE CONGRESS OF THE UNITED STATES OF AMERICA To You are hereby commanded to be and appear before the Committee on Agricultu`
- **`<empty> -> testimony-disclosure`** — `07.14.11_hara_tt.pdf` (`000f2e673a01`, doc `000f2e673a019668`): `COMMITTEE ON EDUCATION AND THE WORKFORCE U.S. HOUSE OF REPRESENTATIVES Truth in Testimony Disclosure Form clause 2(g) of rule XI of the Rules of the House of Representatives and th`
- **`<empty> -> witness-list`** — `20090519172147.pdf` (`509e8f2cdebd`, doc `509e8f2cdebd091e`): `WITNESS LIST  COMMITTEE ON OVERSIGHT AND GOVERNMENT REFORM  Hearing on "State and Local Pandemic Preparedness"  Wednesday, May 20, 2009  PANEL I  • Dr. Daniel M. Sosin Director Coo`
- **`biography -> testimony-disclosure`** — `Stuart_Archer_CV_Feb_2023_9c23250944.pdf` (`048ecb1c59d1`, doc `048ecb1c59d184fe`): `Committee on Energy and Commerce U.S. House of Representatives Witness Disclosure Requirement - "Truth in Testimony" Required by House Rule XI, Clause 2(g)(5) 1. Your Name: Stuart `
- **`meeting-notice,meeting-support -> subpoena`** — `HMTG-112-HHRG-IF02-20121114-SD002.pdf` (`2f66258e49d0`, doc `102017e3c1cc8a69`): `SUBPOENA By AUTHORITY OF THE HOUSE OF REPRESENTATIVES OF THE CONGRESS OF THE UNITED STATES OF AMERICA Barry Cadden, President, Co-owner, and Managing Pharmacist, New England Compou`
- **`meeting-support -> cost-estimate`** — `HMKP-117-GO00-20210720-SD006.pdf` (`7e79c4007e9e`, doc `7e79c4007e9ec25e`): `See also CBO's Cost Estimates Explained, www.cbo.gov/publication/54437; How CBO Prepares Cost Estimates, www.cbo.gov/publication/53519; and Glossary, www.cbo.gov/publication/42904.`
- **`meeting-support -> crs-report`** — `HHRG-118-FD00-20240206-SD002.pdf` (`15226b6a78e3`, doc `15226b6a78e39bf7`): `CRS INSIGHT Prepared for Members and Committees of Congress      INSIGHTi The AI Executive Order and Its Potential Implications for DOD December 12, 2023 On October 20, 2023, Presi`
- **`meeting-support -> federal-register-notice`** — `HHRG-116-IF02-20190521-SD009.pdf` (`19e7d19ee465`, doc `19e7d19ee4651108`): `GP 2670 Federal Register/ Vol. 84, No. 26/Thursday, February 7, 2019/Proposed Rules ENVIRONMENTAL PROTECTION AGENCY 40 CFR Part 63 [EPA-HQ-OAR-2018-0794; FRL-9988-93- OAR] RIN 2060`
- **`meeting-support -> gao-report`** — `HHRG-118-II06-20230228-SD015.pdf` (`022e80cdf4f9`, doc `022e80cdf4f98a64`): `GAO January 2016 United States Government Accountability Office Report to the Chairman, Committee on Natural Resources, House of Representatives HARDROCK MINING BLM and Forest Serv`
- **`meeting-support -> meeting-notice`** — `HMKP-117-IF16-20220615-SD002.pdf` (`005a0ada49a7`, doc `005a0ada49a73964`): `June 13, 2022  SUBCOMMITTEE ON COMMUNICATIONS AND TECHNOLOGY  MARKUP NOTICE   TO:   Members, Subcommittee on Communications and Technology  FROM:  Mike Doyle, Chairman  SUBJECT: Su`
- **`meeting-support -> staff-report`** — `HMKP-116-JU00-20191211-SD1045.pdf` (`a6d7ab2101bf`, doc `a6d7ab2101bf7ae2`): `STATE SECRETS: HOW AN AVALANCHE OF MEDIA LEAKS IS HARMING NATIONAL SECURITY                A Majority Staff Report of the  Committee on Homeland Security and Governmental Affairs U`
- **`meeting-support -> subpoena`** — `HMTG-117-IJ00-20211201-SD001-U1.pdf` (`0264f939ba14`, doc `0264f939ba14d408`): `SUBPOENA BY AUTHORITY OF THE HOUSE OF REPRESENTATIVES OF THE CONGRESS OF THE UNITED STATES OF AMERICA Jeflrey B. Clark To c/o Robert Driscoll, Esq., McGlinchey, Stafford, PLLC You `
- **`meeting-support -> testimony-disclosure`** — `HHRG-114-BU00-20160615-SD001.pdf` (`2037f77d38da`, doc `2037f77d38da03d4`): `Committee on the Budget Witness Disclosure Requirement - "Truth in Testimony" Required by House Rule XI, Clause 2(g) Your Name: Dovalas Holtz-Eakin Yes No 1. Will you be representi`
- **`meeting-support -> witness-list`** — `HHRG-116-VR11-20200916-SD085.pdf` (`0313f4d02ea7`, doc `0313f4d02ea7cb38`): `Witness List 116th Congress U.S. House of Representatives Committee on Veterans' Affairs Subcommittees on Technology Modernization and Health Hearing  "Moving Beyond Patchwork Syst`
- **`witness-biography -> testimony-disclosure`** — `HHRG-117-AG29-Bio-MeierE-20220203.pdf` (`003e32aa303f`, doc `003e32aa303fc1f6`): `Truth in Testimony Disclosure Form In accordance with Rule XI, clause 2(g)(5)* of the Rules of the House of Representatives, witnesses are asked :o disclose the following informati`
- **`witness-statement -> cost-estimate`** — `HHRG-116-II13-Wstate-NezJ-20190626.pdf` (`57e1d8046b50`, doc `57e1d8046b50890d`): `See also CBO's Cost Estimates Explained, www.cbo.gov/publication/54437; How CBO Prepares Cost Estimates, www.cbo.gov/publication/53519; and Glossary, www.cbo.gov/publication/42904.`
- **`witness-statement -> testimony-disclosure`** — `HHRG-115-ED02-Wstate-SossaE-20170518.pdf` (`02c094f1be45`, doc `02c094f1be453356`): `COMMITTEE ON EDUCATION AND THE WORKFORCE U.S. HOUSE OF REPRESENTATIVES Truth in Testimony Disclosure Form Clause 2(g) of rule XI of the Rules of the House of Representatives and th`
- **`witness-support -> crs-report`** — `HHRG-117-JU10-Wstate-MaskellJ-20210311-SD001.pdf` (`09d78241cf44`, doc `09d78241cf44a441`): `Expulsion, Censure, Reprimand, and Fine: Legislative Discipline in the House of Representatives Jack Maskell Legislative Attorney June 27, 2016 Congressional Research Service 7-570`
- **`witness-support -> testimony-disclosure`** — `HHRG-115-II13-Wstate-GudesS-20171130-SD011.pdf` (`00472521603f`, doc `00472521603f9b06`): `1   COMMITTEE ON NATURAL RESOURCES 115th Congress Disclosure Form As required by and provided for in House Rule XI, clause 2(g)(5)  Legislative Hearing on H.R. 4419 (Rep. Dan Newho`
