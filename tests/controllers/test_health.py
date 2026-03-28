"""Tests for the health controller."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.health_controller import router as health_router


@pytest.fixture
def client() -> TestClient:
    """Create a test client with health router."""
    app = FastAPI()
    app.include_router(health_router)
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    """Test the health check endpoint."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
