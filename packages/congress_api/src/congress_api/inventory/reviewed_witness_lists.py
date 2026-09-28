"""Witness lists read from scanned, single-page official PDFs.

Reviewed against rendered page 1 on 2026-09-28. Exact byte digests restrict each
reading to that document edition. Names are listed witnesses, not attendance.
The source's wording is retained separately from the normalized fields.
"""

REVIEWED = {
    "1e71b980a8979b5f804864a8ba47afa5357ee4ea49d99d1c9da6eba3f60a0525": {
        "url": "https://www.congress.gov/113/meeting/house/101180/documents/HHRG-113-AG16-20130723-SD003.pdf",
        "page": 1,
        "text": "The Honorable Scott D. O’Malia, Commissioner, U.S. Commodity Futures Trading Commission, Washington, DC\nThe Honorable Mark P. Wetjen, Commissioner, U.S. Commodity Futures Trading Commission, Washington, DC",
        "people": [
            {"name": "Scott D. O’Malia", "position": "Commissioner", "organization": "U.S. Commodity Futures Trading Commission, Washington, DC"},
            {"name": "Mark P. Wetjen", "position": "Commissioner", "organization": "U.S. Commodity Futures Trading Commission, Washington, DC"},
        ],
    },
    "665f835e1c345e962131b44956f31901723c54b314ce71e51b7252df340dfaa3": {
        "url": "https://www.congress.gov/114/meeting/house/102865/documents/HHRG-114-SM00-20150225-SD002-U1.pdf",
        "page": 1,
        "text": "The Honorable Maria Contreras-Sweet\nAdministrator\nUnited States Small Business Administration\nWashington, DC",
        "people": [{"name": "Maria Contreras-Sweet", "position": "Administrator", "organization": "United States Small Business Administration, Washington, DC"}],
    },
    "ace2f3fa4c9b324c953716c1f8ec913966acace15fd279134a766585653a5a4c": {
        "url": "https://www.congress.gov/116/meeting/house/109506/documents/HHRG-116-JU00-WList-20190521.pdf",
        "page": 1,
        "text": "Donald F. McGahn, II\nFormer White House Counsel\nOffice of White House Counsel",
        "people": [{"name": "Donald F. McGahn II", "position": "Former White House Counsel", "organization": "Office of White House Counsel"}],
    },
}
