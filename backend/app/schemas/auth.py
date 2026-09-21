from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class UserProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    course: str | None = None
    year_level: str | None = None
    student_id: str | None = None
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    role: UserRole
    is_active: bool
    student_id: str | None = None
    course: str | None = None
    year_level: str | None = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut
    # True when the account still uses its seed default password. The UI uses
    # this to offer (never force) a password change after login.
    using_default_password: bool = False


class TokenRefreshRequest(BaseModel):
    refresh_token: str
