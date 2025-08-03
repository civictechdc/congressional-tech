from ..auth import load_api_key
from .congress_event_fetcher import CongressEventFetcher


def main():
    api_key = load_api_key()
    fetcher = CongressEventFetcher()

    ## if we haven't recorded any events, let's go ahead and do that
    ##  first
    if len(fetcher.events.keys()) == 0:
        fetcher.get_all_events(api_key, "house")
        fetcher.dump()

    try:
        fetcher.process_events(api_key)
    except Exception as e:
        raise e
    finally:
        ## overwrite whatever is on disk with wherever we got
        fetcher.dump()


if __name__ == "__main__":
    main()
