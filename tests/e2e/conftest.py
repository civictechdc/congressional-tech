"""Pytest Configuration and Shared Fixtures for Opaque-Box E2E Test Suite."""

from __future__ import annotations
import sys
from pathlib import Path

# Ensure workspace root is always on sys.path for robust module resolution
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle
from tests.e2e.harness.data_generators import SyntheticDataGenerator


def pytest_configure(config):
    config.addinivalue_line("markers", "tier1: Tier 1 Feature Coverage tests")
    config.addinivalue_line("markers", "tier2: Tier 2 Boundary & Corner Case tests")
    config.addinivalue_line("markers", "tier3: Tier 3 Cross-Feature Combination tests")
    config.addinivalue_line("markers", "tier4: Tier 4 Real-World Application Scenarios")
    config.addinivalue_line("markers", "feature(name): Maps test to PROJECT.md Feature F1-F29")
    config.addinivalue_line("markers", "implementation_defect(ticket, feature, description): Tracks known repo defect under escalation")


@pytest.fixture
def local_r2(tmp_path: Path) -> LocalR2Staging:
    """Provide clean isolated local R2 content-addressed storage staging environment."""
    cas_dir = tmp_path / "staged_r2"
    cas_dir.mkdir(parents=True, exist_ok=True)
    return LocalR2Staging(cas_dir)


@pytest.fixture
def staging_dir(tmp_path: Path) -> Path:
    """Temporary workspace directory for staged Parquet tables."""
    stage = tmp_path / "stage_tables"
    stage.mkdir(parents=True, exist_ok=True)
    return stage


@pytest.fixture
def oracle() -> ParquetOracle:
    """Parquet oracle validator instance."""
    return ParquetOracle()


@pytest.fixture
def generator() -> SyntheticDataGenerator:
    """Synthetic test data generator."""
    return SyntheticDataGenerator()


@pytest.fixture
def pipeline_data_dir() -> Path:
    """Path to real production datasets for Tier 4 scenarios."""
    path = Path("/Users/mikewolfd/Work/pipeline-data")
    if not path.exists():
        pytest.skip(f"Production dataset directory not found: {path}")
    return path


@pytest.fixture
def adoption_inputs_dir() -> Path:
    """Path to incremental updates adoption inputs."""
    path = Path("/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs")
    if not path.exists():
        pytest.skip(f"Adoption inputs directory not found: {path}")
    return path


@pytest.fixture
def docspec_rs_dir() -> Path:
    """Path to native Rust docspec-rs repository."""
    path = Path("/Users/mikewolfd/Work/spicy-stack/docspec-rs")
    if not path.exists():
        pytest.skip(f"docspec-rs repository not found: {path}")
    return path
