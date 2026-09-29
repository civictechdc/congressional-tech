"""Published bill type/version vocabulary; retain unlisted source tokens.

Source: https://www.govinfo.gov/help/bills (checked 2026-09-29).
The page calls its version table common versions, not an exhaustive validity list.
A version describes a text edition; its chamber need not be the bill origin.
"""

BILLS_HELP_URL = "https://www.govinfo.gov/help/bills"
BILLS_HELP_CHECKED_ON = "2026-09-29"

BILL_TYPES = {
    'hr': 'House Bill',
    's': 'Senate Bill',
    'hjres': 'House Joint Resolution',
    'sjres': 'Senate Joint Resolution',
    'hconres': 'House Concurrent Resolution',
    'sconres': 'Senate Concurrent Resolution',
    'hres': 'House Simple Resolution',
    'sres': 'Senate Simple Resolution',
}

BILL_VERSIONS = {
    'as': 'Amendment (Senate)',
    'ash': 'Additional Sponsors (House)',
    'ath': 'Agreed to (House)',
    'ats': 'Agreed to (Senate)',
    'cdh': 'Committee Discharged (House)',
    'cds': 'Committee Discharged (Senate)',
    'cph': 'Considered and Passed (House)',
    'cps': 'Considered and Passed (Senate)',
    'eah': 'Engrossed Amendment (House)',
    'eas': 'Engrossed Amendment (Senate)',
    'eh': 'Engrossed (House)',
    'enr': 'Enrolled',
    'eph': 'Engrossed and Deemed Passed by House',
    'es': 'Engrossed (Senate)',
    'fah': 'Failed Amendment (House)',
    'fph': 'Failed Passage (House)',
    'fps': 'Failed Passage (Senate)',
    'hdh': 'Held at Desk (House)',
    'hds': 'Held at Desk (Senate)',
    'ih': 'Introduced (House)',
    'iph': 'Indefinitely Postponed (House)',
    'ips': 'Indefinitely Postponed (Senate)',
    'is': 'Introduced (Senate)',
    'lth': 'Laid on Table (House)',
    'lts': 'Laid on Table (Senate)',
    'oph': 'Ordered to be Printed (House)',
    'ops': 'Ordered to be Printed (Senate)',
    'pap': 'Printed as Passed',
    'pav': 'Previous Action Vitiated',
    'pch': 'Placed on Calendar (House)',
    'pcs': 'Placed on Calendar (Senate)',
    'pp': 'Public Print',
    'pwah': 'Ordered to be Printed with House Amendment',
    'rah': 'Referred with Amendments (House)',
    'ras': 'Referred with Amendments (Senate)',
    'rch': 'Reference Change (House)',
    'rcs': 'Reference Change (Senate)',
    'rdh': 'Received in (House)',
    'rds': 'Received in (Senate)',
    'reah': 'Re-engrossed Amendment (House)',
    'renr': 'Re-enrolled Bill',
    'res': 'Re-engrossed Amendment (Senate)',
    'rfh': 'Referred in (House)',
    'rfs': 'Referred in (Senate)',
    'rh': 'Reported in (House)',
    'rhuc': 'Returned to House by Unanimous Consent',
    'rih': 'Referral Instructions (House)',
    'ris': 'Referral Instructions (Senate)',
    'rs': 'Reported in (Senate)',
    'rth': 'Referred to Committee (House)',
    'rts': 'Referred to Committee (Senate)',
    'sas': 'Additional Sponsors (Senate)',
    'sc': 'Sponsor Change',
}
