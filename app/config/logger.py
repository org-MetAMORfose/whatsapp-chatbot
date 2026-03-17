import logging
import sys
from pathlib import Path


def setup_logging(level: str = "INFO") -> None:
    """
    Configura o sistema de logging para toda a aplicação.
    Deve ser chamado apenas uma vez no entrypoint (main.py).

    Args:
      level: Nível de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Configura o root logger
    root_logger = logging.getLogger()

    # Evita duplicar handlers se já foi configurado
    if root_logger.handlers:
        return

    root_logger.setLevel(getattr(logging, level.upper()))

    # Formato das mensagens
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler para console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Handler para arquivo
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    file_handler = logging.FileHandler(log_dir / "chatbot.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
