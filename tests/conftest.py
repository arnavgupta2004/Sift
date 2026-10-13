import os
import sys
from pathlib import Path

import pytest

os.environ["SIFT_AUTO_INDEX"] = "0"  # tests never start the whole-laptop indexer

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.db import DEFAULT_DB_PATH as DB_PATH  # noqa: E402  (honors SIFT_DATA_DIR)


@pytest.fixture(scope="session", autouse=True)
def _require_synthetic_data():
    if not DB_PATH.exists():
        pytest.exit(
            f"{DB_PATH} not found. Run `python data/generate_synthetic_data.py` "
            "(with the same SIFT_DATA_DIR, if you set one) before running tests — the retrieval/personalization suites are "
            "integration tests against the generated corpus, not isolated unit fixtures."
        )
