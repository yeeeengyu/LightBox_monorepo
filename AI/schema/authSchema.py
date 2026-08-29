from pydantic import BaseModel, Field

class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, description="로그인 아이디")
    nickname: str = Field(..., min_length=2, max_length=30, description="서비스에서 표시할 닉네임")
    password: str = Field(..., min_length=8, description="로그인 비밀번호")
    passwordConfirm: str = Field(..., min_length=8, description="비밀번호 확인")


class LoginRequest(BaseModel):
    username: str = Field(..., description="로그인 아이디")
    password: str = Field(..., description="로그인 비밀번호")


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