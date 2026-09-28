"""Small source-backed corrections; never rewrite retained page assertions."""
DATE_CORRECTIONS = {
    'https://www.drugcaucus.senate.gov/hearings/the-150-billion-drug-market-a-dive-into-the-economics-of-cartels/': {
        'date': '2022-03-02',
        'source_url': 'https://www.drugcaucus.senate.gov/wp-content/uploads/2022/03/113902.pdf',
        'page': '1',
        'quote': 'Wednesday, March 2, 2022',
        'reason': 'The stenographic transcript dates the proceeding March 2; the webpage displays March 4.',
    },
}


def selected_date(url, event):
    return DATE_CORRECTIONS.get(url, {}).get('date') or event['date']
