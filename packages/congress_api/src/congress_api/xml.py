"""Parse source XML, including the UTF-8 BOM docs.house.gov sometimes prefixes."""
import xml.etree.ElementTree as ET

MODS_NS = {"m": "http://www.loc.gov/mods/v3"}


def parse_xml(data):
    return ET.fromstring(data.removeprefix(b"\xef\xbb\xbf") if isinstance(data, bytes) else data.removeprefix("\ufeff"))


def mods_elements(root, tag):
    ## Related-item granules repeat hearing metadata; only the root's extensions count.
    return root.findall(f"m:extension/m:{tag}", MODS_NS)
