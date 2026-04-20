"""Tests for the health controller."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.health_controller import HealthController


@pytest.fixture
def client() -> TestClient:
    """Create a test client with health controller."""
    app = FastAPI()

    health_controller = HealthController()
    app.include_router(health_controller.router)

    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    """Test the health check endpoint."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
