#!/usr/bin/env python3
"""Synchronize skill copies from their authoritative repository sources."""

import argparse
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
ASSET_PAIRS = (
    ("docs/user_manual_en.md", "skill/references/user_manual.md"),
    ("examples/full_runner_example.py", "skill/assets/full_runner_example.py"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check consistency without writing files"
    )
    args = parser.parse_args()

    # Read every source before writing so a missing source cannot cause a partial sync.
    sources = []
    try:
        for source, destination in ASSET_PAIRS:
            sources.append((source, destination, (REPOSITORY_ROOT / source).read_bytes()))
    except OSError as exc:
        print(f"Cannot read source: {exc}", file=sys.stderr)
        return 1

    failed = False
    for source, destination, data in sources:
        target = REPOSITORY_ROOT / destination
        try:
            # Normalize line endings for cross-platform Git checkouts; preserve all
            # other bytes. Sync mode still writes the exact source bytes.
            current = target.read_bytes() if target.exists() else None
            matches = current is not None and (
                current.replace(b"\r\n", b"\n") == data.replace(b"\r\n", b"\n")
            )
            if args.check:
                if not matches:
                    print(f"Out of sync: {destination} (source: {source})", file=sys.stderr)
                    failed = True
            elif current != data:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                print(f"Synced: {source} -> {destination}")
        except OSError as exc:
            print(f"Cannot process {destination}: {exc}", file=sys.stderr)
            failed = True

    if args.check:
        if failed:
            print("Run: python tools/sync_skill_assets.py", file=sys.stderr)
        else:
            print("Skill assets are in sync.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
