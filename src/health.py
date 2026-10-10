"""Write-aware SQLite readiness without changing account rows or schema version."""

from contextlib import closing
from pathlib import Path
import sqlite3

from accounts import SCHEMA_VERSION


def database_ready(path):
    # rw refuses to create a missing account DB. This does not run migrations.
    uri = Path(path).resolve().as_uri() + '?mode=rw'
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version != SCHEMA_VERSION:
            raise sqlite3.DatabaseError('Account schema is not ready.')
        # SQLite writes the database header even when the assigned value is
        # unchanged. Commit exercises journal/database writes while preserving
        # all account rows and the schema version. SELECT alone cannot do this.
        connection.execute('PRAGMA user_version=' + str(version))
        connection.commit()
