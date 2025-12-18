from datetime import datetime
from enum import StrEnum

from sqlmodel import Field, Relationship, SQLModel

from committee_meeting.transcript import Transcript


class RecordingType(StrEnum):
    youtube = "YouTube"


class Recording(SQLModel):
    recording_id: str = Field(default=None, primary_key=True)
    type: RecordingType = Field(default=RecordingType.youtube)
    video_id: str = Field(default=None)
    video_title: str = Field(default=None)
    upload_date: datetime = Field(default=None)
    transcripts: list[Transcript] = Relationship(back_populates="recording")
