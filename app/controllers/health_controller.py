from __future__ import annotations

from fastapi import APIRouter, HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError


class HealthController:
    def __init__(self, redis: Redis[str] | None = None) -> None:
        self.router = APIRouter()

        @self.router.get("/health")
        async def health() -> dict[str, str]:
            if redis is not None:
                try:
                    await redis.ping()
                except RedisError as exc:
                    raise HTTPException(status_code=503, detail="Queue unavailable") from exc
            return {"status": "ok"}
