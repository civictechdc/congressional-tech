from .committee_details import CommitteeDetails
from .committee_summary import CommitteeSummary


class Committee:
    summary: CommitteeSummary = None
    details: CommitteeDetails = None
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
        ## bind the summary
        inst.summary = summary
        return inst

    def get_details(self, api_key: str, force_fetch: bool = False):
        if self.details is not None:
            return self.details

        ## will load from the tinydb before fetching
        self.details = CommitteeDetails.from_spec(
            self.summary.chamber, self.summary.systemCode, api_key, force_fetch
        )

        return self.details
