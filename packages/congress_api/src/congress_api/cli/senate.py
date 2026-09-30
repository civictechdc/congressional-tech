"""Collect Senate/joint committee pages and retain replayable parsed source data.

Discovery reads official hearing listings on the supported sites. The default
boundary is June 2019. An earlier --since requires an explicit --site scope;
that boundary and the latest collection date remain in each site's state.
WordPress event dates rank listings when available. Publication dates are only
ranking hints, never evidence of a proceeding's date.

Page associations use the page's own date and at least half the native title's
rarity-weighted subject. Shared menu lines and files are excluded from matching;
ambiguous ties remain unlinked. Existing associations survive changes in rarity
weights unless a newly explicit event date contradicts the native record.

Recognized official event headers retain their title, date and type, so an
unmatched official proceeding can later be admitted under its own URL identity.
Same-day native candidates are retained even after a partial collection failure
and prevent accidental duplicate admission. Indian Affairs and Drug Caucus use
all native statuses for matching; other sites keep their established population.

Witness parsing covers the seven retained layouts, including Jet h3/h4 names and
paragraph roles. Explicit Drug Caucus attachment pages are followed to their
reported files; original landing URLs and anchor labels remain in state. Files
are discovered, not downloaded. Every request has an actual receipt, separate
from the scheduling day. Failures keep the last usable page.

State contains complete captured HTML/JSON bodies alongside typed page evidence,
listings, associations and request outcomes. It is checkpointed every 25 pages.
CSV files are views of those same saved associations. --seed-cache imports existing research pages read-only.
"""

import argparse
import datetime as dt

from congress_api.acquisition.senate import main
from congress_api.cli.common import nonnegative, source_args
from congress_api.parsers.senate_page import SITE


def parse_args_and_run():
    p = argparse.ArgumentParser(description=__doc__)
    source_args(p)
    p.add_argument("--refresh-limit", type=nonnegative, default=450)
    p.add_argument("--site", action="append", choices=sorted(SITE.values()), help="limit live fetching to these sites; retain other saved sites")
    p.add_argument("--since", type=dt.date.fromisoformat, help="earliest listing day; before June 2019 requires --site")
    p.add_argument("--limit", type=nonnegative, help="maximum live hearing pages (listings are additional)")
    main(**vars(p.parse_args()))
