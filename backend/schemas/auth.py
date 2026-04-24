"""Auth-related Pydantic schemas."""

from pydantic import BaseModel
from typing import Optional


class UserLogin(BaseModel):
    username: str
    password: str


class FeedbackRequest(BaseModel):
    type: str  # "bug", "feature", "feedback", "other"
    message: str


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: str


class GoogleOAuthRequest(BaseModel):
    credential: str
    invite_code: Optional[str] = None


class TwoFactorVerifyRequest(BaseModel):
    code: str


class TwoFactorConfirmSetupRequest(BaseModel):
    code: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
