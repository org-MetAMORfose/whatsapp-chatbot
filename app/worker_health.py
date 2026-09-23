"""Standard-library-only probe to avoid loading another copy of application clients."""
from pathlib import Path
from tempfile import gettempdir
from time import time

HEARTBEAT_FILE = Path(gettempdir()) / "chatbot-worker-heartbeat"


def main() -> None:
    try:
        age = time() - HEARTBEAT_FILE.stat().st_mtime
    except FileNotFoundError:
        raise SystemExit(1) from None
    if age > 30:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
