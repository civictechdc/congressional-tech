"""Parse publisher legislators data without file or network access."""

from congress_api.models.legislators import LEGISLATORS, Legislator


def parse_legislators(data: str | bytes) -> list[Legislator]:
    return LEGISLATORS.validate_json(data)

