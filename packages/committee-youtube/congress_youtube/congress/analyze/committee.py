from tinydb import TinyDB

from .committee_details import CommitteeDetails
from .committee_summary import CommitteeSummary
from ...youtube.tables import (
    map_system_code_committee_handles,
    open_tinydb_for_committee,
)


class Committee:
    summary: CommitteeSummary = None
    details: CommitteeDetails = None
    youtube: TinyDB = None
    events: list

    def __init__(self):
        ## initialize an empty list for events to be bound to this committee
        self.events = []

    def __repr__(self):
        return f"Committee({self.summary.name}, {self.summary.systemCode}, details={self.details is not None}, events={len(self.events)})"

    @classmethod
    def from_summary(cls, summary: CommitteeSummary):
        ## TODO: replace chamber with validation and Literal; should extract that...
        inst = cls()
        youtube_channel_meta_mapper = map_system_code_committee_handles()
        ## bind the summary
        inst.summary = summary
        systemCode = (
            inst.summary.systemCode
            if inst.summary.parent is None
            else inst.summary.parent.systemCode
        )
        try:
            inst.youtube = open_tinydb_for_committee(
                youtube_channel_meta_mapper[systemCode]["name"],
                assert_exists=True,
            )
        except KeyError:
            print(f"No YouTube channel found for {inst.summary.systemCode}")
        return inst

    def get_details(self, api_key: str, force_fetch: bool = False):
        if self.details is not None:
            return self.details

        ## will load from the tinydb before fetching
        self.details = CommitteeDetails.from_spec(
            self.summary.chamber, self.summary.systemCode, api_key, force_fetch
        )

        return self.details
