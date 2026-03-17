from __future__ import annotations

import uvicorn
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


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104


if __name__ == "__main__":
    main()
