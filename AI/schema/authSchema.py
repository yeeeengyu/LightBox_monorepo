from pydantic import BaseModel, Field

class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    nickname: str = Field(..., min_length=2, max_length=30)
    password: str = Field(..., min_length=8)
    passwordConfirm: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    username: str = Field(...)
    password: str = Field(...)


class UserResponse(BaseModel):
    id: int
    username: str
    nickname: str


class SignupResponse(BaseModel):
    ok: bool
    user: UserResponse


class LoginResponse(BaseModel):
    ok: bool
    access_token: str
    token_type: str
    expires_at: str
    user: UserResponse


class MeResponse(BaseModel):
    ok: bool
    user: UserResponse


class OkResponse(BaseModel):
    ok: bool