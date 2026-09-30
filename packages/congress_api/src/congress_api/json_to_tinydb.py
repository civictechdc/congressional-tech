"""Compatibility alias; optional TinyDB exploration lives in congress_api.legacy."""
from importlib import import_module
import sys

if __name__ == "__main__":
    import_module("congress_api.legacy.json_to_tinydb").main()
else:
    sys.modules[__name__] = import_module("congress_api.legacy.json_to_tinydb")
