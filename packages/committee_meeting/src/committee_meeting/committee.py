"""Congressional committee models."""

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from committee_meeting.committee_meeting import CommitteeMeeting


class Chamber(StrEnum):
    """Congressional chamber designation."""

    senate = "senate"
    house = "house"


class Committee(SQLModel, table=True):
    """A congressional committee.

    Attributes:
        committee_id: Unique identifier for the committee from Congress.gov API
        committee_name: Official name of the committee.
        chamber: The congressional chamber (Senate or House) the committee belongs to.
        meetings: List of meetings held by this committee.
    """

    committee_id: str = Field(primary_key=True)
    committee_name: str = Field()
    chamber: Chamber = Field()
    meetings: list["CommitteeMeeting"] = Relationship(back_populates="committee")
