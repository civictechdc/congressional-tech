"""Committee meeting recording models."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from committee_meeting.transcript import Transcript


class RecordingType(StrEnum):
    """Source platform for a meeting recording."""

    youtube = "YouTube"


class Recording(SQLModel, table=True):
    """A video recording of a committee meeting.

    Attributes:
        recording_id: Unique identifier for the recording.
        type: The platform where the recording is hosted.
        video_id: Platform-specific video identifier.
        video_title: Title of the video as displayed on the platform.
        upload_date: Date the recording was uploaded to the platform.
        transcripts: List of transcripts generated from this recording.
    """

    recording_id: str = Field(default=None, primary_key=True)
    type: RecordingType = Field(default=RecordingType.youtube)
    video_id: str = Field(default=None)
    video_title: str = Field(default=None)
    upload_date: datetime = Field(default=None)
    transcripts: list["Transcript"] = Relationship(back_populates="recording")
