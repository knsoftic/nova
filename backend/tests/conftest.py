import pytest
from fastapi.testclient import TestClient

from nova.config import Settings
from nova.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as c:
        yield c
