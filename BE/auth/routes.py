import re

from flask import Blueprint, jsonify, request

from . import storage
from .security import create_token, hash_password, verify_password


auth_blueprint = Blueprint("auth", __name__, url_prefix="/auth")
USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,32}")
BEARER_TOKEN_RE = re.compile(r"[A-Za-z0-9._~+/-]+=*")


class InvalidRequest(ValueError):
    pass


@auth_blueprint.after_request
def prevent_auth_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_blueprint.errorhandler(InvalidRequest)
def invalid_request(error):
    return jsonify(detail=str(error)), 400


def _string_payload(*fields):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise InvalidRequest("request body must be a JSON object")
    for field in fields:
        if not isinstance(payload.get(field), str):
            raise InvalidRequest(f"{field} must be a string")
    return payload


def _validate_signup(payload):
    username = payload["username"].strip().lower()
    nickname = payload["nickname"].strip()
    if not USERNAME_RE.fullmatch(username):
        raise InvalidRequest(
            "username must be 3-32 characters: letters, numbers, dot, hyphen, underscore"
        )
    if not 2 <= len(nickname) <= 30:
        raise InvalidRequest("nickname must be 2-30 characters")
    if len(payload["password"]) < 8:
        raise InvalidRequest("password must be at least 8 characters")
    if payload["password"] != payload["passwordConfirm"]:
        raise InvalidRequest("password confirmation does not match")
    return username, nickname


def _bearer_token():
    authorization = request.headers.get("Authorization", "")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1]
    return token if BEARER_TOKEN_RE.fullmatch(token) else None


def _unauthorized(detail):
    response = jsonify(detail=detail)
    response.status_code = 401
    response.headers["WWW-Authenticate"] = "Bearer"
    return response


@auth_blueprint.post("/signup")
def signup():
    payload = _string_payload("username", "nickname", "password", "passwordConfirm")
    username, nickname = _validate_signup(payload)
    if storage.find_user_by_username(username):
        raise storage.UsernameAlreadyExists()
    user = storage.create_user(username, nickname, hash_password(payload["password"]))
    return jsonify(ok=True, user=storage.public_user(user))


@auth_blueprint.post("/login")
def login():
    payload = _string_payload("username", "password")
    user = storage.find_user_by_username(payload["username"].strip().lower())
    if not user or not verify_password(payload["password"], user["password_hash"]):
        return _unauthorized("invalid username or password")
    token = create_token()
    expires_at = storage.create_session(user["id"], token)
    return jsonify(
        ok=True,
        access_token=token,
        token_type="bearer",
        expires_at=expires_at.isoformat(),
        user=storage.public_user(user),
    )


@auth_blueprint.get("/me")
def me():
    token = _bearer_token()
    if token is None:
        return _unauthorized("missing bearer token")
    user = storage.get_user_by_token(token)
    if not user:
        return _unauthorized("invalid or expired token")
    return jsonify(ok=True, user=storage.public_user(user))


@auth_blueprint.post("/logout")
def logout():
    token = _bearer_token()
    if token is None:
        return _unauthorized("missing bearer token")
    # Deleting a session that is already gone is intentionally idempotent.
    storage.delete_session(token)
    return jsonify(ok=True)
