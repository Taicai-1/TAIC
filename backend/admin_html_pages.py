"""HTML pages served to the admin for org creation request confirmation.

These pages are minimal, brandless-but-clean HTML rendered by FastAPI HTMLResponse.
They exist separately from the Next.js app because they are hit directly from
email links (not through the standard auth flow).
"""

from html import escape


def _base_page(title: str, body_html: str) -> str:
    """Wrap content in a minimal full-page HTML document."""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)} — TAIC Companion</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f3f4f6; margin: 0; padding: 24px;
            min-height: 100vh; display: flex; align-items: center; justify-content: center;
        }}
        .card {{
            background: #fff; max-width: 480px; width: 100%;
            padding: 40px 32px; border-radius: 16px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.07);
            text-align: center;
        }}
        .header {{
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            color: #fff; padding: 20px; border-radius: 12px 12px 0 0;
            margin: -40px -32px 32px; font-size: 18px; font-weight: 700;
        }}
        h1 {{ color: #111827; font-size: 22px; margin: 0 0 16px; }}
        p {{ color: #374151; font-size: 15px; line-height: 1.5; margin: 0 0 16px; }}
        .org-name {{
            display: inline-block; padding: 12px 16px; background: #f3f4f6;
            border-radius: 8px; font-weight: 600; color: #111827; margin: 8px 0;
        }}
        button, .btn {{
            display: inline-block; padding: 14px 28px; font-weight: 600;
            font-size: 15px; border-radius: 8px; border: none; cursor: pointer;
            text-decoration: none;
        }}
        .btn-approve {{ background: #10b981; color: #fff; }}
        .btn-reject {{ background: #ef4444; color: #fff; }}
        .btn-secondary {{ background: #e5e7eb; color: #374151; margin-right: 8px; }}
        .success {{ color: #10b981; }}
        .error {{ color: #ef4444; }}
        textarea {{
            width: 100%; padding: 12px; border: 1px solid #e5e7eb;
            border-radius: 8px; font-family: inherit; font-size: 14px;
            margin: 12px 0; resize: vertical; min-height: 80px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">TAIC Companion — Admin</div>
        {body_html}
    </div>
</body>
</html>"""


def confirm_approve_page(token: str, requester_email: str, requested_name: str, post_url: str) -> str:
    """Page asking admin to confirm the approval of an org creation request."""
    body = f"""
        <h1>Approuver cette organisation ?</h1>
        <p>Demandeur&nbsp;: <strong>{escape(requester_email)}</strong></p>
        <p>Organisation&nbsp;:</p>
        <div class="org-name">{escape(requested_name)}</div>
        <form method="POST" action="{escape(post_url)}">
            <input type="hidden" name="action" value="approve">
            <p style="margin-top: 24px;">
                <a href="/" class="btn btn-secondary">Annuler</a>
                <button type="submit" class="btn btn-approve">✅ Confirmer l'approbation</button>
            </p>
        </form>
    """
    return _base_page("Approuver", body)


def confirm_reject_page(token: str, requester_email: str, requested_name: str, post_url: str) -> str:
    """Page asking admin to confirm the rejection, with optional reason."""
    body = f"""
        <h1>Refuser cette demande ?</h1>
        <p>Demandeur&nbsp;: <strong>{escape(requester_email)}</strong></p>
        <p>Organisation demandée&nbsp;:</p>
        <div class="org-name">{escape(requested_name)}</div>
        <form method="POST" action="{escape(post_url)}">
            <input type="hidden" name="action" value="reject">
            <label style="display:block; text-align:left; margin-top:24px; font-size:14px; color:#374151; font-weight:600;">
                Raison (optionnelle)
            </label>
            <textarea name="reason" placeholder="Ex: Nom non conforme..."></textarea>
            <p>
                <a href="/" class="btn btn-secondary">Annuler</a>
                <button type="submit" class="btn btn-reject">❌ Confirmer le refus</button>
            </p>
        </form>
    """
    return _base_page("Refuser", body)


def success_page(message: str) -> str:
    body = f"""
        <h1 class="success">✅ Action effectuée</h1>
        <p>{escape(message)}</p>
    """
    return _base_page("Succès", body)


def error_page(message: str) -> str:
    body = f"""
        <h1 class="error">❌ Erreur</h1>
        <p>{escape(message)}</p>
    """
    return _base_page("Erreur", body)
