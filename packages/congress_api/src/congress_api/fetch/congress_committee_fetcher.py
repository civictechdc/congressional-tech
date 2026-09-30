"""Compatibility alias; optional TinyDB exploration lives in congress_api.legacy."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("congress_api.legacy.fetch.congress_committee_fetcher")
