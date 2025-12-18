from datetime import datetime
from enum import StrEnum

from sqlmodel import Field, Relationship, SQLModel

from committee_meeting.recording import Recording


class TranscriptSource(StrEnum):
    automated = "automated"
    youtube = "youtube"
    official = "official"


class Transcript(SQLModel):
    transcript_id: str = Field(default=None, primary_key=True)
    recording: Recording = Relationship(back_populates="transcripts")
    transcript_url: str = Field(default=None)
    created_date: datetime = Field(default=None)
    source: TranscriptSource = Field(default=None)
