import logging
import os
import sys
from pathlib import Path

from src.config import Config
from src.service import IngestionService


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def main():
    project_root = Path(__file__).resolve().parents[1]
    load_env_file(project_root / ".env")

    config = Config()
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        stream=sys.stdout,
    )
    IngestionService(config).run()


if __name__ == "__main__":
    main()
