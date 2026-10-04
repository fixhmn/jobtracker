import argparse
import sqlite3
from pathlib import Path


def backup(source: Path, destination: Path):
    if not source.is_file():
        raise ValueError("Source database does not exist")
    if destination.exists():
        raise ValueError("Destination already exists; choose a new filename")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # SQLite's backup API includes committed WAL data, unlike copying just the .db file.
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as copy:
            original.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")


def main():
    parser = argparse.ArgumentParser(description="Create a consistent SQLite backup")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        backup(args.source, args.destination)
    except (ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    print(f"Backup created: {args.destination}")


if __name__ == "__main__":
    main()
