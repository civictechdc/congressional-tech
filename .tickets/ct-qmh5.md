---
id: ct-qmh5
status: closed
deps: []
links: [ct-en4n]
created: 2026-11-20T23:32:58Z
type: bug
priority: 1
assignee: mikewolfd
tags: [explorer, recovery, publication]
---
# Remove unqualified saved copies from usable Explorer downloads

Explorer release `0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3` lists 26 affected records by default. Their detail pages and five additional hidden detail pages offer unqualified saved copies. All 31 records lack text for the affected saved body in v13 export `7aea7925da324273d16c04e7dd7d53b2a7d3a0ade895f9343063015458d88688`.

| Affected records | In default list | Detail offers saved copy |
| --- | ---: | ---: |
| Damaged PDFs | 22 | 22 |
| State Department HTML error payloads | 2 | 2 |
| Linked State Department archive wrappers | 2 | 2 |
| Natural Resources HTML errors at five document targets | 0 | 5 |
| Total | 26 | 31 |

State payload link keys `359e3b8b6b844d69` and `82867326cf8750a2` correspond to wrappers `6eea94ddc3e78724` and `b6aaf0d8fdba71e2`, respectively. Check all four Explorer records and keep one recovery decision per payload. The hidden Natural Resources keys are `85afe0532f6c8e0b`, `a3002f39e37a6384`, `90bd27046786ab4e`, `8b408d366abfb89d` and `e8c6aced18461017`. The last two share one saved body.

The verification ledger pinned by `docs/plans/ocr-source-recovery-inventory.json` identifies all 31 link keys and saved hashes under `public_copy_control.records`. Explorer lists unhidden records by default. On a detail page, a primary saved body enables the primary and alternate links. A recovery with different bytes has its own link, including when the primary is absent. The five Natural Resources pages and the Walling page (`20568d1abba1b309`) each reference their invalid body as both primary and recovery. Clearing those primaries still leaves six recovery downloads. Walling already counts among the 22 damaged PDF pages.

## Acceptance Criteria

1. Resolve every one of the 31 link keys in a successor published release. Record the release ID, document identity, default-list visibility, detail-page download availability and the qualification of any saved replacement. Document the disposition of missing or reassociated records.
2. Verify zero default-list records exposing an unqualified saved copy and zero detail pages offering one. Check primary, alternate and recovery links, including the five hidden details. Count each detail link key once. Repeat with invalid primaries cleared to confirm the guard still detects surviving links.
3. Offer qualified replacements where available and report outstanding recovery per payload and document target. Preserve the original bytes, receipts, legitimate wrapper controls and document identities. Return the per-record release evidence to ct-en4n.

## Notes

**2026-11-20T23:33:34Z**

The November 20 public-copy verification returned exit 1 with 24 counterexamples. The same run confirmed zero inventory originals in the v13 text export. Use the live document and recovery associations in the evidence ledger when testing a successor release.

**2026-11-20T23:54:56Z**

The figure of 24 above counted unhidden inventory originals in the first pass. The corrected guard includes the two State wrappers and measures detail downloads on hidden rows. The current baseline is 26 visible records and 31 detail downloads.

**2026-11-21T05:58:20Z**

The public release pointer still named `0e7084cde775` on November 21. The verified baseline for that release is 26 affected records in the default list and 31 distinct detail pages offering a bad copy. Fix the download choices, keep each usable replacement, and check all 31 pages on the next release containing the fix. Include the six pages where clearing the primary copy alone leaves a bad recovery download. Return the per-page results to [the source audit](ct-en4n.md).

**2026-11-21T06:38:58Z**

The model now withholds 30 reviewed bad files from primary, alternate and recovery downloads. A release rebuilt from test receipts kept the document addresses and the usable recovery. The prior public release still offers bad files on 31 detail pages. The public check also protects the verified Vargas testimony and 117 previously working document links. Close after running that check against the successor.

**2026-11-21T09:03:15Z**

Closed after reading public release `1fad38cc75ba023aca4af5b2184564869eff9831414c00678310d38370f89eae`, published November 21 at 08:59 UTC. All 31 permanent document links retain their identities. Twenty-six are visible in the default list and five are hidden. No primary, alternate, or recovery download exposes any of the 30 reviewed bad byte sequences anywhere in the released tables.

The Vargas page offers the one qualified replacement. Opening its recovery link in a real browser reached the verified PDF, 316,962 bytes, SHA-256 `dbf810aec21993d6cc720bbef8969e5811f92d7e30fc6c6e29bd2ecfa3671c7a`. The other 30 affected pages offer no saved download. Live browser checks also opened the Walling page and the hidden Westerman page. Both retain their document information and show the unavailable-copy message.

All 117 previously working control documents retained their 121 required document-to-file matches. The planted test with only primary links removed still caught six bad recovery links. A separately planted bad alternate also failed. The successor check found zero.

The rows below preserve the 28 underlying source decisions across 31 document targets, including the two State Department wrapper pairs and the Bakst and Mitchell records that shared an error response.

| Document | In default list | Reviewed payload | Source targets | Saved download and recovery status |
| --- | --- | --- | --- | --- |
| [7451a1761b7038e9](https://civictechdc.github.io/congressional-tech/archive/?key=7451a1761b7038e9) 07-26-23__us-economic-security-addressing-economic-coercion-and-increasing-competitiveness | Yes | `7451a1761b70` | [1](<https://www.foreign.senate.gov/download/07-26-23__us-economic-security-addressing-economic-coercion-and-increasing-competitiveness>) [2](<https://www.foreign.senate.gov/imo/media/doc/699581a7-0d9f-1875-acf9-a8ed3fab7924/07%2026%2023%20--%20U.S.%20Economic%20Security%20Addressing%20Economic%20Coercion%20and%20Increasing%20Competitiveness.pdf>) | No saved copy. A separately identified hearing print contains material from this submission. The exact original remains open. |
| [82fd78b27f862a10](https://civictechdc.github.io/congressional-tech/archive/?key=82fd78b27f862a10) 11-15-11_Melvin_FedWkfc_Testimony.pdf | Yes | `82fd78b27f86` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/11-15-11_Melvin_FedWkfc_Testimony.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [4c53c6108c99bae5](https://civictechdc.github.io/congressional-tech/archive/?key=4c53c6108c99bae5) 11-2-11_RegAffairs_Montgomery_Testimony.pdf | Yes | `4c53c6108c99` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/11-2-11_RegAffairs_Montgomery_Testimony.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [6eea94ddc3e78724](https://civictechdc.github.io/congressional-tech/archive/?key=6eea94ddc3e78724) 119037.htm | Yes | `359e3b8b6b84` | [1](<https://2009-2017.state.gov/j/drl/rls/hrrpt/2009//index.htm>) [2](<https://www.state.gov/g/drl/rls/hrrpt/2008/eap/119037.htm>) | No saved copy. Source history is recorded. The original still needs review. |
| [82867326cf8750a2](https://civictechdc.github.io/congressional-tech/archive/?key=82867326cf8750a2) 119153.htm | Yes | `82867326cf87` | [1](<https://www.state.gov/g/drl/rls/hrrpt/2008/wha/119153.htm>) | No saved copy. Source history is recorded. The original still needs review. |
| [b6aaf0d8fdba71e2](https://civictechdc.github.io/congressional-tech/archive/?key=b6aaf0d8fdba71e2) 119153.htm | Yes | `82867326cf87` | [1](<https://www.state.gov/g/drl/rls/hrrpt/2008/wha/119153.htm>) | No saved copy. Source history is recorded. The original still needs review. |
| [9c50cb2fe0da5c37](https://civictechdc.github.io/congressional-tech/archive/?key=9c50cb2fe0da5c37) 12-14-11_Minority_Hearing_Powell_Testimony.pdf | Yes | `9c50cb2fe0da` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/12-14-11_Minority_Hearing_Powell_Testimony.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [9edf73c620331e8b](https://civictechdc.github.io/congressional-tech/archive/?key=9edf73c620331e8b) 12-14-11_NRC_Ostendorff_Testimony.pdf | Yes | `9edf73c62033` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/12-14-11_NRC_Ostendorff_Testimony.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [393a5e8418852b43](https://civictechdc.github.io/congressional-tech/archive/?key=393a5e8418852b43) 12-7-11_Medicaid_Fraud_Cantrell_Testimony_FINAL.pdf | Yes | `393a5e841885` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/12-7-11_Medicaid_Fraud_Cantrell_Testimony_FINAL.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [08ca05e57e8d6dd9](https://civictechdc.github.io/congressional-tech/archive/?key=08ca05e57e8d6dd9) 12-7-11_Medicaid_Fraud_Richard_West_Testimony.pdf | Yes | `08ca05e57e8d` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/12-7-11_Medicaid_Fraud_Richard_West_Testimony.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [d2ba37b370d011c1](https://civictechdc.github.io/congressional-tech/archive/?key=d2ba37b370d011c1) 20090423Ruckelshaus.pdf | Yes | `d2ba37b370d0` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/20090423Ruckelshaus.pdf>) | No saved copy. The retained original awaits a qualification decision. |
| [05fc38c285f3af95](https://civictechdc.github.io/congressional-tech/archive/?key=05fc38c285f3af95) 20090519Reuter.pdf | Yes | `05fc38c285f3` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/20090519Reuter.pdf>) | No saved copy. The retained original awaits a qualification decision. |
| [4c90083757ecf4ef](https://civictechdc.github.io/congressional-tech/archive/?key=4c90083757ecf4ef) 20090624Dicken.pdf | Yes | `4c90083757ec` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/20090624Dicken.pdf>) | No saved copy. The retained original awaits a qualification decision. |
| [1bf7f4055319d6fd](https://civictechdc.github.io/congressional-tech/archive/?key=1bf7f4055319d6fd) 20090709Vargas.pdf | Yes | `1bf7f4055319` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/20090709Vargas.pdf>) | Qualified Vargas testimony. The NARA recovery matches the source review. |
| [7b2002ff1a8592d3](https://civictechdc.github.io/congressional-tech/archive/?key=7b2002ff1a8592d3) 4-20-11_Simpson_Syracuse_Testimony.pdf | Yes | `7b2002ff1a85` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/4-20-11_Simpson_Syracuse_Testimony.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [65b640217635a378](https://civictechdc.github.io/congressional-tech/archive/?key=65b640217635a378) 9-13-2011_BousheyTestimony.pdf | Yes | `65b640217635` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/9-13-2011_BousheyTestimony.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [aa4b1c25d0dba16e](https://civictechdc.github.io/congressional-tech/archive/?key=aa4b1c25d0dba16e) Foerter_Testimony_ICAC.pdf | Yes | `aa4b1c25d0db` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/Foerter_Testimony_ICAC.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [e75db22795c2294a](https://civictechdc.github.io/congressional-tech/archive/?key=e75db22795c2294a) Gordon_Testimony_3-16-11.pdf | Yes | `e75db22795c2` | [1](<https://oversight.house.gov/wp-content/uploads/2012/01/Gordon_Testimony_3-16-11.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [0cbdd25415da2660](https://civictechdc.github.io/congressional-tech/archive/?key=0cbdd25415da2660) HHRG-114-AS29-Bio-WeatheringtonD-20150325.pdf | Yes | `0cbdd25415da` | [1](<http://docs.house.gov/meetings/AS/AS29/20150325/103106/HHRG-114-AS29-Bio-WeatheringtonD-20150325.pdf>) [2](<https://docs.house.gov/meetings/AS/AS29/20150325/103106/HHRG-114-AS29-Bio-WeatheringtonD-20150325.pdf>) | No saved copy. The hearing print omits the submission. Its original remains missing. |
| [a38be43af4d9a72f](https://civictechdc.github.io/congressional-tech/archive/?key=a38be43af4d9a72f) HHRG-116-VR03-Transcript-20191030.pdf | Yes | `a38be43af4d9` | [1](<https://www.congress.gov/116/meeting/house/110128/documents/HHRG-116-VR03-Transcript-20191030.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [d01597f14710e929](https://civictechdc.github.io/congressional-tech/archive/?key=d01597f14710e929) HHRG-117-GO00-TTF-CrabtreeN-20211028.pdf | Yes | `d01597f14710` | [1](<https://www.congress.gov/117/meeting/house/114185/witnesses/HHRG-117-GO00-TTF-CrabtreeN-20211028.pdf>) | No saved copy. The hearing print omits the submission. Its original remains missing. |
| [8a4e17b459216f01](https://civictechdc.github.io/congressional-tech/archive/?key=8a4e17b459216f01) HHRG-117-VR00-TTF-BarlettT-20220428-U1.pdf | Yes | `8a4e17b45921` | [1](<http://docs.house.gov/meetings/VR/VR00/20220428/114671/HHRG-117-VR00-TTF-BarlettT-20220428-U1.pdf>) [2](<https://docs.house.gov/meetings/VR/VR00/20220428/114671/HHRG-117-VR00-TTF-BarlettT-20220428-U1.pdf>) [3](<https://www.congress.gov/117/meeting/house/114671/witnesses/HHRG-117-VR00-TTF-BarlettT-20220428-U1.pdf>) | No saved copy. The source returned the same unusable bytes on retry. |
| [dfdd2b8e943c1ef8](https://civictechdc.github.io/congressional-tech/archive/?key=dfdd2b8e943c1ef8) HHRG-118-VR11-Transcript-20241212.pdf | Yes | `dfdd2b8e943c` | [1](<https://www.congress.gov/118/meeting/house/117751/documents/HHRG-118-VR11-Transcript-20241212.pdf>) | No saved copy. A separately identified hearing print contains material from this submission. The exact original remains open. |
| [85afe0532f6c8e0b](https://civictechdc.github.io/congressional-tech/archive/?key=85afe0532f6c8e0b) HR_5283_Westerman_ANS.pdf | No | `0df2d0da7fa6` | [1](<https://naturalresources.house.gov/UploadedFiles/HR_5283_Westerman_ANS.pdf>) [2](<https://naturalresources.house.gov/uploadedfiles/hr_5283_westerman_ans.pdf>) | No saved copy. Source history is recorded. The original still needs review. |
| [42978b9c1d539c24](https://civictechdc.github.io/congressional-tech/archive/?key=42978b9c1d539c24) index.cfm | Yes | `42978b9c1d53` | [1](<https://www.jec.senate.gov/public/_cache/files/8dcde177-fed6-4d41-89ed-9d92e0bcc827/gao-26-109023.pdf>) [2](<https://www.jec.senate.gov/public/index.cfm?a=Files.Serve&File_id=8DCDE177-FED6-4D41-89ED-9D92E0BCC827>) | No saved copy. Recovery requires a human browser capture of the source. |
| [359e3b8b6b844d69](https://civictechdc.github.io/congressional-tech/archive/?key=359e3b8b6b844d69) index.htm | Yes | `359e3b8b6b84` | [1](<https://2009-2017.state.gov/j/drl/rls/hrrpt/2009//index.htm>) [2](<https://www.state.gov/g/drl/rls/hrrpt/2008/eap/119037.htm>) | No saved copy. Source history is recorded. The original still needs review. |
| [90bd27046786ab4e](https://civictechdc.github.io/congressional-tech/archive/?key=90bd27046786ab4e) Resume_Nau.pdf | No | `34c58155d0ed` | [1](<https://naturalresources.house.gov/UploadedFiles/Resume_Nau.pdf>) [2](<https://naturalresources.house.gov/uploadedfiles/resume_nau.pdf>) | No saved copy. Source history is recorded. The original still needs review. |
| [e8c6aced18461017](https://civictechdc.github.io/congressional-tech/archive/?key=e8c6aced18461017) Testimony___Mitchell.pdf | No | `5d1f51c93c7f` | [1](<https://naturalresources.house.gov/UploadedFiles/Testimony_Bakst.pdf>) [2](<https://naturalresources.house.gov/UploadedFiles/Testimony___Mitchell.pdf>) [3](<https://naturalresources.house.gov/uploadedfiles/testimony___mitchell.pdf>) [4](<https://naturalresources.house.gov/uploadedfiles/testimony_bakst.pdf>) | No saved copy. Source history is recorded. The original still needs review. |
| [8b408d366abfb89d](https://civictechdc.github.io/congressional-tech/archive/?key=8b408d366abfb89d) Testimony_Bakst.pdf | No | `5d1f51c93c7f` | [1](<https://naturalresources.house.gov/UploadedFiles/Testimony_Bakst.pdf>) [2](<https://naturalresources.house.gov/UploadedFiles/Testimony___Mitchell.pdf>) [3](<https://naturalresources.house.gov/uploadedfiles/testimony___mitchell.pdf>) [4](<https://naturalresources.house.gov/uploadedfiles/testimony_bakst.pdf>) | No saved copy. Source history is recorded. The original still needs review. |
| [a3002f39e37a6384](https://civictechdc.github.io/congressional-tech/archive/?key=a3002f39e37a6384) Testimony_Whipps_Jr..pdf | No | `3192a4c231de` | [1](<https://republicans-naturalresources.house.gov/UploadedFiles/Testimony_Whipps_Jr..pdf>) | No saved copy. Source history is recorded. The original still needs review. |
| [20568d1abba1b309](https://civictechdc.github.io/congressional-tech/archive/?key=20568d1abba1b309) Walling Statement 3-15 Flint Water II.pdf | Yes | `ed0298387f8c` | [1](<https://oversightdemocrats.house.gov/imo/media/doc/documents/Walling%20Statement%203-15%20Flint%20Water%20II.pdf>) [2](<https://oversightdemocrats.house.gov/sites/democrats.oversight.house.gov/files/documents/Walling%20Statement%203-15%20Flint%20Water%20II.pdf>) | No saved copy. A usable original still needs recovery. |

The release record names every changed document link, lookup key and source address. The complete per-page readback, control results, and HTTPS responses are under `.cache/archive-release/fix-downloads-page151-20261121/download-review/` in the main checkout. [Reviewed release record](https://github.com/civictechdc/congressional-tech/pull/223) · [Public release manifest](https://congressional-data.spicygov.ai/viewer-publications/releases/1fad38cc75ba023aca4af5b2184564869eff9831414c00678310d38370f89eae/manifest.json)
