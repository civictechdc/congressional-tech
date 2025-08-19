from tinydb import TinyDB
from tinydb.table import Document
import json


def convert_event_to_document(event_id, event):
    ## i think this is one of the ones where the
    ##  JSON api fails but the XML worked
    if "api-root" in event.keys():
        event = event["api-root"]
    try:
        value = event["committeeMeeting"]
    except Exception as e:
        print(event["api-root"].keys(), e)
        raise e
    return Document(value, doc_id=event_id)


def main():
    db = TinyDB("congress_youtube_db.json")
    print("opening DB")
    committee_meetings_tb = db.table("committee_meetings")
    print("opening json")
    with open("congress_events_output.json", "r") as handle:
        cached_output = json.load(handle)

    print(committee_meetings_tb)
    for event_id, event in cached_output.items():
        if not committee_meetings_tb.contains(doc_id=event_id):
            doc = convert_event_to_document(event_id, event)
            committee_meetings_tb.insert(doc)
    print(committee_meetings_tb)


if __name__ == "__main__":
    main()
