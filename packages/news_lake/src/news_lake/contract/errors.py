"""Structured contract failures carrying a rule name and offending record."""


class ContractError(ValueError):
    """Raised for shape or corpus violations.

    Attributes:
        rule: stable rule identifier (e.g. 'duplicate_record_id', 'shape').
        record_id: id of the offending record when known.
        detail: human-readable explanation.
    """

    def __init__(self, rule, detail, record_id=None):
        self.rule = rule
        self.record_id = record_id
        self.detail = detail
        location = f'record {record_id}: ' if record_id is not None else ''
        super().__init__(f'{location}{rule}: {detail}')
