"""Committee meeting models."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from committee_meeting.committee import Committee


class CommitteeMeeting(SQLModel, table=True):
    """A scheduled or completed committee meeting.

    Attributes:
        event_id: Unique identifier for the meeting event from Congress.gov API
        event_title: Title or subject of the meeting.
        start_time: Scheduled start time of the meeting.
        end_time: Scheduled or actual end time of the meeting.
        committee_id: Foreign key reference to the parent committee.
        committee: The committee that held this meeting.
    """

    event_id: str = Field(default=None, primary_key=True)
    event_title: str = Field(default=None)
    start_time: datetime = Field(default=None)
    end_time: datetime = Field(default=None)

    committee_id: Optional[str] = Field(default=None, foreign_key="committee.committee_id")
    committee: Optional["Committee"] = Relationship(back_populates="meetings")
