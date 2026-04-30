from __future__ import annotations

from fastapi import APIRouter


class HealthController:
    def __init__(self) -> None:
        self.router = APIRouter()
        self._register_routes()

    def _register_routes(self) -> None:
        @self.router.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok"}
