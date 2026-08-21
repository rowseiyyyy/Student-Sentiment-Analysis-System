from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole

oauth2_scheme = HTTPBearer(auto_error=False, scheme_name="Bearer")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_exception
    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMINISTRATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires administrator privileges.",
        )
    return current_user


def require_staff(current_user: User = Depends(get_current_user)) -> User:
    """Faculty and administrators can view the shared/aggregate reporting
    data (analytics, dashboards). Students may only see their own
    submissions via the evaluation endpoints, never sitewide analytics."""
    if current_user.role not in {UserRole.ADMINISTRATOR, UserRole.FACULTY}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires faculty or administrator privileges.",
        )
    return current_user