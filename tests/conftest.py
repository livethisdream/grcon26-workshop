import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FIXTURE = os.path.join(ROOT, "fixtures", "m2k-snapshot.json")
REAL = os.path.join(ROOT, "fixtures", "m2k-real.json")


@pytest.fixture(scope="session")
def snapshot():
    with open(FIXTURE) as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def repo_root():
    return ROOT


@pytest.fixture(scope="session")
def real_snapshot():
    """The capture from actual hardware, if it is checked out.

    Skipped rather than required so the suite still runs for someone who
    only has the synthetic fixture.
    """
    if not os.path.exists(REAL):
        pytest.skip("no fixtures/m2k-real.json; capture one with "
                    "iio_discover.py --uri <uri> --json > fixtures/m2k-real.json")
    with open(REAL) as handle:
        return json.load(handle)
