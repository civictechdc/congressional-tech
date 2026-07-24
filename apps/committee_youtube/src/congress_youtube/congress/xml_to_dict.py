import xml.etree.ElementTree as ET


def xml_to_dict(elem):
    # get text if no children
    if not list(elem):
        return elem.text.strip() if elem.text and elem.text.strip() else None

    result = {}
    for child in elem:
        child_data = xml_to_dict(child)

        # group by tag name
        if child.tag in result:
            # convert to list if needed
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(child_data)
        else:
            result[child.tag] = child_data

    return result


def parse_xml_string(xml_str):
    root = ET.fromstring(xml_str)
    return {root.tag: xml_to_dict(root)}
