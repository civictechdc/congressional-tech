"""Default writable locations retained for existing commands and library callers.

These locations historically live beside bundled metadata. Keep their exact
values so existing caches and outputs stay discoverable; importing creates nothing.
"""

from .resources import PACKAGE_DIR

DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "data"
DEFAULT_TINYDB_DIR = DEFAULT_OUTPUT_DIR
DEFAULT_YOUTUBE_REPORT_FILE = DEFAULT_OUTPUT_DIR / "youtube_event_id_report.csv"
DEFAULT_GPO_HEARINGS_FILE = DEFAULT_OUTPUT_DIR / "gpo_hearings.csv"
DEFAULT_MEETINGS_FILE = DEFAULT_OUTPUT_DIR / "congress_meetings.jsonl.gz"
DEFAULT_HEARING_VIDEOS_FILE = DEFAULT_OUTPUT_DIR / "gpo_hearing_videos.csv"
DEFAULT_OVERRIDES_FILE = DEFAULT_OUTPUT_DIR / "hearing_video_overrides.csv"
