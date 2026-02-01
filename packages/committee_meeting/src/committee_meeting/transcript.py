from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from committee_meeting.recording import Recording


class TranscriptSource(StrEnum):
    automated = "automated"
    youtube = "youtube"
    official = "official"


class Transcript(SQLModel, table=True):
    transcript_id: str = Field(default=None, primary_key=True)
    transcript_url: str = Field(default=None)
    created_date: datetime = Field(default=None)
    source: TranscriptSource = Field(default=None)

    recording_id: Optional[str] = Field(default=None, foreign_key="recording.recording_id")
    recording: Optional["Recording"] = Relationship(back_populates="transcripts")
