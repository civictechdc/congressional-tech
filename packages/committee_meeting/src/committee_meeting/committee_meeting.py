from datetime import datetime

from sqlmodel import Field, Relationship, SQLModel

from committee_meeting.committee import Committee


class CommitteeMeeting(SQLModel):
    event_id: str = Field(default=None, primary_key=True)
    event_title: str = Field(default=None)
    committee: Committee = Relationship(back_populates="meetings")
    start_time: datetime = Field(default=None)
    end_time: datetime = Field(default=None)
