import shutil
from pathlib import Path
import pytest


@pytest.fixture(scope="session", autouse=True)
def manage_test_output_environment():
    """
    Ensure output directory exists and cleanup temporary test artifacts after test session.
    """
    root_dir = Path(__file__).resolve().parents[1]
    output_dir = root_dir / "output"
    test_tmp_dir = output_dir / ".test_tmp"

    test_tmp_dir.mkdir(parents=True, exist_ok=True)

    yield

    # Teardown: Clean up all test temporary files under output/.test_tmp
    if test_tmp_dir.exists():
        shutil.rmtree(test_tmp_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolate_cli_tests(request, monkeypatch):
    """
    Isolate CLI unit tests from user-specific local config.json entries.
    """
    if "test_config" not in request.node.nodeid:
        monkeypatch.setattr("utils.utils.read_config", lambda: {})
