import re

from fastapi import APIRouter, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.security import create_token, hash_password, verify_password
from auth.storage import (
    create_session,
    create_user,
    delete_session,
    find_user_by_username,
    get_user_by_token,
    public_user,
)

from schema.authSchema import (
    SignupRequest,
    SignupResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    OkResponse,
)


router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")





def _normalize_username(username: str) -> str:
    return username.strip().lower()


def _validate_signup(payload: SignupRequest) -> tuple[str, str]:
    username = _normalize_username(payload.username)
    nickname = payload.nickname.strip()
    password_confirm = payload.passwordConfirm

    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username must be 3-32 characters: letters, numbers, dot, hyphen, underscore",
        )
    if not (2 <= len(nickname) <= 30):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="nickname must be 2-30 characters",
        )
    if len(payload.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="password must be at least 8 characters",
        )
    if payload.password != password_confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="password confirmation does not match",
        )

    return username, nickname


def _token_from_credentials(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    return credentials.credentials


def current_user_from_token(token: str) -> dict:
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
        )
    return user


def current_user_from_credentials(credentials: HTTPAuthorizationCredentials | None) -> dict:
    return current_user_from_token(_token_from_credentials(credentials))


def optional_user_from_credentials(credentials: HTTPAuthorizationCredentials | None):
    if credentials is None:
        return None
    return current_user_from_credentials(credentials)


@router.post(
    "/signup",
    response_model=SignupResponse,
    summary="회원가입",
    description="아이디, 닉네임, 비밀번호, 비밀번호 확인을 받아 새 사용자를 생성합니다.",
    responses={409: {"description": "이미 존재하는 아이디"}},
)
def signup(payload: SignupRequest):
    username, nickname = _validate_signup(payload)
    if find_user_by_username(username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username already exists",
        )

    user = create_user(username, nickname, hash_password(payload.password))
    return {"ok": True, "user": public_user(user)}


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="로그인",
    description="아이디와 비밀번호를 확인하고 Bearer 토큰을 발급합니다.",
    responses={401: {"description": "아이디 또는 비밀번호 불일치"}},
)
def login(payload: LoginRequest):
    username = _normalize_username(payload.username)
    user = find_user_by_username(username)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
        )

    token = create_token()
    expires_at = create_session(user["id"], token)
    return {
        "ok": True,
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user": public_user(user),
    }


@router.get(
    "/me",
    response_model=MeResponse,
    summary="현재 사용자 확인",
    description="Authorization: Bearer <token> 헤더로 현재 로그인 사용자를 확인합니다.",
    responses={401: {"description": "토큰 없음, 만료 또는 잘못된 토큰"}},
)
def me(credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme)):
    user = current_user_from_credentials(credentials)
    return {"ok": True, "user": public_user(user)}


@router.post(
    "/logout",
    response_model=OkResponse,
    summary="로그아웃",
    description="현재 Bearer 토큰 세션을 삭제합니다.",
    responses={401: {"description": "토큰 없음 또는 잘못된 Authorization 헤더"}},
)
def logout(credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme)):
    token = _token_from_credentials(credentials)
    delete_session(token)
    return {"ok": True}
