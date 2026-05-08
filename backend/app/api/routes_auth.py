from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime,timezone
from app.api.deps import get_db
from app.models import User, PasswordResetToken
from app.schemas import (
    ForgotPasswordRequest,
    TokenResponse,
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
    NewPasswordRequest
)
from app.services.auth import create_access_token, decode_access_token, hash_password, verify_password, forgot_password_service
from app.services.send_email import (
    send_password_change_success_email,
    send_verification_email,
)


router = APIRouter(tags=["auth"], prefix="/auth")


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
        is_verified=False,
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    verification_token = create_access_token(subject=f"verify:{new_user.email}")
    send_verification_email(verification_token,new_user.email)
    return {
        "data": {
            "id": new_user.id,
            "email": new_user.email,
            "first_name": new_user.first_name,
            "last_name": new_user.last_name,
            "phonenumber": new_user.phonenumber,
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
    if not user or not verify_password(payload.password, user.hashed_password):
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
        raise HTTPException(status_code=404, detail="if the email is registered, you will receive a password reset link shortly.")
    response = forgot_password_service(user.id, payload.email, db)
    return response


@router.post("/reset-password")
def reset_password(payload:NewPasswordRequest, db: Session = Depends(get_db))->dict:
    token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == payload.token).first()
    print(f"Attempting password reset with token: {payload.token}")
    if not token or token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired password reset token")
    
    user = db.query(User).filter(User.id ==token.user_id).first()
    print(f"Found user for password reset: {user.email}")

    new_hashed_password = hash_password(payload.new_password)
    user.hashed_password = new_hashed_password
    db.add(user)
    db.commit()
    send_password_change_success_email(user.email)
    return {"message": "Password reset successfully"}