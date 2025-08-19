import logging
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

    API_SERVICE_NAME = 'youtube'
    API_VERSION = 'v3'

    def __init__(self, youtube_api_key: str):
        """
        Initialize the YouTube API client with the provided API key.

        Args:
            youtube_api_key (str): The YouTube Data API key for authentication.
        """
        self.youtube = build(self.API_SERVICE_NAME, self.API_VERSION, developerKey=youtube_api_key)

    def get_event(self, title: str, channel_id: str | None = None) -> dict | None:
        """
        Search for a YouTube video by title and optional channel ID.

        Args:
            title (str): The video title to search for.
            channel_id (str, optional): The channel ID to limit the search to.

        Returns:
            dict | None: The first search result item, or None if an error occurs.
        """

        try:
            search_response = self.youtube.search().list(
                q=title,
                part="snippet",
                channelId=channel_id,
                maxResults=1
            ).execute()

            return search_response["items"][0]
        except (HttpError, IndexError) as ex:
            logging.error(ex)
            return None

    def get_channel(self, handle: str) -> dict | None:
        """
        Retrieve channel information by handle.

        Args:
            handle (str): The YouTube channel handle (e.g., @HouseAppropriationsCommittee).

        Returns:
            dict | None: The channel information, or None if an error occurs.
        """

        try:
            channel_response = self.youtube.channels().list(
                part="snippet",
                forHandle=handle
            ).execute()

            return channel_response["items"][0]
        except (HttpError, IndexError) as ex:
            logging.error(ex)
