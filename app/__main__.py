"""HTTP process entry point. Run the worker independently with `app-worker`."""
import uvicorn

from app.config import settings


def main() -> None:
    uvicorn.run("app.api:create_app", factory=True, host="0.0.0.0",  # noqa: S104
                port=settings.WHATSAPP_WEBHOOK_PORT, workers=1, limit_concurrency=8)


if __name__ == "__main__":
    main()
