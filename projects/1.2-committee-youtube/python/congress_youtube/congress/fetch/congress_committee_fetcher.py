import os
from tinydb import TinyDB, Query
from tinydb.table import Document
from typing import Literal
from ...globals import DEFAULT_TINYDB_DIR
from ..api import congress_api_get


class CongressCommitteeFetcher:
    """
    Class for managing congressional committee data using the Congress.gov API.
    Attributes:
        api_key (str): API key for accessing Congress.gov data.
        tinydb_dir (str): Directory path for TinyDB database.
        committees_tinydb_path (str): Path to the TinyDB JSON file storing committee data.
        committees_tb (TinyDB.table): TinyDB table for committee data.
    Methods:
        fetch_all_committees(chamber): Retrieve and store committee data by chamber.
    """

    def __init__(self, api_key: str, tinydb_dir: str = DEFAULT_TINYDB_DIR) -> None:
        self.api_key = api_key
        self.tinydb_dir = tinydb_dir

        self.committees_tinydb_path = os.path.join(
            tinydb_dir, "committee-summaries.json"
        )
        self.committees_tb = TinyDB(self.committees_tinydb_path).table("committees")
        print(
            f"Loaded {len(self.committees_tb):d} committees from {os.path.abspath(self.committees_tinydb_path)}"
        )

    def fetch_all_committees(
        self,
        chamber: Literal["house", "senate", "nochamber"] = "house",
    ) -> tuple[list[Document], list[Document]]:
        committees = get_committees(chamber, api_key=self.api_key)["committees"]
        committee_q = Query()
        new_committees = []
        for committee in committees:
            system_code = committee.get("systemCode")
            if not self.committees_tb.contains(committee_q.systemCode == system_code):
                id = self.committees_tb.insert(committee)
                doc = Document(committee, doc_id=id)
                new_committees.append(doc)
        if len(new_committees) > 0:
            print(f"Added {len(new_committees)} new committees.")
        return [self.committees_tb.all(), new_committees]


def get_committees(
    chamber: Literal["house", "senate"] = "house",
    **kwargs,
):
    if chamber not in {"house", "senate"}:
        raise ValueError(
            f"Invalid chamber: {chamber}, must be one of: 'house', 'senate'"
        )
    return congress_api_get(f"committee/{chamber}", **kwargs)
