from __future__ import annotations

from fastapi import FastAPI

from app.controllers.health_controller import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Metamorfose WhatsApp Chatbot API")
    app.include_router(health_router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"message": "Metamorfose WhatsApp Chatbot API is running"}

    return app


app = create_app()
