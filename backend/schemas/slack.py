"""Slack-related Pydantic schemas."""

from pydantic import BaseModel


class SlackConfigRequest(BaseModel):
    slack_bot_token: str
    slack_signing_secret: str
