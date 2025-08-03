from ...auth import load_youtube_api_key
from .youtube_event_fetcher import YoutubeEventFetcher


def main():
    fetcher = YoutubeEventFetcher()
    api_key = load_youtube_api_key()


if __name__ == "__main__":
    main()
