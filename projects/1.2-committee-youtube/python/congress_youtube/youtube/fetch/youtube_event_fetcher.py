import logging
from typing import List
from tinydb import TinyDB, where
from tinydb.table import Table
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


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
        self, youtube_api_key: str, record_path: str = "congress_youtube_db.json"
    ):
        """
        Initialize the YouTube API client with the provided API key.

        Args:
            youtube_api_key (str): The YouTube Data API key for authentication.
        """
        self.youtube = build(
            self.API_SERVICE_NAME, self.API_VERSION, developerKey=youtube_api_key
        )

        self.record_path = record_path

        self.videos_tbs = {}
        self.channels_tb = TinyDB(self.record_path).table("youtube_channels")

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
                raise ValueError(
                    f"{len(search_results)} entries with same channel handle in {self.channels_tb}."
                )

            ## hit the API if our channel isn't in the store
            channel_response = (
                self.youtube.channels()
                .list(part=["snippet", "contentDetails"], forHandle=channel_handle)
                .execute()
            )

            channel_details = channel_response["items"][0]

            ## store the channel details
            self.store_channel(channel_handle, channel_details)

            return channel_details

        except (HttpError, IndexError) as ex:
            logging.error(ex)

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
        videos_tb = TinyDB(self.record_path).table(f"youtube_videos_{channel_handle}")

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
            print(f"Fetch {fetches} of {int(total_results // 50 + 1)}.")

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
        print(f"All done! Fetched {fetches * 50} videos, added {added}.")


def parse_channel_details(channel_details: dict) -> dict:
    """Extract relevant details from channel API response"""
    uploads = channel_details["contentDetails"]["relatedPlaylists"]["uploads"]

    channel_data = {
        key: channel_details["snippet"][key]
        for key in ["title", "description", "publishedAt", "customUrl"]
    }
    channel_data["uploads"] = uploads

    return channel_data


def insert_videos_into_tb(items: List[dict], videos_tb: Table) -> bool:
    break_flag = False
    added = 0

    ## insert each item OR determine if we should leave the loop
    for item in items:
        doc = parse_video_details(item)
        search_results = videos_tb.search(where("videoId") == doc["videoId"])
        ## break if we've already processed up until this point
        if len(search_results) > 0:
            print(f"{doc['videoId']} already exists in {videos_tb}.")
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
