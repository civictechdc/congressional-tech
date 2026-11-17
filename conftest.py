"""Every pytest session in this checkout tests this checkout's code on the engine it pins.

scripts/dev.py doctor checks the same before a lane, but a direct pytest run skips
doctor: on 2026-11-02 a re-check ran another checkout's .venv/bin/pytest here and
imported that checkout's packages without a word. Lanes with their own config file
(explorer-mcp) have their own rootdir and never load this file.
"""
import importlib.util
import os
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location('_checkout_preflight', Path(__file__).parent / 'scripts/dev.py')
dev = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dev)


def pytest_configure(config):
    # A test of the nightly's failure path must not alert the person at this Mac: notify_failure
    # posts a real "Archive nightly publish" notification unless this is set (2026-11-17: each
    # local run of test_archive_publish_job.py popped one, and read as a nightly failing here).
    os.environ['ARCHIVE_NIGHTLY_NO_MACOS_NOTIFY'] = '1'
    declaration = dev.declaration()
    errors = dev.checkout_errors(declaration)
    for lane, spec in declaration['lanes'].items():
        if os.environ.get(spec.get('required_job_config_env', '')):
            try:
                dev.job_runtime(declaration, lane)
            except ValueError as error:
                errors.append(str(error))
            break
    if errors:
        raise pytest.UsageError('This session would not test this checkout:\n' + '\n'.join(errors))
