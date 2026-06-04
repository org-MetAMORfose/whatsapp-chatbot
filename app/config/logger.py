import logging
import sys
from pathlib import Path

from pythonjsonlogger.json import JsonFormatter


def setup_logging(
    level: str = "INFO",
    loki_url: str = "",
    loki_enabled: bool = False,
) -> None:
    root_logger = logging.getLogger()

    if root_logger.handlers:
        return

    root_logger.setLevel(getattr(logging, level.upper()))

    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(message)s %(name)s",
        rename_fields={
            "levelname": "type",
            "message": "msg",
            "asctime": "timestamp",
            "name": "logger",
        },
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "chatbot.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    if loki_enabled and loki_url:
        import queue

        import logging_loki

        loki_handler = logging_loki.LokiQueueHandler(
            queue.Queue(-1),
            url=f"{loki_url}/loki/api/v1/push",
            tags={"app": "whatsapp-chatbot"},
            version="1",
        )
        loki_handler.setFormatter(formatter)
        root_logger.addHandler(loki_handler)
