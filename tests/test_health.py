from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from accounts import AccountStore, SCHEMA_VERSION
from health import database_ready
import server


class HealthTests(unittest.TestCase):
    def test_committed_header_write_preserves_data_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'accounts.sqlite3'
            with closing(AccountStore(path)) as store:
                store.connection.execute("INSERT INTO accounts VALUES ('a','code',123)")
                store.connection.commit()
            before = path.read_bytes()
            database_ready(path)
            after = path.read_bytes()
            self.assertNotEqual(before[24:28],after[24:28])  # file change counter
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],SCHEMA_VERSION)
                self.assertEqual(connection.execute('SELECT * FROM accounts').fetchall(),[('a','code',123)])

    def test_health_is_public_and_redacts_write_failure(self):
        for path in ('/healthz','/api/game/health'):
            with self.subTest(path=path), patch('server.AccountStore') as authentication:
                with patch('server.database_ready',side_effect=sqlite3.OperationalError('private database path: disk full')):
                    result = server.app.test_client().get(path)
                self.assertEqual(result.status_code,503)
                self.assertEqual(result.json,{'online':False})
                self.assertNotIn(b'private',result.data)
                with patch('server.database_ready') as readiness:
                    result = server.app.test_client().get(path)
                self.assertEqual(result.status_code,200)
                self.assertEqual(result.json,{'online':True})
                readiness.assert_called_once_with(server.app.config['ACCOUNT_DB'])
                authentication.assert_not_called()
