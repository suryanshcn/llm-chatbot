import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway import LLMGateway
from app.main import create_app


@pytest.fixture
def make_client(tmp_path):
    def _make(keys=("k1", "k2"), simulation=True, extra=None):
        settings = Settings(
            api_keys=list(keys), model="gemini/test-model",
            database_url=f"sqlite:///{tmp_path}/t.db",
            allowed_origins=["http://localhost:3000"],
            enable_failure_simulation=simulation,
        )
        gw = LLMGateway(settings.api_keys, settings.model,
                        extra_kwargs=extra or {"mock_response": "Paris is the capital."})
        return TestClient(create_app(settings, gw), raise_server_exceptions=False)
    return _make


@pytest.fixture
def client(make_client):
    return make_client()
