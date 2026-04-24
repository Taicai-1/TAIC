"""Authentication endpoints: register, login, 2FA, OAuth, email verification, logout, password reset."""

import logging
import os
from datetime import datetime, timedelta
from uuid import uuid4

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from auth import (
    create_access_token,
    verify_token,
    hash_password,
    verify_password,
    hash_reset_token,
    verify_pre_2fa_token,
    verify_setup_token,
)
from database import get_db, User, PasswordResetToken
from email_service import (
    send_password_reset_email,
    send_verification_email,
    send_feedback_email,
)
from helpers.rate_limiting import (
    _check_auth_rate_limit,
    _record_auth_failure,
    _check_2fa_rate_limit,
)
from redis_client import get_cached_user, invalidate_user_cache
from schemas.auth import (
    UserLogin,
    FeedbackRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
    GoogleOAuthRequest,
    TwoFactorVerifyRequest,
    TwoFactorConfirmSetupRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from validation import UserCreateValidated

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/register")
async def register(user: UserCreateValidated, request: Request, db: Session = Depends(get_db)):
    """Register new user"""
    # Rate limiting: prevent brute force account creation
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_auth_rate_limit(ip):
        logger.warning(f"Rate limit exceeded for registration from IP: {ip}")
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again in 1 hour.")

    try:
        # Check if user exists
        if db.query(User).filter(User.username == user.username).first():
            raise HTTPException(status_code=400, detail="Username already registered")

        if db.query(User).filter(User.email == user.email).first():
            raise HTTPException(status_code=400, detail="Email already registered")

        # Create new user
        hashed_password = hash_password(user.password)
        db_user = User(username=user.username, email=user.email, hashed_password=hashed_password)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        # Handle invite_code: join org on registration
        if user.invite_code:
            company = (
                db.query(Company)
                .filter(Company.invite_code == user.invite_code, Company.invite_code_enabled == True)
                .first()
            )
            if company:
                db_user.company_id = company.id
                membership = CompanyMembership(user_id=db_user.id, company_id=company.id, role="member")
                db.add(membership)
                db.commit()
                invalidate_user_cache(db_user.id)
                logger.info(f"User {user.username} joined company {company.name} via invite_code at registration")

        logger.info(f"User registered: {user.username}")
        event_tracker.track_user_action(db_user.id, "user_registered")

        # Send verification email
        try:
            verify_token = create_access_token(
                data={"sub": str(db_user.id), "type": "email_verify"}, expires_delta=timedelta(hours=24)
            )
            frontend_url = os.getenv("FRONTEND_URL", "https://taic.ai")
            verify_link = f"{frontend_url}/verify-email?token={verify_token}"
            send_verification_email(db_user.email, verify_link)
            logger.info(f"Verification email sent to {db_user.email}")
        except Exception as e:
            logger.error(f"Failed to send verification email to {db_user.email}: {e}")

        return {"message": "User created successfully. Please verify your email."}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/login")
async def login(user: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    """Login user with HttpOnly secure cookie"""
    # Rate limiting: prevent brute force password attacks
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_auth_rate_limit(ip):
        logger.warning(f"Rate limit exceeded for login from IP: {ip}")
        raise HTTPException(status_code=429, detail="Too many failed attempts. Please try again in 1 hour.")

    try:
        # Permet la connexion avec username OU email
        db_user = db.query(User).filter((User.username == user.username) | (User.email == user.username)).first()
        if not db_user:
            _record_auth_failure(ip)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # OAuth-only user (no password) trying to login with password
        if not db_user.hashed_password:
            raise HTTPException(
                status_code=400, detail="This account uses Google sign-in. Please use the Google button."
            )

        if not verify_password(user.password, db_user.hashed_password):
            _record_auth_failure(ip)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Email verification check (before 2FA)
        if not db_user.email_verified:
            # Auto-send verification email
            try:
                verify_token = create_access_token(
                    data={"sub": str(db_user.id), "type": "email_verify"}, expires_delta=timedelta(hours=24)
                )
                frontend_url = os.getenv("FRONTEND_URL", "https://taic.ai")
                verify_link = f"{frontend_url}/verify-email?token={verify_token}"
                send_verification_email(db_user.email, verify_link)
                logger.info(f"Verification email auto-sent to {db_user.email} on login")
            except Exception as e:
                logger.error(f"Failed to auto-send verification email on login: {e}")

            # Mask email: j***@gmail.com
            email = db_user.email
            at_idx = email.index("@")
            masked = email[0] + "***" + email[at_idx:]
            return {"requires_email_verification": True, "email": masked}

        # 2FA flow: check user's TOTP state
        if db_user.totp_enabled:
            # User has 2FA enabled → issue restricted pre_2fa token (5 min)
            pre_2fa_token = create_access_token(
                data={"sub": str(db_user.id), "type": "pre_2fa"}, expires_delta=timedelta(minutes=5)
            )
            logger.info(f"User {user.username} requires 2FA verification")
            return {"requires_2fa": True, "pre_2fa_token": pre_2fa_token, "token_type": "bearer"}

        if not getattr(db_user, "totp_setup_completed_at", None):
            # User has NOT set up 2FA yet → issue restricted setup token (30 min)
            setup_token = create_access_token(
                data={"sub": str(db_user.id), "type": "needs_2fa_setup"}, expires_delta=timedelta(minutes=30)
            )
            logger.info(f"User {user.username} needs 2FA setup")
            return {"requires_2fa_setup": True, "setup_token": setup_token, "token_type": "bearer"}

        # 2FA completed → issue full access token
        access_token = create_access_token(data={"sub": str(db_user.id)})

        # Security: Set HttpOnly secure cookie to prevent XSS token theft
        response.set_cookie(
            key="token", value=access_token, httponly=True, secure=True, samesite="none", max_age=28800, path="/"
        )

        logger.info(f"User logged in: {user.username}")
        event_tracker.track_user_action(db_user.id, "user_login")

        return {"access_token": access_token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


############################
# Feedback Endpoint
############################


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest, request: Request, db: Session = Depends(get_db)):
    """Submit user feedback via email to contact@taic.co."""
    from auth import verify_token_from_cookie

    user_id = verify_token_from_cookie(request)
    db_user = get_cached_user(user_id, db)
    if not db_user:
        raise HTTPException(status_code=401, detail="User not found")

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if len(req.message) > 5000:
        raise HTTPException(status_code=400, detail="Message too long (max 5000 characters)")

    try:
        send_feedback_email(db_user.email, db_user.username, req.type, req.message.strip())
        return {"message": "Feedback sent successfully"}
    except Exception as e:
        logger.error(f"Failed to send feedback email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send feedback")


############################
# Email Verification Endpoints
############################


@router.post("/auth/verify-email")
async def verify_email(req: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify user email with JWT token from verification link."""
    from auth import SECRET_KEY, ALGORITHM
    import jwt as pyjwt

    try:
        payload = pyjwt.decode(req.token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "email_verify":
            raise HTTPException(status_code=400, detail="Invalid verification token")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid verification token")

        db_user = db.query(User).filter(User.id == int(user_id)).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        if db_user.email_verified:
            return {"message": "Email already verified"}

        db_user.email_verified = True
        db.commit()
        invalidate_user_cache(db_user.id)
        logger.info(f"Email verified for user {db_user.username}")
        return {"message": "Email verified successfully"}

    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Verification link has expired")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=400, detail="Invalid verification token")


@router.post("/auth/resend-verification")
async def resend_verification(req: ResendVerificationRequest, request: Request, db: Session = Depends(get_db)):
    """Resend email verification link. Rate limited."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_auth_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")

    # Always return success to prevent email enumeration
    db_user = db.query(User).filter(User.email == req.email).first()
    if not db_user or db_user.email_verified:
        return {"message": "If this email exists and is unverified, a verification link has been sent."}

    try:
        verify_token = create_access_token(
            data={"sub": str(db_user.id), "type": "email_verify"}, expires_delta=timedelta(hours=24)
        )
        frontend_url = os.getenv("FRONTEND_URL", "https://taic.ai")
        verify_link = f"{frontend_url}/verify-email?token={verify_token}"
        send_verification_email(db_user.email, verify_link)
        logger.info(f"Verification email resent to {db_user.email}")
    except Exception as e:
        logger.error(f"Failed to resend verification email: {e}")

    return {"message": "If this email exists and is unverified, a verification link has been sent."}


############################
# Google OAuth2 Endpoint
############################


@router.post("/auth/google")
async def google_oauth(req: GoogleOAuthRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Authenticate with Google OAuth2 ID token."""
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests

    google_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    if not google_client_id:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    try:
        # Verify the Google ID token
        idinfo = google_id_token.verify_oauth2_token(req.credential, google_requests.Request(), google_client_id)

        email = idinfo.get("email")
        name = idinfo.get("name", "")
        if not email:
            raise HTTPException(status_code=400, detail="Google account has no email")

        # Check for existing user by email
        db_user = db.query(User).filter(User.email == email).first()

        if db_user:
            # Existing user — link Google if not already done
            if not db_user.email_verified:
                db_user.email_verified = True
            if not db_user.oauth_provider:
                db_user.oauth_provider = "google"
            db.commit()
            invalidate_user_cache(db_user.id)
        else:
            # New user — create account
            username = email.split("@")[0]
            # Ensure username uniqueness
            base_username = username
            counter = 1
            while db.query(User).filter(User.username == username).first():
                username = f"{base_username}{counter}"
                counter += 1

            db_user = User(
                username=username, email=email, hashed_password=None, email_verified=True, oauth_provider="google"
            )
            db.add(db_user)
            db.commit()
            db.refresh(db_user)

            # Handle invite_code
            if req.invite_code:
                company = (
                    db.query(Company)
                    .filter(Company.invite_code == req.invite_code, Company.invite_code_enabled == True)
                    .first()
                )
                if company:
                    db_user.company_id = company.id
                    membership = CompanyMembership(user_id=db_user.id, company_id=company.id, role="member")
                    db.add(membership)
                    db.commit()

            logger.info(f"Google OAuth user created: {username}")
            event_tracker.track_user_action(db_user.id, "user_registered_google")

        # Issue full access token (skip 2FA for OAuth)
        access_token = create_access_token(data={"sub": str(db_user.id)})

        response.set_cookie(
            key="token", value=access_token, httponly=True, secure=True, samesite="none", max_age=28800, path="/"
        )

        logger.info(f"Google OAuth login: {email}")
        event_tracker.track_user_action(db_user.id, "user_login_google")

        return {"access_token": access_token, "token_type": "bearer"}

    except ValueError as e:
        logger.error(f"Google OAuth token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid Google token")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google OAuth error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/auth/verify")
async def verify_auth(request: Request, db: Session = Depends(get_db)):
    """Verify authentication via HttpOnly cookie

    This endpoint checks if the user is authenticated by verifying the HttpOnly cookie.
    Used by frontend pages to check auth without localStorage.

    Returns:
        - 200: User authenticated, returns user info
        - 401: Not authenticated
    """
    from auth import verify_token_from_cookie

    try:
        user_id = verify_token_from_cookie(request)

        # Get user info
        db_user = get_cached_user(user_id, db)
        if not db_user:
            raise HTTPException(status_code=401, detail="User not found")

        return {
            "authenticated": True,
            "user": {
                "id": db_user.id,
                "username": db_user.username,
                "email": db_user.email,
                "totp_enabled": db_user.totp_enabled,
                "company_id": db_user.company_id,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth verification error: {e}")
        raise HTTPException(status_code=401, detail="Not authenticated")


############################
# 2FA (TOTP) Endpoints
############################


@router.post("/auth/2fa/setup")
async def setup_2fa(request: Request, db: Session = Depends(get_db)):
    """Generate TOTP secret and QR code for 2FA setup.
    Requires a setup token (needs_2fa_setup).
    """
    import pyotp
    import qrcode
    import io
    import base64

    user_id = verify_setup_token(request)
    db_user = db.query(User).filter(User.id == int(user_id)).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Generate TOTP secret
    secret = pyotp.random_base32()

    # Store encrypted secret (not yet enabled)
    db_user.totp_secret = secret
    db.commit()
    invalidate_user_cache(db_user.id)

    # Generate provisioning URI for QR code
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=db_user.email, issuer_name="TAIC Companion")

    # Generate QR code as base64 image
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    qr_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return {"secret": secret, "qr_code": f"data:image/png;base64,{qr_base64}"}


@router.post("/auth/2fa/confirm-setup")
async def confirm_2fa_setup(
    body: TwoFactorConfirmSetupRequest, request: Request, response: Response, db: Session = Depends(get_db)
):
    """Confirm 2FA setup by verifying the first TOTP code.
    Activates 2FA, generates backup codes, returns full access token.
    """
    import pyotp

    user_id = verify_setup_token(request)
    db_user = db.query(User).filter(User.id == int(user_id)).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    secret = db_user.totp_secret
    if not secret:
        raise HTTPException(status_code=400, detail="2FA setup not initiated")

    # Verify the code
    totp = pyotp.TOTP(secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid verification code")

    # Activate 2FA
    db_user.totp_enabled = True
    db_user.totp_setup_completed_at = datetime.utcnow()
    db.commit()
    invalidate_user_cache(db_user.id)

    # Issue full access token
    access_token = create_access_token(data={"sub": str(db_user.id)})

    response.set_cookie(
        key="token", value=access_token, httponly=True, secure=True, samesite="none", max_age=28800, path="/"
    )

    logger.info(f"2FA setup completed for user {db_user.username}")
    event_tracker.track_user_action(db_user.id, "2fa_setup_completed")

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/auth/2fa/verify")
async def verify_2fa(body: TwoFactorVerifyRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Verify TOTP code or backup code during login.
    Requires a pre_2fa token. Returns full access token on success.
    """
    import pyotp

    user_id = verify_pre_2fa_token(request)

    # Rate limiting per user
    if not _check_2fa_rate_limit(user_id):
        raise HTTPException(status_code=429, detail="Too many 2FA attempts. Please try again in 5 minutes.")

    db_user = get_cached_user(user_id, db)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if not db_user.totp_enabled or not db_user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA is not enabled")

    # Verify TOTP code
    secret = db_user.totp_secret
    totp = pyotp.TOTP(secret)
    if not totp.verify(body.code.strip(), valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid verification code")

    # Issue full access token
    access_token = create_access_token(data={"sub": str(db_user.id)})

    response.set_cookie(
        key="token", value=access_token, httponly=True, secure=True, samesite="none", max_age=28800, path="/"
    )

    logger.info(f"2FA verified for user {db_user.username}")
    event_tracker.track_user_action(db_user.id, "2fa_verified")

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/auth/2fa/status")
async def get_2fa_status(request: Request, db: Session = Depends(get_db)):
    """Get 2FA status for the current user. Requires full access token."""
    from auth import verify_token_from_cookie

    user_id = verify_token_from_cookie(request)
    db_user = get_cached_user(user_id, db)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "totp_enabled": db_user.totp_enabled,
        "setup_completed_at": db_user.totp_setup_completed_at.isoformat() if db_user.totp_setup_completed_at else None,
    }


@router.post("/logout")
async def logout(response: Response):
    """Logout user by clearing HttpOnly cookie

    Clears the authentication cookie to log out the user.
    """
    response.delete_cookie(key="token", path="/")
    return {"message": "Logged out successfully"}



@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    # Rate limiting: prevent abuse of password reset
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_auth_rate_limit(ip):
        logger.warning(f"Rate limit exceeded for forgot-password from IP: {ip}")
        raise HTTPException(status_code=429, detail="Too many password reset attempts. Please try again in 15 minutes.")

    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    # Generate token and hash it before storing (security: prevent token theft if DB compromised)
    token = str(uuid4())
    token_hash = hash_reset_token(token)
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    # Store HASHED token in DB
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token_hash,  # Store hash, not plaintext
        expires_at=expires_at,
        used=False,
    )
    db.add(reset_token)
    db.commit()

    # Send PLAINTEXT token in email (user needs it to reset password)
    frontend_url = os.getenv("FRONTEND_URL", "https://taic.ai")
    reset_link = f"{frontend_url}/reset-password?token={token}"
    try:
        send_password_reset_email(user.email, reset_link)
        logger.info(f"Password reset email sent to {user.email}")
        return {"message": "Un lien de réinitialisation a été envoyé par email"}
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de l'email: {e}")
        return {"message": "Erreur lors de l'envoi de l'email"}


# Endpoint pour réinitialiser le mot de passe (DB version)
@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    # Rate limiting: prevent brute force token guessing
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_auth_rate_limit(ip):
        logger.warning(f"Rate limit exceeded for reset-password from IP: {ip}")
        raise HTTPException(status_code=429, detail="Too many reset attempts. Please try again in 15 minutes.")

    # Hash the received token to look it up in DB (tokens are stored hashed)
    token_hash = hash_reset_token(req.token)
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token == token_hash).first()

    if not reset_token:
        raise HTTPException(status_code=400, detail="Token invalide ou expiré")
    if reset_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Token expiré")
    if reset_token.used:
        raise HTTPException(status_code=400, detail="Token déjà utilisé")

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    user.hashed_password = hash_password(req.new_password)
    reset_token.used = True
    db.commit()
    invalidate_user_cache(user.id)

    logger.info(f"Password reset successful for user {user.email}")
    return {"message": "Mot de passe réinitialisé avec succès"}

