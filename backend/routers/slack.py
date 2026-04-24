"""Slack endpoints: config CRUD, test, events webhook."""

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from collections import deque

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db, Agent
from rag_engine import get_answer
from schemas.slack import SlackConfigRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# On garde les 500 derniers event_id pour éviter les doublons
_recent_event_ids = deque(maxlen=500)
_event_ids_lock = threading.Lock()


@router.get("/api/agents/{agent_id}/slack-config")
async def get_slack_config(agent_id: int, request: Request, db: Session = Depends(get_db)):
    """Get Slack configuration status for an agent. Never returns tokens in clear."""
    from auth import verify_token_from_cookie

    user_id = verify_token_from_cookie(request)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if str(agent.user_id) != str(user_id):
        raise HTTPException(status_code=403, detail="Not authorized")

    raw_token = agent.slack_bot_token
    raw_secret = agent.slack_signing_secret
    is_configured = bool(raw_token and raw_secret)

    masked_token = ""
    masked_secret = ""
    if raw_token and len(raw_token) > 8:
        masked_token = raw_token[:4] + "****" + raw_token[-4:]
    elif raw_token:
        masked_token = "****"
    if raw_secret and len(raw_secret) > 8:
        masked_secret = raw_secret[:4] + "****" + raw_secret[-4:]
    elif raw_secret:
        masked_secret = "****"

    return {
        "is_configured": is_configured,
        "team_id": agent.slack_team_id or "",
        "bot_user_id": agent.slack_bot_user_id or "",
        "masked_token": masked_token,
        "masked_secret": masked_secret,
    }


@router.put("/api/agents/{agent_id}/slack-config")
async def update_slack_config(
    agent_id: int, payload: SlackConfigRequest, request: Request, db: Session = Depends(get_db)
):
    """Save Slack credentials after validating the bot token via auth.test."""
    from auth import verify_token_from_cookie

    user_id = verify_token_from_cookie(request)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if str(agent.user_id) != str(user_id):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Validate the token via Slack auth.test
    resp = requests.post(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {payload.slack_bot_token}"},
    )
    slack_data = resp.json()
    if not slack_data.get("ok"):
        raise HTTPException(status_code=400, detail=f"Invalid Slack token: {slack_data.get('error', 'unknown error')}")

    team_id = slack_data.get("team_id", "")
    bot_user_id = slack_data.get("user_id", "")
    team_name = slack_data.get("team", "")

    # Store via property setters (auto-encryption)
    agent.slack_bot_token = payload.slack_bot_token
    agent.slack_signing_secret = payload.slack_signing_secret
    agent.slack_team_id = team_id
    agent.slack_bot_user_id = bot_user_id
    db.commit()

    logger.info(f"Slack config saved for agent {agent_id}: team={team_name} ({team_id}), bot_user={bot_user_id}")

    return {
        "ok": True,
        "team_id": team_id,
        "bot_user_id": bot_user_id,
        "team_name": team_name,
    }


@router.delete("/api/agents/{agent_id}/slack-config")
async def delete_slack_config(agent_id: int, request: Request, db: Session = Depends(get_db)):
    """Remove all Slack configuration from an agent."""
    from auth import verify_token_from_cookie

    user_id = verify_token_from_cookie(request)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if str(agent.user_id) != str(user_id):
        raise HTTPException(status_code=403, detail="Not authorized")

    agent._slack_bot_token = None
    agent._slack_signing_secret = None
    agent.slack_team_id = None
    agent.slack_bot_user_id = None
    db.commit()

    logger.info(f"Slack config removed for agent {agent_id}")
    return {"ok": True}


@router.post("/api/agents/{agent_id}/slack-test")
async def test_slack_connection(agent_id: int, request: Request, db: Session = Depends(get_db)):
    """Test Slack connection using the stored bot token."""
    from auth import verify_token_from_cookie

    user_id = verify_token_from_cookie(request)
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if str(agent.user_id) != str(user_id):
        raise HTTPException(status_code=403, detail="Not authorized")

    slack_token = agent.slack_bot_token
    if not slack_token:
        raise HTTPException(status_code=400, detail="No Slack token configured")

    resp = requests.post(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {slack_token}"},
    )
    slack_data = resp.json()

    if not slack_data.get("ok"):
        return {"is_valid": False, "error": slack_data.get("error", "unknown error")}

    return {
        "is_valid": True,
        "team_name": slack_data.get("team", ""),
        "bot_name": slack_data.get("user", ""),
        "team_id": slack_data.get("team_id", ""),
    }


# --- SLACK WEBHOOK ENDPOINT ---


def verify_slack_signature(request_body: bytes, timestamp: str, signature: str, signing_secret: str) -> bool:
    """
    Verify Slack request signature to prevent fake events.

    Security: Each Slack webhook request is signed with a unique signature based on:
    - Request body
    - Timestamp
    - Signing secret (unique per agent/workspace)

    This prevents:
    - Fake events from attackers
    - Replay attacks (timestamp validation)
    - Timing attacks (constant-time comparison)

    Multi-tenant: Each agent has their own signing_secret stored in DB.
    """
    if not signing_secret:
        logger.error("Slack signing_secret not configured for this agent - REJECTING request for security")
        return False  # Strict mode: reject if not configured

    # Check timestamp to prevent replay attacks (max 5 minutes old)
    try:
        request_timestamp = int(timestamp)
        current_timestamp = int(time.time())
        if abs(current_timestamp - request_timestamp) > 60 * 5:
            logger.warning(f"Slack request timestamp too old: {timestamp}")
            return False
    except (ValueError, TypeError):
        logger.error(f"Invalid Slack timestamp: {timestamp}")
        return False

    # Compute expected signature using HMAC-SHA256
    sig_basestring = f"v0:{timestamp}:".encode() + request_body
    expected_signature = "v0=" + hmac.new(signing_secret.encode(), sig_basestring, hashlib.sha256).hexdigest()

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(expected_signature, signature):
        logger.error("Slack signature mismatch — request rejected")
        return False

    return True


@router.post("/slack/events")
async def slack_events(request: Request, db: Session = Depends(get_db)):
    # Get raw body and headers for signature verification
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    body = await request.body()

    # Parse JSON data
    data = json.loads(body.decode("utf-8"))

    # Vérification du challenge lors de l'installation (no signature needed for this)
    if data.get("type") == "url_verification":
        return {"challenge": data["challenge"]}

    # Extract team_id and event data for agent lookup
    event = data.get("event", {})
    team_id = data.get("team_id") or event.get("team")
    event_text = event.get("text", "")

    # Parse bot mentions from text (format: <@U123ABC>)
    mentioned_bot_user_ids = re.findall(r"<@([A-Z0-9]+)>", event_text)

    # Find agent for signature verification
    # Priority 1: Match by bot_user_id (most specific, handles multi-bot workspaces)
    agent_for_verification = None
    matched_bot_user_id = None

    if mentioned_bot_user_ids:
        for bot_user_id in mentioned_bot_user_ids:
            agent = (
                db.query(Agent).filter(Agent.slack_bot_user_id == bot_user_id, Agent.slack_team_id == team_id).first()
            )
            if agent:
                agent_for_verification = agent
                matched_bot_user_id = bot_user_id
                logger.info(f"Found agent by bot_user_id: {bot_user_id} (team: {team_id}) -> {agent.name}")
                break

    # Priority 2: Fallback to team_id only (less specific, for backwards compatibility)
    if not agent_for_verification:
        agent_for_verification = db.query(Agent).filter(Agent.slack_team_id == team_id).first()
        if agent_for_verification:
            logger.info(f"Found agent by team_id only: {team_id} -> {agent_for_verification.name}")

    if not agent_for_verification:
        logger.warning(f"No agent found for Slack team_id: {team_id}")
        raise HTTPException(status_code=403, detail="No agent configured for this Slack workspace")

    # SECURITY: Verify Slack signature with this agent's signing_secret
    if not verify_slack_signature(body, timestamp, signature, agent_for_verification.slack_signing_secret):
        logger.error(
            f"Slack signature verification failed for team_id: {team_id}, agent: {agent_for_verification.name}"
        )
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    logger.info(f"Slack signature verified for team: {team_id}, agent: {agent_for_verification.name}")

    # Check for duplicate events
    event_id = data.get("event_id")
    if event_id:
        with _event_ids_lock:
            if event_id in _recent_event_ids:
                logger.info(f"Event déjà traité, on ignore: {event_id}")
                return {"ok": True, "info": "Duplicate event ignored"}
            _recent_event_ids.append(event_id)

    # On ne traite que les mentions du bot (app_mention)
    if event.get("type") == "app_mention" and "text" in event:
        user_message = event["text"]
        channel = event["channel"]
        thread_ts = event.get("thread_ts")  # timestamp du thread si présent

        # Use the agent we already found for verification
        agent = agent_for_verification
        agent_id = agent.id
        slack_token = agent.slack_bot_token

        if not slack_token:
            logger.warning(f"No Slack token found for agent with team_id={team_id}")
            return {"ok": False, "error": "No Slack token for agent"}
        # 1. Récupère l'historique du channel ou du thread
        history = []
        try:
            headers = {"Authorization": f"Bearer {slack_token}"}
            messages = []
            if thread_ts:
                # Récupère tous les messages du thread
                resp = requests.get(
                    "https://slack.com/api/conversations.replies",
                    headers=headers,
                    params={"channel": channel, "ts": thread_ts},
                )
                messages = resp.json().get("messages", [])
                logger.info(f"Slack thread history (count={len(messages)}): {[m.get('text', '') for m in messages]}")
            else:
                # Récupère les derniers messages du channel
                resp = requests.get(
                    "https://slack.com/api/conversations.history",
                    headers=headers,
                    params={"channel": channel, "limit": 10},
                )
                messages = resp.json().get("messages", [])
                logger.info(f"Slack channel history (count={len(messages)}): {[m.get('text', '') for m in messages]}")
            # Formate l'historique pour le modèle dans l'ordre du plus ancien au plus récent
            for msg in sorted(messages, key=lambda m: float(m.get("ts", 0))):
                role = "user" if msg.get("user") else "assistant"
                content = msg.get("text", "")
                history.append({"role": role, "content": content})
        except Exception as e:
            logger.error(f"Erreur récupération historique Slack: {e}")
            history = []
        # Log le contenu de l'historique avant get_answer
        logger.info(f"Slack context sent to get_answer: {history}")
        # 2. Resolve model_id from agent's type
        slack_model_id = None
        if agent.finetuned_model_id:
            slack_model_id = agent.finetuned_model_id
        else:
            atype = getattr(agent, "type", "conversationnel")
            if atype == "recherche_live":
                slack_model_id = os.getenv("PERPLEXITY_MODEL", "perplexity:sonar")
            else:
                slack_model_id = os.getenv("MISTRAL_MODEL", "mistral:mistral-small-latest")
        # Appel direct à la fonction get_answer avec l'historique Slack
        answer = get_answer(
            user_message,
            None,
            db,
            agent_id=agent_id,
            history=history,
            model_id=slack_model_id,
            company_id=agent.company_id,
        )
        # 3. Envoie la réponse sur Slack avec le bon token
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {slack_token}"},
            json={"channel": channel, "text": answer, "thread_ts": thread_ts}
            if thread_ts
            else {"channel": channel, "text": answer},
        )
        logger.info(f"Slack API response: status={resp.status_code}")
    return {"ok": True}
