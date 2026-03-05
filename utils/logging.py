from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(level: str, file_path: str) -> None:
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(file_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
