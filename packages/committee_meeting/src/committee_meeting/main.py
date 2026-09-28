"""Print the draft JSON Schema. Does not fetch, migrate or publish any data."""
import json

from .catalog import Catalog


def main():
    schema = Catalog.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    print(json.dumps(schema, indent=2))


if __name__ == "__main__":
    main()
