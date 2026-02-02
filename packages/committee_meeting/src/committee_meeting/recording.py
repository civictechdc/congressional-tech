"""Committee meeting recording models."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from committee_meeting.committee_meeting import CommitteeMeeting
    from committee_meeting.transcript import Transcript


class RecordingType(StrEnum):
    """Source platform for a meeting recording."""

    youtube = "youtube"


class Recording(SQLModel, table=True):
    """A video recording of a committee meeting.

    Attributes:
        recording_id: Unique identifier for the recording.
        type: The platform where the recording is hosted.
        video_id: Platform-specific video identifier.
        video_title: Title of the video as displayed on the platform.
        upload_date: Date the recording was uploaded to the platform.
        meeting_id: Foreign key reference to the associated committee meeting.
        meeting: The committee meeting this recording captures.
        transcripts: List of transcripts generated from this recording.
    """

    recording_id: str = Field(primary_key=True)
    type: RecordingType = Field(default=RecordingType.youtube)
    video_id: str = Field()
    video_title: str = Field()
    upload_date: Optional[datetime] = Field(default=None)
    meeting_id: Optional[str] = Field(default=None, foreign_key="committeemeeting.event_id")
    meeting: Optional["CommitteeMeeting"] = Relationship(back_populates="recordings")
    transcripts: list["Transcript"] = Relationship(back_populates="recording")
