from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from service.app import create_app
from service.config import Settings
from service.core import Core
from service.hermes import HermesClient
from service.whop import MockWhop

from fakes import WEBHOOK_SECRET, FakeHermes, FakePipeline


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(mock=True, data_dir=tmp_path / "data", public_base_url="http://testserver",
                    app_shared_secret="test-app-key", admin_key="test-admin-key",
                    whop_webhook_secret=WEBHOOK_SECRET, hermes_api_base="http://hermes:8642",
                    hermes_api_key="test-hermes-key", mcp_token="test-mcp-token")


@pytest.fixture
def pipeline() -> FakePipeline:
    return FakePipeline()


@pytest.fixture
def hermes() -> FakeHermes:
    return FakeHermes()


@pytest.fixture
def core(settings, pipeline, hermes) -> Core:
    client = HermesClient(settings.hermes_api_base, settings.hermes_api_key, transport=hermes.transport())
    return Core(settings, pipeline=pipeline, whop=MockWhop("http://testserver"), hermes=client)


@pytest.fixture
def client(core):
    with TestClient(create_app(core, start_monitor=False)) as c:
        yield c
