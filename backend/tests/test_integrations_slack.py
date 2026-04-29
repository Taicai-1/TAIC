"""Integration tests for Slack webhook handling."""

import pytest
import json


@pytest.mark.asyncio
async def test_slack_url_verification(client):
    """Test Slack URL verification challenge response."""
    challenge_value = "test_challenge_string_12345"
    payload = {"type": "url_verification", "challenge": challenge_value, "token": "test_token"}

    response = await client.post("/slack/events", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["challenge"] == challenge_value


@pytest.mark.asyncio
async def test_slack_event_without_signature_rejected(client, test_agent):
    """Test that Slack events without valid signature are rejected."""
    # Set up agent with Slack config
    test_agent.slack_team_id = "T12345"
    test_agent.slack_bot_user_id = "U12345"
    test_agent._slack_signing_secret = "test_signing_secret"
    test_agent._slack_bot_token = "xoxb-test-token"

    payload = {
        "type": "event_callback",
        "team_id": "T12345",
        "event": {
            "type": "app_mention",
            "text": "<@U12345> Hello bot!",
            "channel": "C12345",
            "user": "U67890",
            "team": "T12345",
        },
        "event_id": "Ev12345",
    }

    # POST without X-Slack-Signature and X-Slack-Request-Timestamp headers
    response = await client.post("/slack/events", json=payload)

    # Should reject with 403 due to missing/invalid signature
    assert response.status_code == 403
    data = response.json()
    assert "signature" in data["detail"].lower()
