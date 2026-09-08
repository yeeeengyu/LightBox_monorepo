import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pymysql

from auth import security, storage


LEGACY_HASH = (
    "pbkdf2_sha256$120000$MDEyMzQ1Njc4OWFiY2RlZg==$"
    "pVnYjtg7BbTIea0LtsW/0ddvJtdKtkUBqQ/vIaiKLi4="
)
DB_ENV = {
    "MYSQL_HOST": "localhost", "MYSQL_USER": "user", "MYSQL_PASSWORD": "password",
    "MYSQL_DATABASE": "spotipy", "MYSQL_PORT": "3306",
}


class SecurityCompatibilityTests(unittest.TestCase):
    def test_legacy_password_hash_still_verifies(self):
        self.assertTrue(security.verify_password("legacy-password", LEGACY_HASH))
        self.assertFalse(security.verify_password("incorrect", LEGACY_HASH))
        with patch.object(security.secrets, "token_bytes", return_value=b"0123456789abcdef"):
            self.assertEqual(security.hash_password("legacy-password"), LEGACY_HASH)

    def test_corrupted_hash_is_rejected(self):
        for password_hash in (None, "broken", "other$120000$AA==$AA==", LEGACY_HASH.replace("120000", "0"), LEGACY_HASH.replace("120000", "-1"), "pbkdf2_sha256$120000$???$???"):
            with self.subTest(password_hash=password_hash):
                self.assertFalse(security.verify_password("password", password_hash))

    def test_token_hash_remains_sha256(self):
        self.assertEqual(
            security.hash_token("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )


class StorageTests(unittest.TestCase):
    def mocked_connection(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        context = MagicMock()
        context.__enter__.return_value = connection
        return context, cursor

    def test_connect_failure_becomes_framework_neutral_unavailable(self):
        with patch.dict(os.environ, DB_ENV, clear=True):
            with patch.object(pymysql, "connect", side_effect=pymysql.OperationalError(2003, "private host details")):
                with self.assertRaisesRegex(storage.StorageUnavailable, "^MySQL is unavailable$"):
                    with storage.get_connection():
                        self.fail("Connection should not succeed")

    def test_missing_configuration_becomes_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(storage.StorageUnavailable, "MySQL is not configured"):
                with storage.get_connection():
                    self.fail("Connection should not succeed")

    def test_query_failure_becomes_unavailable_and_connection_is_closed(self):
        connection = MagicMock()
        with patch.dict(os.environ, DB_ENV, clear=True):
            with patch.object(pymysql, "connect", return_value=connection):
                with self.assertRaises(storage.StorageUnavailable):
                    with storage.get_connection():
                        raise pymysql.OperationalError(2013, "Lost connection")
        connection.close.assert_called_once_with()

    def test_mysql_duplicate_insert_becomes_username_conflict(self):
        context, cursor = self.mocked_connection()
        cursor.execute.side_effect = pymysql.IntegrityError(1062, "Duplicate username")
        with patch.object(storage, "get_connection", return_value=context):
            with self.assertRaises(storage.UsernameAlreadyExists):
                storage.create_user("tester", "테스터", LEGACY_HASH)

    def test_session_stores_hash_and_naive_utc_expiry(self):
        context, cursor = self.mocked_connection()
        before = datetime.now(timezone.utc)
        with patch.dict(os.environ, {"AUTH_TOKEN_EXPIRE_DAYS": "7"}):
            with patch.object(storage, "get_connection", return_value=context):
                expires_at = storage.create_session(7, "legacy-token")
        after = datetime.now(timezone.utc)
        params = cursor.execute.call_args.args[1]
        self.assertEqual(params[0], 7)
        self.assertEqual(params[1], security.hash_token("legacy-token"))
        self.assertEqual(params[2], expires_at.replace(tzinfo=None))
        self.assertIsNone(params[2].tzinfo)
        self.assertEqual(expires_at.tzinfo, timezone.utc)
        self.assertLessEqual(before + timedelta(days=7), expires_at)
        self.assertLessEqual(expires_at, after + timedelta(days=7))

    def test_session_lookup_excludes_expired_sessions_and_uses_token_hash(self):
        context, cursor = self.mocked_connection()
        cursor.fetchone.return_value = None
        with patch.object(storage, "get_connection", return_value=context):
            self.assertIsNone(storage.get_user_by_token("expired-token"))
        sql, params = cursor.execute.call_args.args
        self.assertIn("auth_sessions.expires_at > %s", sql)
        self.assertEqual(params[0], security.hash_token("expired-token"))
        self.assertIsNone(params[1].tzinfo)

    def test_logout_deletes_by_token_hash(self):
        context, cursor = self.mocked_connection()
        with patch.object(storage, "get_connection", return_value=context):
            storage.delete_session("legacy-token")
        self.assertEqual(cursor.execute.call_args.args[1], (security.hash_token("legacy-token"),))


if __name__ == "__main__":
    unittest.main()
