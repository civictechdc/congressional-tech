import logging
import re

from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pathlib import Path
from tinydb import where
from tinydb.table import Table

from youtube_api.tables import open_tinydb_for_committee

## re-check videos without captions for this long after publishing
CAPTION_RECHECK_DAYS = 30


class YoutubeEventFetcher:
    """
    A utility class for retrieving YouTube video and channel data using the YouTube Data API.

    Attributes:
        youtube: The YouTube API service client.

    Methods:
        get_event(): Search for a YouTube video by title and optional channel ID.
        get_channel(): Retrieve channel information by handle.
    """

    API_SERVICE_NAME = "youtube"
    API_VERSION = "v3"

    videos_tbs = {}
    channels_tb: Table = None
    force = False

    def __init__(
        self,
        youtube_api_key: str,
        committee_index: int,
        csv_path: Path,
        tinydb_dir: Path,
    ):
        """
        Initialize the YouTube API client with the provided API key.

        Args:
            youtube_api_key (str): The YouTube Data API key for authentication.
        """
        self.youtube = build(
            self.API_SERVICE_NAME, self.API_VERSION, developerKey=youtube_api_key
        )

        self.tinydb = open_tinydb_for_committee(
            committee_name_or_index=committee_index,
            csv_path=csv_path,
            tinydb_dir=tinydb_dir,
        )

        self.videos_tbs = {}
        self.channels_tb = self.tinydb.table("youtube_channels")

    def get_channel(self, channel_handle: str) -> dict | None:
        """
        Retrieve channel information by handle.

        Args:
            handle (str): The YouTube channel handle (e.g., @HouseAppropriationsCommittee).

        Returns:
            dict | None: The channel information, or None if an error occurs.

            channel item:
            ------------
            {
                "kind": "youtube#channel",
                "etag": "EqDBuiF5LKk8DQMOvFZiVdu1Nfs",
                "id": "UCMaSlF09S0fpoRshS2t_7XA",
                "snippet": {
                    "title": "House Appropriations Committee",
                    "description": "The official YouTube channel for the House Appropriations Committee, led by Chairman Tom Cole. ",
                    "customUrl": "@houseappropriationscommittee",
                    "publishedAt": "2011-05-19T17:22:33Z",
                    "thumbnails": {
                        "default": { "url", "width", "height" },
                        "medium": { ... },
                        "high": { ... }
                    },
                    "localized": {
                        "title": "House Appropriations Committee",
                        "description": "The official YouTube channel for the House Appropriations Committee, led by Chairman Tom Cole. "
                    }
                },
                "contentDetails": {
                    "relatedPlaylists": {
                        "likes": "",
                        "uploads": "UUMaSlF09S0fpoRshS2t_7XA"
                    }
                }
            }
        """
        try:
            search_results = self.channels_tb.search(where("handle") == channel_handle)

            ## check if we've already stored this channel
            if len(search_results) == 1:
                return search_results[0]
            elif len(search_results) > 1:
                if self.force:
                    self.channels_tb.truncate()
                else:
                    raise ValueError(
                        f"{len(search_results)} entries with same channel handle in {self.channels_tb}."
                    )

            ## hit the API if our channel isn't in the store
            channel_response = (
                self.youtube.channels()
                .list(part=["snippet", "contentDetails"], forHandle=channel_handle)
                .execute()
            )

            ## a handle that doesn't exist returns no "items" key at all
            channel_details = channel_response.get("items", [])[0]

            ## store the channel details
            self.store_channel(channel_handle, channel_details)

            return channel_details

        except (HttpError, IndexError) as ex:
            logging.error(f"Could not fetch channel {channel_handle}: {ex!r}")

    def store_channel(self, channel_handle: str, channel_details: dict) -> None:
        doc = parse_channel_details(channel_details)
        doc["handle"] = channel_handle

        ## insert the channel
        self.channels_tb.insert(doc)

    def get_all_channel_videos(self, channel_handle: str) -> None:
        """

        playlistItem:
        ------------
        {
            "publishedAt": "2025-07-23T23: 26: 16Z",
            "channelId": "UCMaSlF09S0fpoRshS2t_7XA",
            "title": "Full Committee Markup of FY26 National Security, Department of State, and Related Programs Bill",
            "description": "House Committee on Appropriations, Subcommittee on National Security, Department of State\n\n(EventID=118543)",
            "thumbnails": {
                "default": { "url", "width", "height" },
                "medium": { ... },
                "high": { ... },
                "standard": { ... },
                "maxres": { ... }
            },
            "channelTitle": "House Appropriations Committee",
            "playlistId": "UUMaSlF09S0fpoRshS2t_7XA",
            "position": 0,
            "resourceId": { "kind": "youtube#video", "videoId": "lQnpl1K8dVY" },
            "videoOwnerChannelTitle": "House Appropriations Committee",
            "videoOwnerChannelId": "UCMaSlF09S0fpoRshS2t_7XA"
        }

        """
        playlistId = self.channels_tb.search(where("handle") == channel_handle)[0][
            "uploads"
        ]

        ## create a videos table for this channel
        videos_tb = self.tinydb.table(f"youtube_videos_{channel_handle}")

        ## clear the table if we want to force download
        if self.force:
            videos_tb.truncate()

        ## bind it so we can access it later
        self.videos_tbs[channel_handle] = videos_tb

        ## pagination loop
        pageToken = None
        break_flag = False
        fetches = 0
        added = 0
        while True:
            ## get this page's videos
            playlistItemsResponse = (
                self.youtube.playlistItems()
                .list(
                    part="snippet",
                    playlistId=playlistId,
                    maxResults=50,
                    pageToken=pageToken,
                )
                .execute()
            )
            fetches += 1
            total_results = playlistItemsResponse["pageInfo"]["totalResults"]
            logging.info(f"Fetch {fetches} of {int(total_results // 50 + 1)}.")

            break_flag, this_added = insert_videos_into_tb(
                playlistItemsResponse["items"], videos_tb
            )

            added += this_added

            ## if we didn't break on the above loop
            if not break_flag:
                ## check the next page
                pageToken = playlistItemsResponse.get("nextPageToken", None)
                # if we've run out of pages, then break
                break_flag = pageToken is None

            ## exit the loop, we're done!
            if break_flag:
                break
        logging.info(f"All done! Fetched {fetches * 50} videos, added {added}.")

    def update_video_details(self, channel_handle: str) -> bool:
        """
        Record each video's caption flag and duration from videos.list
        (part=contentDetails, 1 quota unit per 50 videos):

        - `caption`: True/False from contentDetails.caption (captions the channel
          uploaded), or None if the API no longer returns the video (deleted/private).
        - `duration`: length in seconds, or None if unavailable. Separates full
          hearings from clips, and flags truncated uploads.

        Checks videos missing either field, plus recent videos that had no captions
        last time, since captions are often added a few days after a hearing.

        Returns False if an API call failed partway (the rest are checked next run).

        videos.list contentDetails item (abridged):
        ------------
        {
            "id": "lQnpl1K8dVY",
            "contentDetails": { "duration": "PT2H3M1S", "caption": "true", ... }
        }
        """
        videos_tb = self.tinydb.table(f"youtube_videos_{channel_handle}")

        recheck_after = (
            datetime.now(timezone.utc) - timedelta(days=CAPTION_RECHECK_DAYS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_check = videos_tb.search(
            ~where("caption").exists()
            | ~where("duration").exists()
            | ((where("caption") == False) & (where("publishedAt") >= recheck_after))  # noqa: E712
        )
        if not to_check:
            return True

        details = {}
        ok = True
        for i in range(0, len(to_check), 50):
            batch = to_check[i : i + 50]
            try:
                response = (
                    self.youtube.videos()
                    .list(
                        part="contentDetails",
                        id=",".join(doc["videoId"] for doc in batch),
                        maxResults=50,
                    )
                    .execute()
                )
            except HttpError as ex:
                ## leave the rest unchecked; next run will pick them up
                logging.error(f"Video details check failed for {channel_handle}: {ex!r}")
                ok = False
                break
            returned = {item["id"]: item["contentDetails"] for item in response.get("items", [])}
            for doc in batch:
                cd = returned.get(doc["videoId"])
                details[doc["videoId"]] = {
                    "caption": (cd.get("caption") == "true") if cd else None,
                    "duration": parse_iso8601_duration(cd.get("duration")) if cd else None,
                }

        ## one DB write for the whole channel
        checked_ids = [doc.doc_id for doc in to_check if doc["videoId"] in details]
        if checked_ids:
            videos_tb.update(lambda doc: doc.update(details[doc["videoId"]]), doc_ids=checked_ids)
        values = list(details.values())
        logging.info(
            f"Checked {len(values)} videos on {channel_handle}:"
            f" {sum(v['caption'] is True for v in values)} with captions,"
            f" {sum(v['caption'] is False for v in values)} without,"
            f" {sum(v['caption'] is None for v in values)} unavailable."
        )
        return ok


def parse_channel_details(channel_details: dict) -> dict:
    """Extract relevant details from channel API response"""
    uploads = channel_details["contentDetails"]["relatedPlaylists"]["uploads"]

    channel_data = {
        key: channel_details["snippet"][key]
        for key in ["title", "description", "publishedAt", "customUrl"]
    }
    channel_data["uploads"] = uploads

    return channel_data


def insert_videos_into_tb(items: list[dict], videos_tb: Table) -> bool:
    break_flag = False
    added = 0

    ## insert each item OR determine if we should leave the loop
    for item in items:
        doc = parse_video_details(item)
        search_results = videos_tb.search(where("videoId") == doc["videoId"])
        ## break if we've already processed up until this point
        if len(search_results) > 0:
            logging.info(f"{doc['videoId']} already exists in {videos_tb}.")
            break_flag = True
            break
        videos_tb.insert(doc)
        added += 1

    return break_flag, added


def parse_video_details(video_details: dict) -> dict:
    """Extract relevant details from playlistItems API response"""
    video_id = video_details["snippet"]["resourceId"]["videoId"]

    video_data = {
        key: video_details["snippet"][key]
        for key in ["title", "description", "publishedAt"]
    }
    video_data["videoId"] = video_id

    return video_data


def parse_iso8601_duration(value: str | None) -> int | None:
    """'PT2H3M1S' -> 7381 seconds. Upcoming livestreams report 'P0D' -> 0."""
    if not value:
        return None
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value)
    if not m:
        return None
    days, hours, minutes, seconds = (int(g or 0) for g in m.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds
