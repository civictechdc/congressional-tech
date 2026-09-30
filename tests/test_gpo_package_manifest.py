"""Real package manifests expose files omitted from their MODS locations."""
from pathlib import Path

import pytest
from congress_api.models.gpo import GpoPackageManifest
from congress_api.parsers.gpo import parse_package_manifest


@pytest.mark.parametrize(('package', 'filename'), [
    ('CHRG-116hhrg43625', 'CHRG-116hhrg43625-add2'),
    ('CHRG-117jhrg54192', 'CHRG-117hhrg54192'),
])
def test_real_package_filenames_survive_without_package_name_assumptions(package, filename):
    raw = (Path(__file__).parent / 'fixtures/gpo_metadata/package_manifests' / f'{package}-dip.xml').read_bytes()
    source = parse_package_manifest(raw)
    assert source.attributes['OBJID'] == package
    assert [file.attributes['MIMETYPE'] for file in source.files] == ['text/html', 'application/pdf']
    assert [location.href for location in source.files[0].locations] == [
        f'file://html/{filename}.htm',
        f'https://www.govinfo.gov/content/pkg/{package}/html/{filename}.htm',
    ]
    assert source.files[1].locations[1].href == f'https://www.govinfo.gov/content/pkg/{package}/pdf/{filename}.pdf'
    restored = GpoPackageManifest.model_validate_json(source.model_dump_json())
    assert restored.content.body_bytes() == raw
    assert restored.xml == source.xml
    # Published manifest sizes remain source strings, even when a later captured
    # HTML file has a different length.
    assert isinstance(restored.files[0].attributes['SIZE'], str)


def test_rejects_html_error_response():
    with pytest.raises(ValueError, match='not a METS'):
        parse_package_manifest(b'<html><body>Error</body></html>')
