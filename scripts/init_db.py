from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import create_all  # noqa: E402

if __name__ == "__main__":
    create_all()
    print("Database tables created.")
