import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app import create_app
from auth import storage
from auth.security import verify_password


LEGACY_HASH = (
    "pbkdf2_sha256$120000$MDEyMzQ1Njc4OWFiY2RlZg==$"
    "pVnYjtg7BbTIea0LtsW/0ddvJtdKtkUBqQ/vIaiKLi4="
)
USER = {"id": 7, "username": "tester", "nickname": "테스터", "password_hash": LEGACY_HASH}
PUBLIC_USER = {"id": 7, "username": "tester", "nickname": "테스터"}


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "CORS_ALLOWED_ORIGINS": ["http://localhost:5173"]})
        self.client = self.app.test_client()
        self.payload = {
            "username": "  TeSteR  ",
            "nickname": "  테스터  ",
            "password": "legacy-password",
            "passwordConfirm": "legacy-password",
        }

    def test_signup_normalizes_names_and_never_returns_password_hash(self):
        with patch.object(storage, "find_user_by_username", return_value=None) as find_user:
            with patch.object(storage, "create_user", return_value=USER) as create_user:
                response = self.client.post("/auth/signup", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"ok": True, "user": PUBLIC_USER})
        find_user.assert_called_once_with("tester")
        args = create_user.call_args.args
        self.assertEqual(args[:2], ("tester", "테스터"))
        self.assertTrue(verify_password("legacy-password", args[2]))

    def test_signup_rejects_invalid_fields_before_using_database(self):
        invalid_fields = [
            ("username", "a"),
            ("username", "a" * 33),
            ("username", "한글아이디"),
            ("username", "user name"),
            ("nickname", " a "),
            ("nickname", "a" * 31),
            ("password", "short"),
            ("passwordConfirm", "does-not-match"),
            ("passwordConfirm", None),
            ("username", 123),
        ]
        with patch.object(storage, "find_user_by_username") as find_user:
            for field, value in invalid_fields:
                with self.subTest(field=field, value=value):
                    response = self.client.post("/auth/signup", json={**self.payload, field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIsInstance(response.json["detail"], str)
            find_user.assert_not_called()

    def test_signup_and_login_require_json_objects_and_string_fields(self):
        for endpoint in ("/auth/signup", "/auth/login"):
            for body in ("{", "[]", "null", "{}", '{"username": 3, "password": false}'):
                with self.subTest(endpoint=endpoint, body=body):
                    response = self.client.post(endpoint, data=body, content_type="application/json")
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("detail", response.json)

    def test_signup_returns_409_for_existing_username(self):
        with patch.object(storage, "find_user_by_username", return_value=USER):
            with patch.object(storage, "create_user") as create_user:
                response = self.client.post("/auth/signup", json=self.payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json, {"detail": "username already exists"})
        create_user.assert_not_called()

    def test_signup_returns_409_when_concurrent_insert_wins(self):
        with patch.object(storage, "find_user_by_username", return_value=None):
            with patch.object(storage, "create_user", side_effect=storage.UsernameAlreadyExists):
                response = self.client.post("/auth/signup", json=self.payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json, {"detail": "username already exists"})

    def test_login_me_logout_and_revoked_token(self):
        expires_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
        sessions = {}

        def create_session(user_id, token):
            self.assertEqual(user_id, USER["id"])
            sessions[token] = USER
            return expires_at

        with patch.object(storage, "find_user_by_username", return_value=USER) as find_user:
            with patch.object(storage, "create_session", side_effect=create_session):
                login = self.client.post(
                    "/auth/login", json={"username": " TeStEr ", "password": "legacy-password"}
                )
        find_user.assert_called_once_with("tester")
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json["user"], PUBLIC_USER)
        self.assertEqual(login.json["token_type"], "bearer")
        self.assertEqual(login.json["expires_at"], expires_at.isoformat())
        token = login.json["access_token"]
        self.assertEqual(len(token), 43)
        headers = {"Authorization": f"Bearer {token}"}
        with patch.object(storage, "get_user_by_token", side_effect=sessions.get):
            with patch.object(storage, "delete_session", side_effect=lambda token: sessions.pop(token, None)):
                me = self.client.get("/auth/me", headers=headers)
                self.assertEqual(me.status_code, 200)
                self.assertEqual(me.json, {"ok": True, "user": PUBLIC_USER})
                logout = self.client.post("/auth/logout", headers=headers)
                self.assertEqual(logout.status_code, 200)
                self.assertEqual(logout.json, {"ok": True})
                self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)
                self.assertEqual(self.client.post("/auth/logout", headers=headers).status_code, 200)

    def test_login_rejects_unknown_user_and_wrong_password(self):
        for user in (None, USER):
            with self.subTest(user_exists=user is not None):
                with patch.object(storage, "find_user_by_username", return_value=user):
                    with patch.object(storage, "create_session") as create_session:
                        response = self.client.post(
                            "/auth/login", json={"username": "tester", "password": "wrong-password"}
                        )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json, {"detail": "invalid username or password"})
                create_session.assert_not_called()

    def test_missing_or_malformed_bearer_is_401_without_database_access(self):
        for value in (None, "", "Basic abc", "Bearer", "Bearer a b", "Bearer a,b", "Bearer a@b"):
            for path, method in (("/auth/me", self.client.get), ("/auth/logout", self.client.post)):
                with self.subTest(value=value, path=path):
                    with patch.object(storage, "get_user_by_token") as get_user:
                        with patch.object(storage, "delete_session") as delete_session:
                            headers = {} if value is None else {"Authorization": value}
                            response = method(path, headers=headers)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
                    get_user.assert_not_called()
                    delete_session.assert_not_called()

    def test_expired_or_unknown_token_is_401(self):
        with patch.object(storage, "get_user_by_token", return_value=None) as get_user:
            response = self.client.get("/auth/me", headers={"Authorization": "bearer expired-token"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json, {"detail": "invalid or expired token"})
        get_user.assert_called_once_with("expired-token")

    def test_introspection_success_and_auth_errors_cannot_be_cached(self):
        with patch.object(storage, "get_user_by_token", return_value=USER):
            response = self.client.get("/auth/me", headers={"Authorization": "Bearer valid-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        unauthorized = self.client.get("/auth/me")
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.headers["Cache-Control"], "no-store")
        with patch.object(storage, "get_user_by_token", side_effect=storage.StorageUnavailable("MySQL is unavailable")):
            unavailable = self.client.get("/auth/me", headers={"Authorization": "Bearer valid-token"})
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.headers["Cache-Control"], "no-store")

    def test_database_errors_return_json_503(self):
        cases = [
            ("/auth/signup", self.client.post, "find_user_by_username", {"json": self.payload}),
            ("/auth/login", self.client.post, "find_user_by_username", {"json": self.payload}),
            ("/auth/me", self.client.get, "get_user_by_token", {"headers": {"Authorization": "Bearer token"}}),
            ("/auth/logout", self.client.post, "delete_session", {"headers": {"Authorization": "Bearer token"}}),
        ]
        for path, method, operation, kwargs in cases:
            with self.subTest(path=path):
                with patch.object(storage, operation, side_effect=storage.StorageUnavailable("MySQL is unavailable")):
                    response = method(path, **kwargs)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json, {"detail": "MySQL is unavailable"})

    def test_cors_allows_configured_frontend_and_authorization_preflight(self):
        response = self.client.options(
            "/auth/me",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertIn("authorization", response.headers["Access-Control-Allow-Headers"].lower())
        rejected = self.client.get("/auth/me", headers={"Origin": "https://unrelated.example"})
        self.assertNotIn("Access-Control-Allow-Origin", rejected.headers)

    def test_cors_origins_can_be_overridden(self):
        app = create_app({"TESTING": True, "CORS_ALLOWED_ORIGINS": ["https://frontend.example"]})
        client = app.test_client()
        allowed = client.get("/auth/me", headers={"Origin": "https://frontend.example"})
        self.assertEqual(allowed.headers["Access-Control-Allow-Origin"], "https://frontend.example")
        rejected = client.get("/auth/me", headers={"Origin": "http://localhost:5173"})
        self.assertNotIn("Access-Control-Allow-Origin", rejected.headers)


if __name__ == "__main__":
    unittest.main()
