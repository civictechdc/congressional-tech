"""Common validation behavior for records owned by upstream publishers."""

from pydantic import BaseModel, ConfigDict, model_validator


class SourceModel(BaseModel):
    """Validate known fields without discarding new publisher fields.

    Keep source dates, identifiers and URLs as strings where supplied as strings.
    Unknown enum values are source data, not validation errors. ``source_dict``
    preserves omitted fields and explicit nulls when writing existing JSON shapes.
    """

    model_config = ConfigDict(extra="allow", strict=True, validate_by_alias=True, validate_by_name=False)

    @model_validator(mode="wrap")
    @classmethod
    def preserve_alias_presence(cls, value, handler):
        result = handler(value)
        if isinstance(value, dict):
            for name, field in cls.model_fields.items():
                # Pydantic includes colliding extra names in fields_set. Without
                # this, an unrelated publisher key can fabricate an absent alias.
                if field.alias and field.alias != name and name in value and field.alias not in value:
                    result.__pydantic_fields_set__.discard(name)
        return result

    def source_dict(self) -> dict:
        return self.model_dump(mode="json", by_alias=True, exclude_unset=True)
