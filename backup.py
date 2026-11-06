#!/usr/bin/env python3
"""Create a consistent SQLite backup without stopping the AAMM server."""
import argparse
from contextlib import closing
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote
import app


def backup(source, destination):
    source, destination = Path(source).expanduser().resolve(), Path(destination).expanduser().resolve()
    if not source.is_file():
        raise ValueError('Source database does not exist')
    if source == destination:
        raise ValueError('Source and destination must be different')
    # Open read-only: a typo must never create an empty source database.
    uri = 'file:' + quote(str(source), safe='/') + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as src:
        if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='opportunities'").fetchone():
            raise ValueError('Source is not an AAMM database')
        # O_EXCL prevents accidental replacement of a previous backup.
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup integrity check failed')
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', help='New backup file; existing files are never overwritten')
    parser.add_argument('--source', default=str(app.DB), help='Source database (default: AAMM_DB or data/aamm.sqlite3)')
    args = parser.parse_args()
    try:
        backup(args.source, args.destination)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print('Backup failed:', exc, file=sys.stderr)
        return 1
    print('Backup created:', args.destination)
    return 0

if __name__ == '__main__':
    sys.exit(main())
