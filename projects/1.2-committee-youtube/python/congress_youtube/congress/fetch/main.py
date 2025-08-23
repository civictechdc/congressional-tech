from ...auth import load_congress_api_key
from .congress_event_fetcher import CongressEventFetcher


def main():
    api_key = load_congress_api_key()
    fetcher = CongressEventFetcher()
    fetcher.fetch_event_list(api_key, "house")
    fetcher.process_events(api_key)


if __name__ == "__main__":
    main()
