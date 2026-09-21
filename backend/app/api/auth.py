from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.auth import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    Token,
    TokenRefreshRequest,
    UserLogin,
    UserProfileUpdate,
    UserOut,
)
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
router = APIRouter(prefix="/auth", tags=["Authentication"])

# Only Asia Tech institution emails may sign in. There is no public sign-up:
# Admin/Faculty accounts are provisioned by the seed script (seed_admin.py)
# or an internal admin panel. Students are anonymous and never log in.
ALLOWED_EMAIL_DOMAIN = "@asiatech.edu.ph"

# Default passwords assigned by the seed script. Login reports whether the
# account is still using one so the UI can offer (not force) a password
# change. These are compared against the stored hash, never stored.
DEFAULT_PASSWORDS = {
    "administrator": "ASIATECH-admin123",
    "faculty": "ASIATECH-faculty123",
}


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)):
    # Institution-only sign-in: reject any non-@asiatech.edu.ph address
    # before doing anything else (no public registration exists).
    if not payload.email.lower().endswith(ALLOWED_EMAIL_DOMAIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only @asiatech.edu.ph accounts can sign in.",
        )

    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated.")

    default_password = DEFAULT_PASSWORDS.get(user.role.value)
    using_default_password = bool(
        default_password and verify_password(default_password, user.hashed_password)
    )

    access_token = create_access_token(subject=user.id, role=user.role.value)
    refresh_token = create_refresh_token(subject=user.id, role=user.role.value)
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user,
        using_default_password=using_default_password,
    )


@router.post("/refresh", response_model=Token)
@limiter.limit("20/minute")
def refresh_token(request: Request, payload: TokenRefreshRequest, db: Session = Depends(get_db)):
    try:
        decoded = decode_token(payload.refresh_token)
        if decoded.get("type") != "refresh":
            raise ValueError("Not a refresh token")
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    user = db.query(User).filter(User.id == decoded["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive.")

    access_token = create_access_token(subject=user.id, role=user.role.value)
    new_refresh_token = create_refresh_token(subject=user.id, role=user.role.value)
    return Token(access_token=access_token, refresh_token=new_refresh_token, user=user)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def forgot_password(request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Request a password-reset token.

    In local/dev mode, the token is returned directly so UI testing works without
    a mail provider. In production, the server sends a reset email and never leaks
    the token back in the API response.
    """
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        return {"detail": "If that email exists, a reset link has been sent."}

    token = create_password_reset_token(subject=user.id)
    response = {"detail": "If that email exists, a reset link has been sent."}

    if settings.ENVIRONMENT != "production":
        response["reset_token"] = token
    else:
        from app.utils.email import send_password_reset_email

        reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
        send_password_reset_email(user.email, reset_url)

    return response


@router.post("/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
def reset_password(request: Request, payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset a user's password using a token obtained from /forgot-password."""
    try:
        decoded = decode_token(payload.token)
        if decoded.get("type") != "password_reset":
            raise ValueError("Not a password-reset token")
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    user = db.query(User).filter(User.id == decoded["sub"]).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    user.hashed_password = hash_password(payload.new_password)
    db.commit()

    return {"detail": "Password has been reset successfully. You can now log in."}


@router.get("/me/profile", response_model=UserOut)
def get_profile(current_user: User = Depends(get_current_user)):
    """Get the authenticated user's full profile (incl. student info)."""
    return current_user


@router.put("/me/profile", response_model=UserOut)
def update_profile(
    payload: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the authenticated user's profile. Optionally change the
    password by providing ``current_password`` and ``new_password``."""
    if payload.full_name is not None:
        current_user.full_name = payload.full_name
    if payload.course is not None:
        current_user.course = payload.course
    if payload.year_level is not None:
        current_user.year_level = payload.year_level
    if payload.student_id is not None:
        current_user.student_id = payload.student_id

    # Password change requires the current password to be verified.
    if payload.new_password:
        if not payload.current_password or not verify_password(
            payload.current_password, current_user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect.",
            )
        current_user.hashed_password = hash_password(payload.new_password)

    db.commit()
    db.refresh(current_user)
    return current_user
