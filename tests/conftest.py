from __future__ import annotations

import os
from pathlib import Path

import pytest

TEST_DATABASE_URL = "postgresql+psycopg://pjbank:pjbank_dev_password@localhost:5432/pjbank_test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session", autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def sample_paths():
    if not DATA_DIR.exists():
        pytest.skip("Sample data folder is not present.")
    paths = sorted(path for path in DATA_DIR.iterdir() if path.is_file())
    if not paths:
        pytest.skip("Sample data folder is empty.")
    return paths
