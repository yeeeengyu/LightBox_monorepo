"""Framework-neutral MySQL persistence; existing users and sessions remain valid."""

import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pymysql

from .security import hash_token


class StorageUnavailable(RuntimeError):
    pass


class UsernameAlreadyExists(RuntimeError):
    pass


def _db_config():
    try:
        port = int(os.getenv("MYSQL_PORT", "3306"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError as error:
        raise StorageUnavailable("MYSQL_PORT must be a valid port number") from error
    return {
        "host": os.getenv("MYSQL_HOST"),
        "port": port,
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE"),
        "charset": "utf8mb4",
        "autocommit": True,
        "connect_timeout": 5,
        "read_timeout": 5,
        "write_timeout": 5,
    }


def is_configured() -> bool:
    config = _db_config()
    return all(config.get(key) for key in ("host", "user", "password", "database"))


@contextmanager
def get_connection():
    config = _db_config()
    missing = [key for key in ("host", "user", "password", "database") if not config.get(key)]
    if missing:
        raise StorageUnavailable(f"MySQL is not configured: {', '.join(missing)}")

    connection = None
    try:
        connection = pymysql.connect(**config, cursorclass=pymysql.cursors.DictCursor)
        yield connection
    except pymysql.MySQLError as error:
        # Driver details can contain database internals; keep the public error stable.
        raise StorageUnavailable("MySQL is unavailable") from error
    finally:
        if connection is not None:
            connection.close()


def init_auth_storage() -> None:
    if not is_configured():
        return
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    nickname VARCHAR(50) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT UNSIGNED NOT NULL,
                    token_hash CHAR(64) NOT NULL UNIQUE,
                    expires_at DATETIME NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_auth_sessions_user_id (user_id),
                    INDEX idx_auth_sessions_expires_at (expires_at),
                    CONSTRAINT fk_auth_sessions_user_id
                        FOREIGN KEY (user_id) REFERENCES users(id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )


def public_user(user: dict) -> dict:
    return {"id": user["id"], "username": user["username"], "nickname": user["nickname"]}


def find_user_by_username(username: str):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, nickname, password_hash FROM users WHERE username = %s",
                (username,),
            )
            return cursor.fetchone()


def create_user(username: str, nickname: str, password_hash: str) -> dict:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    "INSERT INTO users (username, nickname, password_hash) VALUES (%s, %s, %s)",
                    (username, nickname, password_hash),
                )
            except pymysql.IntegrityError as error:
                if error.args and error.args[0] == 1062:
                    raise UsernameAlreadyExists() from error
                raise
            cursor.execute("SELECT id, username, nickname FROM users WHERE id = LAST_INSERT_ID()")
            return cursor.fetchone()


def create_session(user_id: int, token: str) -> datetime:
    try:
        expire_days = int(os.getenv("AUTH_TOKEN_EXPIRE_DAYS", "7"))
        if expire_days <= 0:
            raise ValueError
        expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
    except (ValueError, OverflowError) as error:
        raise StorageUnavailable("AUTH_TOKEN_EXPIRE_DAYS must be a positive number of days") from error

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO auth_sessions (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (user_id, hash_token(token), expires_at.replace(tzinfo=None)),
            )
    return expires_at


def get_user_by_token(token: str):
    token_digest = hash_token(token)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT users.id, users.username, users.nickname
                FROM auth_sessions
                JOIN users ON users.id = auth_sessions.user_id
                WHERE auth_sessions.token_hash = %s
                  AND auth_sessions.expires_at > %s
                """,
                (token_digest, now),
            )
            return cursor.fetchone()


def delete_session(token: str) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM auth_sessions WHERE token_hash = %s",
                (hash_token(token),),
            )


def delete_expired_sessions() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM auth_sessions WHERE expires_at <= %s", (now,))
