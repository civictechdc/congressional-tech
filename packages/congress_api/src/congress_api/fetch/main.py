"""Compatibility alias; optional TinyDB exploration lives in congress_api.legacy."""
from importlib import import_module
import sys

if __name__ == "__main__":
    import_module("congress_api.legacy.fetch.main").parse_args_and_run()
else:
    sys.modules[__name__] = import_module("congress_api.legacy.fetch.main")
