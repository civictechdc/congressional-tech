from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from committee_meeting.committee import Committee


class CommitteeMeeting(SQLModel, table=True):
    event_id: str = Field(default=None, primary_key=True)
    event_title: str = Field(default=None)
    start_time: datetime = Field(default=None)
    end_time: datetime = Field(default=None)

    committee_id: Optional[str] = Field(default=None, foreign_key="committee.committee_id")
    committee: Optional["Committee"] = Relationship(back_populates="meetings")
