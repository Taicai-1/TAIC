"""
Centralized email service for TAIC Companion.
All outbound emails go through this module using contact@taic.co (Google Workspace).
"""

import os
import re
import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

# SMTP configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "contact@taic.co")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "TAIC Companion")


def send_email(to: str, subject: str, html_body: str):
    """Send an email via SMTP with HTML content."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        raise RuntimeError("SMTP_EMAIL or SMTP_PASSWORD not configured")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_EMAIL}>"
    msg["To"] = to

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)

    logger.info(f"Email sent to {to}: {subject}")


def _wrap_template(content_html: str, preheader: str = "") -> str:
    """Wrap content in the branded TAIC email template."""
    preheader_block = ""
    if preheader:
        preheader_block = (
            f'<div style="display:none;font-size:1px;color:#f3f4f6;'
            f'line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">'
            f"{preheader}</div>"
        )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TAIC Companion</title>
</head>
<body style="margin:0; padding:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color:#f3f4f6; -webkit-font-smoothing:antialiased;">
  {preheader_block}
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f6;">
    <tr>
      <td align="center" style="padding:24px 16px;">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%;">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg, #6366f1 0%, #a855f7 100%); border-radius:16px 16px 0 0; padding:32px 24px; text-align:center;">
              <h1 style="color:#ffffff; margin:0; font-size:24px; font-weight:700; letter-spacing:-0.5px;">TAIC Companion</h1>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="background:#ffffff; padding:32px 24px; border-radius:0 0 16px 16px; box-shadow:0 4px 6px rgba(0,0,0,0.07);">
              {content_html}
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:24px; text-align:center;">
              <p style="color:#9ca3af; font-size:12px; margin:0; line-height:1.5;">
                &copy; 2025 TAIC Companion &middot; <a href="mailto:contact@taic.co" style="color:#9ca3af; text-decoration:none;">contact@taic.co</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_verification_email(to_email: str, verify_link: str):
    """Send a branded email verification email with CTA button."""
    content = f"""
<h2 style="color:#1f2937; margin:0 0 16px 0; font-size:20px;">
  V&eacute;rifiez votre adresse email
</h2>
<p style="color:#4b5563; font-size:15px; line-height:1.6; margin:0 0 24px 0;">
  Bienvenue sur TAIC Companion ! Cliquez sur le bouton ci-dessous
  pour v&eacute;rifier votre adresse email et activer votre compte.
  Ce lien expire dans 24 heures.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td align="center" style="padding:8px 0 24px 0;">
      <a href="{verify_link}"
         style="display:inline-block; background:linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
                color:#ffffff; text-decoration:none; padding:14px 32px; border-radius:8px;
                font-size:15px; font-weight:600; letter-spacing:0.3px;">
        V&eacute;rifier mon email
      </a>
    </td>
  </tr>
</table>
<p style="color:#9ca3af; font-size:13px; line-height:1.5; margin:0;">
  Si vous n'avez pas cr&eacute;&eacute; de compte TAIC Companion, ignorez cet email.
</p>"""

    html = _wrap_template(content, preheader="Vérifiez votre email TAIC Companion")
    send_email(to_email, "Vérifiez votre adresse email", html)


def send_password_reset_email(to_email: str, reset_link: str):
    """Send a branded password reset email with CTA button."""
    content = f"""
<h2 style="color:#1f2937; margin:0 0 16px 0; font-size:20px;">
  R&eacute;initialisation de votre mot de passe
</h2>
<p style="color:#4b5563; font-size:15px; line-height:1.6; margin:0 0 24px 0;">
  Vous avez demand&eacute; la r&eacute;initialisation de votre mot de passe.
  Cliquez sur le bouton ci-dessous pour en choisir un nouveau.
  Ce lien expire dans 15 minutes.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td align="center" style="padding:8px 0 24px 0;">
      <a href="{reset_link}"
         style="display:inline-block; background:linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
                color:#ffffff; text-decoration:none; padding:14px 32px; border-radius:8px;
                font-size:15px; font-weight:600; letter-spacing:0.3px;">
        R&eacute;initialiser mon mot de passe
      </a>
    </td>
  </tr>
</table>
<p style="color:#9ca3af; font-size:13px; line-height:1.5; margin:0;">
  Si vous n'avez pas demand&eacute; cette r&eacute;initialisation, ignorez cet email.
</p>"""

    html = _wrap_template(content, preheader="Réinitialisez votre mot de passe TAIC Companion")
    send_email(to_email, "Réinitialisation de votre mot de passe", html)


def send_invitation_email(to_email: str, company_name: str, join_link: str):
    """Send a branded organization invitation email with CTA button."""
    content = f"""
<h2 style="color:#1f2937; margin:0 0 16px 0; font-size:20px;">
  Vous &ecirc;tes invit&eacute;(e) !
</h2>
<p style="color:#4b5563; font-size:15px; line-height:1.6; margin:0 0 24px 0;">
  Vous avez &eacute;t&eacute; invit&eacute;(e) &agrave; rejoindre
  <strong>{company_name}</strong> sur TAIC Companion.
  Cliquez sur le bouton ci-dessous pour accepter l'invitation.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td align="center" style="padding:8px 0 24px 0;">
      <a href="{join_link}"
         style="display:inline-block; background:linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
                color:#ffffff; text-decoration:none; padding:14px 32px; border-radius:8px;
                font-size:15px; font-weight:600; letter-spacing:0.3px;">
        Rejoindre {company_name}
      </a>
    </td>
  </tr>
</table>
<p style="color:#9ca3af; font-size:13px; line-height:1.5; margin:0;">
  Ce lien expire dans 24 heures. Si vous n'attendiez pas cette invitation, ignorez cet email.
</p>"""

    html = _wrap_template(content, preheader=f"Rejoignez {company_name} sur TAIC Companion")
    send_email(to_email, f"Invitation à rejoindre {company_name}", html)


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences (```html, ```) that LLMs sometimes wrap output in."""
    if not text:
        return text
    cleaned = text.strip()
    # Remove opening fence like ```html or ```
    cleaned = re.sub(r"^```[a-zA-Z]*\s*\n?", "", cleaned)
    # Remove closing fence
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


def generate_recap_html(agent_name: str, recap_content: str) -> str:
    """Wrap LLM-generated recap content in the branded TAIC email template."""
    now = datetime.utcnow().strftime("%d/%m/%Y")
    recap_content = _strip_markdown_fences(recap_content)

    content = f"""
<p style="color:#6b7280; font-size:14px; margin:0 0 20px 0; text-align:center;">
  {agent_name} &mdash; Semaine du {now}
</p>
{recap_content}
<hr style="border:none; border-top:1px solid #e5e7eb; margin:24px 0;">
<p style="color:#9ca3af; font-size:12px; text-align:center; margin:0;">
  G&eacute;n&eacute;r&eacute; automatiquement par TAIC Companion
</p>"""

    return _wrap_template(content, preheader=f"Recap hebdomadaire - {agent_name}")


def send_recap_email(to_email: str | list[str], agent_name: str, html: str):
    """Send the weekly recap email to one or more recipients."""
    subject = f"Recap Hebdomadaire - {agent_name}"
    recipients = to_email if isinstance(to_email, list) else [to_email]
    for recipient in recipients:
        send_email(recipient, subject, html)


def send_agent_share_email(to_email: str, sharer_name: str, agent_name: str, can_edit: bool, chat_link: str):
    """Notify a user that a companion has been shared with them."""
    access_label = "le consulter et le modifier" if can_edit else "le consulter"
    content = f"""
<h2 style="color:#1f2937; margin:0 0 16px 0; font-size:20px;">
  Un nouveau companion a &eacute;t&eacute; partag&eacute; avec vous
</h2>
<p style="color:#4b5563; font-size:15px; line-height:1.6; margin:0 0 24px 0;">
  <strong>{sharer_name}</strong> vient de partager le companion
  <strong>{agent_name}</strong> avec vous. Vous pouvez maintenant {access_label}
  depuis votre tableau de bord.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td align="center" style="padding:8px 0 24px 0;">
      <a href="{chat_link}"
         style="display:inline-block; background:linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
                color:#ffffff; text-decoration:none; padding:14px 32px; border-radius:8px;
                font-size:15px; font-weight:600; letter-spacing:0.3px;">
        Ouvrir {agent_name}
      </a>
    </td>
  </tr>
</table>
<p style="color:#9ca3af; font-size:13px; line-height:1.5; margin:0;">
  Cet email a &eacute;t&eacute; envoy&eacute; parce qu'un membre de votre organisation
  a partag&eacute; un companion avec vous.
</p>"""

    html = _wrap_template(content, preheader=f"{sharer_name} vous a partagé {agent_name}")
    send_email(to_email, f"{sharer_name} vous a partagé un companion", html)


def send_agent_unshare_email(to_email: str, sharer_name: str, agent_name: str):
    """Notify a user that their access to a companion has been revoked."""
    content = f"""
<h2 style="color:#1f2937; margin:0 0 16px 0; font-size:20px;">
  Acc&egrave;s &agrave; un companion r&eacute;voqu&eacute;
</h2>
<p style="color:#4b5563; font-size:15px; line-height:1.6; margin:0 0 24px 0;">
  <strong>{sharer_name}</strong> a retir&eacute; votre acc&egrave;s au companion
  <strong>{agent_name}</strong>. Ce companion n'appara&icirc;tra plus dans votre
  tableau de bord.
</p>
<p style="color:#9ca3af; font-size:13px; line-height:1.5; margin:0;">
  Si vous pensez qu'il s'agit d'une erreur, contactez votre administrateur d'organisation.
</p>"""

    html = _wrap_template(content, preheader=f"Votre accès à {agent_name} a été révoqué")
    send_email(to_email, f"Votre accès à {agent_name} a été révoqué", html)


def send_agent_share_updated_email(to_email: str, sharer_name: str, agent_name: str, can_edit: bool, chat_link: str):
    """Notify a user that their permission on a shared companion has changed."""
    if can_edit:
        heading = "Permissions d'&eacute;dition accord&eacute;es"
        message = (
            f"<strong>{sharer_name}</strong> vous a accord&eacute; la permission de "
            f"<strong>modifier</strong> le companion <strong>{agent_name}</strong>. "
            f"Vous pouvez d&eacute;sormais modifier ses r&eacute;glages et ses documents."
        )
    else:
        heading = "Permissions d'&eacute;dition retir&eacute;es"
        message = (
            f"<strong>{sharer_name}</strong> a retir&eacute; votre permission de "
            f"modifier le companion <strong>{agent_name}</strong>. Vous pouvez toujours "
            f"le consulter mais vous ne pouvez plus le modifier."
        )

    content = f"""
<h2 style="color:#1f2937; margin:0 0 16px 0; font-size:20px;">
  {heading}
</h2>
<p style="color:#4b5563; font-size:15px; line-height:1.6; margin:0 0 24px 0;">
  {message}
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td align="center" style="padding:8px 0 24px 0;">
      <a href="{chat_link}"
         style="display:inline-block; background:linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
                color:#ffffff; text-decoration:none; padding:14px 32px; border-radius:8px;
                font-size:15px; font-weight:600; letter-spacing:0.3px;">
        Ouvrir {agent_name}
      </a>
    </td>
  </tr>
</table>"""

    html = _wrap_template(content, preheader=f"Vos permissions sur {agent_name} ont été modifiées")
    send_email(to_email, f"Vos permissions sur {agent_name} ont été modifiées", html)


def send_feedback_email(from_user_email: str, username: str, feedback_type: str, message: str):
    """Send user feedback to contact@taic.co with Reply-To set to the user's email."""
    type_labels = {
        "bug": "Bug Report",
        "feature": "Feature Request",
        "feedback": "Feedback",
        "other": "Other",
    }
    type_label = type_labels.get(feedback_type, feedback_type)

    content = f"""
<h2 style="color:#1f2937; margin:0 0 16px 0; font-size:20px;">
  {type_label}
</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
  <tr>
    <td style="padding:8px 0; color:#6b7280; font-size:14px; border-bottom:1px solid #e5e7eb;">
      <strong>De :</strong> {username} &lt;{from_user_email}&gt;
    </td>
  </tr>
  <tr>
    <td style="padding:8px 0; color:#6b7280; font-size:14px; border-bottom:1px solid #e5e7eb;">
      <strong>Type :</strong> {type_label}
    </td>
  </tr>
</table>
<div style="background:#f9fafb; border-radius:12px; padding:20px; color:#1f2937; font-size:15px; line-height:1.6; white-space:pre-wrap;">{message}</div>"""

    html = _wrap_template(content, preheader=f"{type_label} de {username}")

    if not SMTP_EMAIL or not SMTP_PASSWORD:
        raise RuntimeError("SMTP_EMAIL or SMTP_PASSWORD not configured")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[TAIC Feedback] {type_label} - {username}"
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_EMAIL}>"
    msg["To"] = SMTP_EMAIL
    msg["Reply-To"] = from_user_email

    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)

    logger.info(f"Feedback email sent from {from_user_email}: {type_label}")


def render_admin_org_request_email(
    requester_email: str,
    requested_name: str,
    approve_url: str,
    reject_url: str,
) -> str:
    """Render the HTML email sent to admin when a new org creation is requested."""
    content = f"""
        <h2 style="color:#111827; font-size:20px; margin:0 0 16px; font-weight:700;">
            Nouvelle demande d'organisation
        </h2>
        <p style="color:#374151; font-size:15px; line-height:1.5; margin:0 0 8px;">
            <strong>{requester_email}</strong> souhaite créer l'organisation&nbsp;:
        </p>
        <p style="color:#111827; font-size:18px; font-weight:600; margin:0 0 24px; padding:12px 16px; background:#f3f4f6; border-radius:8px;">
            {requested_name}
        </p>
        <p style="color:#374151; font-size:14px; line-height:1.5; margin:0 0 24px;">
            Choisissez une action&nbsp;:
        </p>
        <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto;">
            <tr>
                <td style="padding:0 8px;">
                    <a href="{approve_url}"
                       style="display:inline-block; padding:14px 28px; background:#10b981; color:#ffffff;
                              text-decoration:none; border-radius:8px; font-weight:600; font-size:15px;">
                        ✅ Approuver
                    </a>
                </td>
                <td style="padding:0 8px;">
                    <a href="{reject_url}"
                       style="display:inline-block; padding:14px 28px; background:#ef4444; color:#ffffff;
                              text-decoration:none; border-radius:8px; font-weight:600; font-size:15px;">
                        ❌ Refuser
                    </a>
                </td>
            </tr>
        </table>
        <p style="color:#9ca3af; font-size:12px; line-height:1.5; margin:24px 0 0; text-align:center;">
            Les liens pointent vers une page de confirmation — rien n'est exécuté automatiquement.
        </p>
    """
    return _wrap_template(
        content,
        preheader=f"{requester_email} demande '{requested_name}'",
    )


def render_user_org_approved_email(requested_name: str, app_url: str) -> str:
    """Render the HTML email sent to user when their org request is approved."""
    content = f"""
        <h2 style="color:#111827; font-size:20px; margin:0 0 16px; font-weight:700;">
            🎉 Votre organisation a été approuvée
        </h2>
        <p style="color:#374151; font-size:15px; line-height:1.5; margin:0 0 16px;">
            Bonne nouvelle&nbsp;: votre organisation
            <strong>{requested_name}</strong> a été approuvée et est maintenant active.
        </p>
        <p style="color:#374151; font-size:15px; line-height:1.5; margin:0 0 24px;">
            Vous pouvez dès à présent inviter vos collaborateurs et configurer vos intégrations.
        </p>
        <div style="text-align:center; margin:32px 0;">
            <a href="{app_url}"
               style="display:inline-block; padding:14px 32px; background:linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
                      color:#ffffff; text-decoration:none; border-radius:8px; font-weight:600; font-size:15px;">
                Accéder à mon organisation
            </a>
        </div>
    """
    return _wrap_template(content, preheader=f"'{requested_name}' est prête")


def render_user_org_rejected_email(requested_name: str, reason: str | None, app_url: str) -> str:
    """Render the HTML email sent to user when their org request is rejected."""
    reason_block = ""
    if reason:
        reason_block = f"""
        <p style="color:#374151; font-size:14px; line-height:1.5; margin:0 0 16px; padding:12px 16px; background:#fef2f2; border-left:3px solid #ef4444; border-radius:4px;">
            <strong>Raison&nbsp;:</strong> {reason}
        </p>
        """
    content = f"""
        <h2 style="color:#111827; font-size:20px; margin:0 0 16px; font-weight:700;">
            Votre demande d'organisation
        </h2>
        <p style="color:#374151; font-size:15px; line-height:1.5; margin:0 0 16px;">
            Votre demande pour l'organisation <strong>{requested_name}</strong>
            n'a pas pu être acceptée pour le moment.
        </p>
        {reason_block}
        <p style="color:#374151; font-size:15px; line-height:1.5; margin:0 0 24px;">
            Vous pouvez soumettre une nouvelle demande depuis votre espace.
        </p>
        <div style="text-align:center; margin:32px 0;">
            <a href="{app_url}"
               style="display:inline-block; padding:14px 32px; background:#6366f1;
                      color:#ffffff; text-decoration:none; border-radius:8px; font-weight:600; font-size:15px;">
                Soumettre une nouvelle demande
            </a>
        </div>
    """
    return _wrap_template(content, preheader="Information sur votre demande")
