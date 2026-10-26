import logging
import re

from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pathlib import Path
from tinydb import where
from tinydb.table import Table

from youtube_api.models import (
    YoutubeChannelItem,
    YoutubePlaylistItem,
    YoutubeVideoItem,
)
from youtube_api.tables import get_channel_id_overrides, open_tinydb_for_committee

## re-check videos without captions for this long after publishing
CAPTION_RECHECK_DAYS = 30
METADATA_VERSION = 1
METADATA_RECHECK_DAYS = 30


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def observation(item):
    return {"retrieved_at": timestamp(), "item": item}


class YoutubeEventFetcher:
    """
    A utility class for retrieving YouTube video and channel data using the YouTube Data API.

    Attributes:
        youtube: The YouTube API service client.

    Methods:
        get_channel(): Retrieve channel information by handle.
    """

    API_SERVICE_NAME = "youtube"
    API_VERSION = "v3"

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

        self.channels_tb = self.tinydb.table("youtube_channels")
        self.channel_ids = get_channel_id_overrides(csv_path)

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
        search_results = self.channels_tb.search(where("handle") == channel_handle)

        ## Refresh retained channel metadata once per run.
        if len(search_results) > 1 and not self.force:
            raise ValueError(
                f"{len(search_results)} entries with same channel handle in {self.channels_tb}."
            )

        # Some official handles stop resolving while the channel ID still works.
        # Keep the configured handle as the cache key so prior videos stay attached.
        channel_id = self.channel_ids.get(channel_handle)
        lookup = {"id": channel_id} if channel_id else {"forHandle": channel_handle}

        ## Keep the complete current item, including channel ID and thumbnails.
        channel_response = (
            self.youtube.channels()
            .list(part=["snippet", "contentDetails"], **lookup)
            .execute()
        )

        items = channel_response.get("items", [])
        if not items:
            return None

        channel_details = items[0]
        if channel_id and channel_details["id"] != channel_id:
            raise ValueError("Returned YouTube channel does not match configured channel ID")

        ## store the channel details
        self.store_channel(channel_handle, channel_details)

        return channel_details

    def store_channel(self, channel_handle: str, channel_details: dict) -> None:
        doc = parse_channel_details(channel_details)
        doc["handle"] = channel_handle

        previous = self.channels_tb.search(where("handle") == channel_handle)
        if not previous or previous[0].get("uploads") != doc["uploads"]:
            doc["uploads_scan_complete"] = False
        self.channels_tb.upsert(doc, where("handle") == channel_handle)

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
        channel = self.channels_tb.search(where("handle") == channel_handle)[0]
        playlistId = channel["uploads"]
        allow_overlap_stop = channel.get("uploads_scan_complete") is True and not self.force
        # An interrupted scan must not mistake its own partial writes for an
        # already complete overlap on the next run. Replaying from page one is safe.
        self.channels_tb.update({"uploads_scan_complete": False}, where("handle") == channel_handle)

        ## create a videos table for this channel
        videos_tb = self.tinydb.table(f"youtube_videos_{channel_handle}")

        # A forced scan refreshes every page while retaining previously captured
        # records. Missing playlist entries and request failures are not deletion.

        ## pagination loop
        pageToken = None
        break_flag = False
        fetches = 0
        added = 0
        while True:
            ## get this page's videos
            try:
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
            except HttpError as ex:
                ## a channel with no public uploads has no uploads playlist at all
                if ex.resp.status == 404 and pageToken is None:
                    logging.warning(f"{channel_handle} has no public uploads.")
                    return
                raise
            fetches += 1
            total_results = playlistItemsResponse["pageInfo"]["totalResults"]
            logging.info(f"Fetch {fetches} of {int(total_results // 50 + 1)}.")

            overlap, this_added = insert_videos_into_tb(
                playlistItemsResponse["items"], videos_tb
            )
            break_flag = overlap and allow_overlap_stop

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
        self.channels_tb.update({"uploads_scan_complete": True}, where("handle") == channel_handle)
        logging.info(f"All done! Fetched {fetches} pages, added {added} videos.")

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
        metadata_before = (datetime.now(timezone.utc) - timedelta(days=METADATA_RECHECK_DAYS)).isoformat()
        to_check = videos_tb.search(
            ~where("metadata_version").exists()
            | (where("metadata_version") != METADATA_VERSION)
            | (where("details_checked_at") < metadata_before)
            | ~where("caption").exists()
            | ~where("duration").exists()
            | ((where("caption") == False) & (where("publishedAt") >= recheck_after))  # noqa: E712
        )
        if self.force:
            to_check = videos_tb.all()
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
                        part="snippet,contentDetails,status,liveStreamingDetails",
                        id=",".join(doc["videoId"] for doc in batch),
                        maxResults=50,
                    )
                    .execute()
                )
            except HttpError as ex:
                ## leave the rest unchecked; next run will pick them up
                logging.error(f"Video details check failed for {channel_handle}: {type(ex).__name__}")
                ok = False
                break
            returned = {
                item["id"]: YoutubeVideoItem.model_validate(item).source_dict()
                for item in response.get("items", [])
            }
            checked_at = timestamp()
            for doc in batch:
                item = returned.get(doc["videoId"])
                cd = item.get("contentDetails", {}) if item else {}
                upstream = dict(doc.get("upstream") or {})
                # Keep the last returned item when a later check omits the video.
                # Unavailability is a separate observation, not an empty replacement.
                if item is not None:
                    upstream["video"] = {"retrieved_at": checked_at, "item": item}
                values = {
                    "caption": {"true": True, "false": False}.get(cd.get("caption")),
                    "duration": parse_iso8601_duration(cd.get("duration")),
                    "upstream": upstream, "details_checked_at": checked_at,
                    "metadata_version": METADATA_VERSION, "available": item is not None,
                }
                if item is not None:
                    snippet = item.get("snippet", {})
                    values.update({key: snippet[key] for key in ("title", "description", "channelId", "channelTitle") if key in snippet})
                    if snippet.get("publishedAt"):
                        values["videoPublishedAt"] = snippet["publishedAt"]
                details[doc["videoId"]] = values
            # Save each completed API batch before requesting the next one.
            # A transport failure or interrupted process must not discard it.
            videos_tb.update(lambda doc: doc.update(details[doc["videoId"]]),
                             doc_ids=[doc.doc_id for doc in batch])
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
    validated = YoutubeChannelItem.model_validate(channel_details).source_dict()
    uploads = validated["contentDetails"]["relatedPlaylists"]["uploads"]

    channel_data = {
        key: validated["snippet"][key]
        for key in ["title", "description", "publishedAt", "customUrl"]
        if key in validated["snippet"]
    }
    channel_data["uploads"] = uploads
    channel_data["channelId"] = validated["id"]
    channel_data["upstream"] = observation(validated)

    return channel_data


def insert_videos_into_tb(items: list[dict], videos_tb: Table) -> tuple[bool, int]:
    existing = {}
    for row in videos_tb.all():
        existing.setdefault(row["videoId"], []).append(row.doc_id)
    incoming = {doc["videoId"]: doc for doc in map(parse_video_details, items)}
    overlapping = incoming.keys() & existing.keys()
    if overlapping:
        def refresh(previous):
            value = incoming[previous["videoId"]]
            upstream = {**previous.get("upstream", {}), **value["upstream"]}
            previous.update({**value, "upstream": upstream})
        videos_tb.update(refresh, doc_ids=[id for video in overlapping for id in existing[video]])
    added = [doc for video, doc in incoming.items() if video not in existing]
    if added:
        videos_tb.insert_multiple(added)
    return bool(overlapping), len(added)


def parse_video_details(video_details: dict) -> dict:
    """Extract relevant details from playlistItems API response"""
    validated = YoutubePlaylistItem.model_validate(video_details).source_dict()
    video_id = validated["snippet"]["resourceId"]["videoId"]

    video_data = {
        key: validated["snippet"][key]
        for key in ["title", "description", "publishedAt"]
    }
    video_data["videoId"] = video_id
    video_data["upstream"] = {"playlist_item": observation(validated)}

    return video_data


def parse_iso8601_duration(value: str | None) -> int | None:
    """'PT2H3M1S' -> 7381 seconds. 'P1DT2H' -> 93600 seconds. Upcoming livestreams report 'P0D' -> 0."""
    if not value or not isinstance(value, str):
        return None
    m = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value)
    if not m or not any(m.groups()):
        return None
    weeks, days, hours, minutes, seconds = (int(g or 0) for g in m.groups())
    return (((weeks * 7 + days) * 24 + hours) * 60 + minutes) * 60 + seconds
