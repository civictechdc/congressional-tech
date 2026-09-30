"""Witness lists read from rendered official PDFs with incomplete text parsing.

Reviewed against the indicated rendered pages on 2026-09-28. Exact byte digests restrict each
reading to that document edition. Names are listed witnesses, not attendance.
The source's wording is retained separately from the normalized fields.
"""


REVIEWED = {
    "8a42957a8037431ba5284e79cb3e09531f2b01473d2e5698d4504dd3aabec1d9": {
        "url": "https://www.congress.gov/113/meeting/house/100218/documents/HHRG-113-JU00-20130205-SD002.pdf",
        "page": 1,
        "text": "Panel One\nMr. Vivek Wadhwa\nDirector of Research\nPratt School of Engineering\nDuke University\nMr. Michael Teitelbaum\nSenior Advisor, Alfred P. Sloan Foundation\nWertheim Fellow, Harvard Law School\nDr. Puneet S. Arora, MD MS FACE\nChairman of the Board\nImmigration Voice\nThe Honorable Julian Castro\nMayor of San Antonio, Texas\nPanel Two\nMs. Julie Myers Wood\nPresident,\nGuidepost Solutions LLC\nMr. Chris Crane\nPresident, National Immigration and\nCustoms Enforcement Council 118\nAmerican Federation of Government\nEmployees\nMs. Jessica Vaughan\nDirector of Policy Studies\nCenter for Immigration Studies\nMr. Muzaffar Chishti\nDirector, Migration Policy Institute's Office\nNew York University School of Law",
        "people": [
            {"name": "Vivek Wadhwa", "position": "Director of Research", "organization": "Pratt School of Engineering, Duke University"},
            {"name": "Michael Teitelbaum", "position": "Senior Advisor; Wertheim Fellow", "organization": "Alfred P. Sloan Foundation; Harvard Law School"},
            {"name": "Puneet S. Arora", "position": "Chairman of the Board", "organization": "Immigration Voice"},
            {"name": "Julian Castro", "position": "Mayor of San Antonio, Texas", "organization": ""},
            {"name": "Julie Myers Wood", "position": "President", "organization": "Guidepost Solutions LLC"},
            {"name": "Chris Crane", "position": "President", "organization": "National Immigration and Customs Enforcement Council 118, American Federation of Government Employees"},
            {"name": "Jessica Vaughan", "position": "Director of Policy Studies", "organization": "Center for Immigration Studies"},
            {"name": "Muzaffar Chishti", "position": "Director, Migration Policy Institute's Office", "organization": "New York University School of Law"},
        ],
    },
    "c96bd593842c9462b364f5f50d05647855020a8f35f6b54f74b7e7ea35bb0838": {
        "url": "https://www.congress.gov/113/meeting/house/100266/documents/HHRG-113-II00-20130214-SD002.pdf",
        "page": 1,
        "pages": [1, 2],
        "text": "PANEL I\nTim Spisak\nDeputy Assistant Director\nMinerals and Realty Management\nBureau of Land Management\nDepartment of the Interior\nDaniel Garcia-Diaz\nDirector\nNational Resources and Environment\nU.S. Government Accountability Office\nKimberly Elmore\nAssistant Inspector General for Audits, Inspections, and Evaluations\nU.S. Department of the Interior\nPANEL II\nRodney Morgan\nVP of Procurement\nMicron Technology\nBrad Boersen\nDirector, Strategic Planning & Analysis for Optical Fiber\nCorning Incorporated\nGary Page\nPresident\nHelium & Balloons Across America\nDr. Sam Aronson\nVice President\nAPS Physics\nPANEL III\nDavid Joyner\nPresident\nAir Liquide Helium America, Inc.\nTom Thoman\nDivision President – Gases Production\nAirgas, Inc.\nKevin Lynch\nSr. Vice President\nSpecialty Gases & Helium\nMatheson Tri-Gas\nWalter Nelson\nDirector, Sourcing & Supply Chain\nAir Products and Chemicals, Inc.\nNick Haines\nHead Global Helium Source Development\nLinde North America\nScott Kaltrider\nVP, Business Management and Helium\nPraxair, Inc.",
        "people": [
            {"name": "Tim Spisak", "position": "Deputy Assistant Director", "organization": "Minerals and Realty Management, Bureau of Land Management, Department of the Interior"},
            {"name": "Daniel Garcia-Diaz", "position": "Director", "organization": "National Resources and Environment, U.S. Government Accountability Office"},
            {"name": "Kimberly Elmore", "position": "Assistant Inspector General for Audits, Inspections, and Evaluations", "organization": "U.S. Department of the Interior"},
            {"name": "Rodney Morgan", "position": "VP of Procurement", "organization": "Micron Technology"},
            {"name": "Brad Boersen", "position": "Director, Strategic Planning & Analysis for Optical Fiber", "organization": "Corning Incorporated"},
            {"name": "Gary Page", "position": "President", "organization": "Helium & Balloons Across America"},
            {"name": "Sam Aronson", "position": "Vice President", "organization": "APS Physics"},
            {"name": "David Joyner", "position": "President", "organization": "Air Liquide Helium America, Inc."},
            {"name": "Tom Thoman", "position": "Division President – Gases Production", "organization": "Airgas, Inc."},
            {"name": "Kevin Lynch", "position": "Sr. Vice President", "organization": "Specialty Gases & Helium, Matheson Tri-Gas"},
            {"name": "Walter Nelson", "position": "Director, Sourcing & Supply Chain", "organization": "Air Products and Chemicals, Inc."},
            {"name": "Nick Haines", "position": "Head Global Helium Source Development", "organization": "Linde North America"},
            {"name": "Scott Kaltrider", "position": "VP, Business Management and Helium", "organization": "Praxair, Inc."},
        ],
    },
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
