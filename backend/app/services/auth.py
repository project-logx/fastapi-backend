from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from app.models import PasswordResetToken
from app.services.send_email import send_password_reset_email, send_verification_email

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

_HASH_ALGORITHM = "sha256"
_HASH_ITERATIONS = 120_000
_HASH_SALT_BYTES = 16


def _base64url_encode(data: bytes) -> str:
	return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(data: str) -> bytes:
	padding = "=" * (-len(data) % 4)
	return base64.urlsafe_b64decode(data + padding)


def _sign_token(signing_input: bytes, secret: str) -> str:
	digest = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
	return _base64url_encode(digest)


def hash_password(password: str) -> str:
	if not password:
		raise ValueError("Password must not be empty")
	salt = secrets.token_bytes(_HASH_SALT_BYTES)
	hashed = hashlib.pbkdf2_hmac(
		_HASH_ALGORITHM,
		password.encode("utf-8"),
		salt,
		_HASH_ITERATIONS,
	)
	return "pbkdf2_sha256${}${}${}".format(
		_HASH_ITERATIONS,
		_base64url_encode(salt),
		_base64url_encode(hashed),
	)


def verify_password(plain: str, hashed: str) -> bool:
	try:
		scheme, iterations_raw, salt_raw, hash_raw = hashed.split("$", 3)
	except ValueError:
		return False
	if scheme != "pbkdf2_sha256":
		return False
	try:
		iterations = int(iterations_raw)
		salt = _base64url_decode(salt_raw)
		expected_hash = _base64url_decode(hash_raw)
	except (ValueError, binascii.Error):
		return False
	computed_hash = hashlib.pbkdf2_hmac(
		_HASH_ALGORITHM,
		plain.encode("utf-8"),
		salt,
		iterations,
	)
	return hmac.compare_digest(computed_hash, expected_hash)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
	if ALGORITHM != "HS256":
		raise ValueError(f"Unsupported algorithm: {ALGORITHM}")
	if not subject:
		raise ValueError("Subject must not be empty")

	now = datetime.now(timezone.utc)
	expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

	header = {"alg": "HS256", "typ": "JWT"}
	payload = {
		"sub": subject,
		"iat": int(now.timestamp()),
		"exp": int(expire.timestamp()),
	}

	encoded_header = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
	encoded_payload = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
	signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
	signature = _sign_token(signing_input, SECRET_KEY)
	return f"{encoded_header}.{encoded_payload}.{signature}"


def decode_access_token(token: str) -> dict:
	if ALGORITHM != "HS256":
		raise ValueError(f"Unsupported algorithm: {ALGORITHM}")
	try:
		encoded_header, encoded_payload, signature = token.split(".", 2)
	except ValueError as exc:
		raise ValueError("Invalid token format") from exc

	signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
	expected_sig = _sign_token(signing_input, SECRET_KEY)
	if not hmac.compare_digest(expected_sig, signature):
		raise ValueError("Invalid token signature")

	try:
		header = json.loads(_base64url_decode(encoded_header))
		payload = json.loads(_base64url_decode(encoded_payload))
	except (json.JSONDecodeError, binascii.Error) as exc:
		raise ValueError("Invalid token payload") from exc

	if header.get("alg") != "HS256":
		raise ValueError("Invalid token algorithm")

	exp = payload.get("exp")
	if isinstance(exp, int):
		now_ts = int(datetime.now(timezone.utc).timestamp())
		if now_ts >= exp:
			raise ValueError("Token has expired")

	return payload

def create_reset_password_token()->str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return token_hash


def forgot_password_service(id: str, email: str, db: Session) -> dict:

	token_hash = create_reset_password_token()
	db.query(PasswordResetToken).filter(PasswordResetToken.user_id == id).delete()

	reset_token = PasswordResetToken(
		user_id=id,
		token_hash=token_hash,
		expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
	)
	db.add(reset_token)
	send_password_reset_email(token_hash, email)
	db.commit()

	return {
		"message": "Password Reset Link Sent Successfully!!"
	}






