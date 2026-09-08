"""Resolve optional AI API identities through the Flask authentication service."""

import os

import requests
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


bearer_scheme = HTTPBearer(auto_error=False)


def current_user_from_token(token: str) -> dict:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    base_url = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8000").rstrip("/")
    try:
        timeout = float(os.getenv("AUTH_SERVICE_TIMEOUT_SECONDS", "5"))
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        response = requests.get(
            f"{base_url}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            allow_redirects=False,
        )
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "authentication service unavailable"
        ) from exc

    if response.status_code in (401, 403):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    if response.status_code != 200:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "authentication service unavailable"
        )

    try:
        payload = response.json()
        user = payload.get("user") if isinstance(payload, dict) else None
        if (
            payload.get("ok") is not True
            or not isinstance(user, dict)
            or type(user.get("id")) is not int
            or user["id"] <= 0
            or not isinstance(user.get("username"), str)
            or not isinstance(user.get("nickname"), str)
        ):
            raise ValueError("invalid authentication response")
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "invalid authentication service response"
        ) from exc

    return {key: user[key] for key in ("id", "username", "nickname")}


def optional_user_from_credentials(credentials: HTTPAuthorizationCredentials | None):
    if credentials is None:
        return None
    return current_user_from_token(credentials.credentials)
