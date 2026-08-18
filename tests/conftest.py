import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FIXTURE = os.path.join(ROOT, "fixtures", "m2k-snapshot.json")


@pytest.fixture(scope="session")
def snapshot():
    with open(FIXTURE) as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def repo_root():
    return ROOT
