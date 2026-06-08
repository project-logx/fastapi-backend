from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from authlib.integrations.starlette_client import OAuth

from app.api.deps import get_db
from app.models import PasswordResetToken, User
from app.schemas import (
    ForgotPasswordRequest,
    TokenResponse,
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
    NewPasswordRequest,
)
from app.services.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    decode_access_token,
    forgot_password_service,
    hash_password,
    verify_password,
)
from app.services.send_email import (
    send_password_change_success_email,
    send_verification_email,
)
from app.config import settings


router = APIRouter(tags=["auth"], prefix="/auth")


# ---------------------------------------------------------------------------
# Email / password flows
# ---------------------------------------------------------------------------

@router.post("/signup", response_model=UserResponse)
def signup(payload: UserSignupRequest, db: Session = Depends(get_db)) -> dict:
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        first_name=payload.first_name,
        last_name=payload.last_name,
        phonenumber=payload.phonenumber,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        auth_provider="local",
        is_verified=False,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    verification_token = create_access_token(subject=f"verify:{new_user.email}")
    send_verification_email(verification_token, new_user.email)
    return {
        "data": {
            "id": new_user.id,
            "email": new_user.email,
            "first_name": new_user.first_name,
            "last_name": new_user.last_name,
            "phonenumber": new_user.phonenumber,
            "auth_provider": new_user.auth_provider,
            "avatar_url": new_user.avatar_url,
        }
    }


@router.post("/verify")
def verify_email(token: str | None = None, db: Session = Depends(get_db)) -> dict:
    if not token:
        raise HTTPException(status_code=400, detail="Verification token is required")

    try:
        payload = decode_access_token(token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.startswith("verify:"):
        raise HTTPException(status_code=400, detail="Invalid verification token")

    user_email = subject.removeprefix("verify:")
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_verified = True
    db.commit()
    return {"message": "Email verified successfully"}


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified. Please check your inbox.")

    access_token = create_access_token(subject=str(user.id))
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    print(f"Received forgot password request for email: {payload.email}")
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="If the email is registered, you will receive a password reset link shortly.",
        )
    response = forgot_password_service(user.id, payload.email, db)
    return response


@router.post("/reset-password")
def reset_password(payload: NewPasswordRequest, db: Session = Depends(get_db)) -> dict:
    token = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == payload.token)
        .first()
    )
    print(f"Attempting password reset with token: {payload.token}")
    if not token or token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired password reset token")

    user = db.query(User).filter(User.id == token.user_id).first()
    print(f"Found user for password reset: {user.email}")

    user.hashed_password = hash_password(payload.new_password)
    db.add(user)
    db.commit()
    send_password_change_success_email(user.email)
    return {"message": "Password reset successfully"}


# ---------------------------------------------------------------------------
# Google OAuth flow
# ---------------------------------------------------------------------------

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
print(
    f"Google OAuth registered with client_id: {settings.google_client_id} "
    f"and client_secret: {'***' if settings.google_client_secret else '(not set)'}"
)


@router.get("/google")
async def google_login(request: Request):
    redirect_uri = request.url_for("auth_callback")
    print(redirect_uri)
    return await oauth.google.authorize_redirect(request, redirect_uri=redirect_uri)


@router.get("/google/callback", name="auth_callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)

        user_info = token.get("userinfo")
        if not user_info:
            raise HTTPException(status_code=400, detail="Failed to retrieve user info from Google")

        provider_user_id = user_info.get("sub")
        if not provider_user_id:
            raise HTTPException(status_code=400, detail="Google user id not found")

        user_email = user_info.get("email")
        given_name = user_info.get("given_name")
        family_name = user_info.get("family_name")
        avatar_url = user_info.get("picture")
        print(f"Google user info: {user_info}")

        # 1. Look up by provider_user_id first (returning OAuth user)
        user = (
            db.query(User)
            .filter(
                User.auth_provider == "google",
                User.provider_user_id == provider_user_id,
            )
            .first()
        )

        if user:
            # Update latest profile info
            user.first_name = given_name
            user.last_name = family_name
            user.avatar_url = avatar_url
        else:
            # 2. Check if an email/password account already exists for this email
            user = db.query(User).filter(User.email == user_email).first()
            if user:
                # Link Google to the existing local account
                user.auth_provider = "google"
                user.provider_user_id = provider_user_id
                user.avatar_url = avatar_url
                user.is_verified = True  # Google-verified email is trusted
            else:
                # 3. Brand new user — create via Google
                user = User(
                    email=user_email,
                    first_name=given_name,
                    last_name=family_name,
                    avatar_url=avatar_url,
                    auth_provider="google",
                    provider_user_id=provider_user_id,
                    hashed_password=None,
                    phonenumber=None,
                    is_verified=True,  # Google already verified the email
                )
                db.add(user)

        db.commit()
        db.refresh(user)

        # Always use user.id as JWT subject for consistency with local login
        access_token = create_access_token(subject=str(user.id))
        # Pass the token via URL query param so the SPA can store it in localStorage.
        # (httpOnly cookies are invisible to JS, which breaks the frontend auth flow.)
        redirect_url = f"{settings.frontend_base_url}/dashboard?token={access_token}"
        return RedirectResponse(url=redirect_url)
    except Exception as e:
        print(f"Google OAuth error: {e}")
        raise HTTPException(status_code=400, detail="Google authentication failed")
