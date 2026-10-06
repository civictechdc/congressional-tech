"""Keep generated diagnostic probes separate from publisher download links."""


PROVENANCE_COLUMNS = ('source_association_basis', 'source_occurrences')


def independent_publisher_link(row):
    """A retained failed capture alone cannot reopen an excluded experiment."""
    return any(row.get('source_url') in (item.get('source_link_url') or []) and
               'generated_xml_probe' not in (item.get('source_association_basis') or [])
               for item in row.get('source_occurrences') or [])


def publisher_download_candidate(row):
    """Admit legacy rows, but require independent links for generated probes.

    Recovery associations can copy a publisher link onto a generated candidate;
    that copied link is not independent evidence for the candidate URL.
    """
    occurrences = row.get('source_occurrences') or []
    generated = 'generated_xml_probe' in (row.get('source_association_basis') or [])
    generated = generated or any(
        'generated_xml_probe' in (item.get('source_association_basis') or [])
        for item in occurrences)
    if not generated:
        return True
    return independent_publisher_link(row)
