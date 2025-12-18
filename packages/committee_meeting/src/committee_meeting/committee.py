from enum import StrEnum

from sqlmodel import Field, Relationship, SQLModel

from committee_meeting.committee_meeting import CommitteeMeeting


class Chamber(StrEnum):
    senate = "Senate"
    house = "House"


class Committee(SQLModel):
    committee_id: str = Field(default=None, primary_key=True)
    committee_name: str = Field(default=None)
    chamber: Chamber = Field(default=None)
    meetings: list[CommitteeMeeting] = Relationship(back_populates="committee")
