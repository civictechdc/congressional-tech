from corpus_recovery.html import classify_transcripts as classify


def transcript(text):
    return ('<html><title>Committee on Veterans Affairs hearing</title><body>'+text+'</body></html>').encode()


def test_printed_transcript():
    text='HEARING BEFORE HOUSE OF REPRESENTATIVES SERIAL No. 112-11 Printed for the use of the committee '+('testimony ' * 500)
    assert classify(transcript(text))['subtype']=='printed_hearing_transcript'


def test_navigation_is_not_transcript():
    assert classify(transcript('committee hearing '+('navigation ' * 700)))['category']=='empty_document_body'


def test_short_wrapper_is_not_transcript():
    text='HEARING BEFORE HOUSE OF REPRESENTATIVES SERIAL No. 112-11 Printed for the use of the committee'
    assert classify(transcript(text))['category']=='empty_document_body'


def test_challenge_remains_rejected():
    assert classify(b'<html><title>Session Verification</title><body>Wait</body></html>')['category']=='error_or_challenge'
