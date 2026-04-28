#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a standalone AgentES executable.")
    parser.add_argument("--name", default="agentes", help="Output executable name.")
    parser.add_argument("--clean", action="store_true", help="Remove build output before building.")
    args = parser.parse_args()

    if args.clean:
        shutil.rmtree(ROOT / "build", ignore_errors=True)
        shutil.rmtree(ROOT / "dist", ignore_errors=True)
        for spec in ROOT.glob("*.spec"):
            spec.unlink()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--onefile",
        "--name",
        args.name,
        "--collect-all",
        "pydantic",
        "--collect-all",
        "typer",
        "--collect-submodules",
        "yaml",
        str(ROOT / "scripts" / "agentes_entry.py"),
    ]
    run(cmd)
    output = ROOT / "dist" / args.name
    print(f"Built {output}")


if __name__ == "__main__":
    main()
