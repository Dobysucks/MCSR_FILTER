from __future__ import annotations

import argparse
from pathlib import Path

from .app import run_app
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="MCSR 26.2 Seed Filter")
    default_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "MCSR26SeedFilter"
    parser.add_argument("--workdir", type=Path, default=default_root)
    args = parser.parse_args()
    run_app(args.workdir)


if __name__ == "__main__":
    main()
