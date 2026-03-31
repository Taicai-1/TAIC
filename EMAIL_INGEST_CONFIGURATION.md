# 📧 Configuration de l'Email Ingest - Guide Complet

## 📋 Vue d'Ensemble

Votre système d'ingestion d'emails permet aux utilisateurs d'envoyer des documents par email à leurs agents IA en utilisant des **@tags** dans le sujet.

### Architecture Actuelle

```
┌─────────────────────────────────────────────────────────────────┐
│                      Flux d'Email Ingest                         │
└─────────────────────────────────────────────────────────────────┘

1. Utilisateur envoie email → cohenjeremy046@gmail.com
                              avec sujet: "@sales Nouveau client"

2. Cloud Function Gmail (GCP) → Détecte le nouvel email
                                Extrait: sujet, contenu, pièces jointes

3. Cloud Function → POST /api/emails/ingest (Backend)
                    avec X-API-Key pour authentification

4. Backend → Extrait @tags du sujet: ["@sales"]
           → Trouve les agents avec email_tags = ["@sales"]
           → Crée un document pour chaque agent matché
           → Chunking + Embeddings + Stockage dans FAISS

5. Agent → Peut maintenant répondre aux questions sur le contenu de l'email
```

---

## 🔧 Comment Changer l'Adresse Email

### Étape 1: Identifier les Éléments à Modifier

**Deux adresses email sont configurées**:

1. **Email d'ENVOI** (reset password, notifications):
   - Fichier: `backend/main.py`
   - Ligne: 2172
   - Utilisation: Envoi d'emails sortants (réinitialisation de mot de passe)

2. **Email de RÉCEPTION** (ingestion de documents):
   - Configuration: Cloud Function Gmail (GCP)
   - Utilisation: Réception d'emails avec @tags pour ingestion automatique

---

### Étape 2: Modifier l'Email d'Envoi (SMTP Gmail)

#### A. Dans le Code Backend

**Fichier: `backend/main.py` (ligne 2169-2178)**

**AVANT:**
```python
def send_reset_email(to_email, reset_link):
    msg = MIMEText(f"Voici votre lien de réinitialisation : {reset_link}")
    msg['Subject'] = "Réinitialisation de votre mot de passe"
    msg['From'] = "cohenjeremy046@gmail.com"  # ← Ancienne adresse
    msg['To'] = to_email

    # Utilise un mot de passe d'application Gmail
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login("cohenjeremy046@gmail.com", "qvoo zfco ryva hwpi")  # ← Anciens identifiants
        server.send_message(msg)
```

**APRÈS (exemple avec nouvelle adresse):**
```python
def send_reset_email(to_email, reset_link):
    msg = MIMEText(f"Voici votre lien de réinitialisation : {reset_link}")
    msg['Subject'] = "Réinitialisation de votre mot de passe"
    msg['From'] = "votre-nouvelle-adresse@gmail.com"  # ← Nouvelle adresse
    msg['To'] = to_email

    # Utilise un mot de passe d'application Gmail
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login("votre-nouvelle-adresse@gmail.com", "votre_mot_de_passe_app")  # ← Nouveaux identifiants
        server.send_message(msg)
```

#### B. Générer un Mot de Passe d'Application Gmail

**Important**: N'utilisez JAMAIS votre mot de passe Gmail réel. Utilisez un **mot de passe d'application**.

**Étapes:**
1. Aller sur: https://myaccount.google.com/security
2. Activer la **validation en deux étapes** (si pas déjà fait)
3. Aller dans **Mots de passe des applications**
4. Sélectionner **Application: Autre** et nommer "TAIC Backend SMTP"
5. Google génère un code de 16 caractères (ex: `abcd efgh ijkl mnop`)
6. Copier ce code et l'utiliser dans `server.login()`

**Note**: Retirez les espaces du code généré → `abcdefghijklmnop`

---

### Étape 3: Modifier l'Email de Réception (Cloud Function Gmail)

#### A. Créer/Mettre à Jour la Cloud Function

**Si la Cloud Function n'existe pas encore**, créez-la:

**1. Créer le fichier `cloud_function_gmail/main.py`:**

```python
import os
import base64
import json
import requests
from flask import Request
from google.cloud import logging

# Configuration
BACKEND_API_URL = os.environ.get('BACKEND_API_URL', 'https://backend-xxxx.run.app')
EMAIL_INGEST_API_KEY = os.environ.get('EMAIL_INGEST_API_KEY', '')

# Logger
client = logging.Client()
logger = client.logger('gmail-ingest-function')

def process_gmail_webhook(request: Request):
    """
    Cloud Function déclenchée par Pub/Sub Gmail.
    Extrait le contenu de l'email et l'envoie au backend pour ingestion.
    """
    try:
        # Parser le message Pub/Sub
        envelope = request.get_json()
        if not envelope:
            logger.log_text('No Pub/Sub message received', severity='ERROR')
            return 'Bad Request: no Pub/Sub message received', 400

        if not isinstance(envelope, dict) or 'message' not in envelope:
            logger.log_text('Invalid Pub/Sub message format', severity='ERROR')
            return 'Bad Request: invalid Pub/Sub message format', 400

        pubsub_message = envelope['message']
        message_data = base64.b64decode(pubsub_message['data']).decode('utf-8')

        # Le message contient l'ID de l'email Gmail
        message_info = json.loads(message_data)
        email_address = message_info.get('emailAddress')
        history_id = message_info.get('historyId')

        logger.log_text(f'Processing email from {email_address}, history_id: {history_id}')

        # Récupérer l'email via Gmail API (code simplifié)
        # Dans la vraie implémentation, utilisez google-api-python-client
        # pour récupérer le contenu de l'email

        # Exemple de payload (à adapter selon votre implémentation)
        payload = {
            "source": "gmail",
            "source_id": history_id,
            "title": "Sujet de l'email extrait",  # Extraire du Gmail API
            "content": "Contenu de l'email",      # Extraire du Gmail API
            "metadata": {
                "from_email": "expediteur@example.com",
                "date": "2026-02-01T10:30:00Z"
            }
        }

        # Envoyer au backend
        headers = {
            'Content-Type': 'application/json',
            'X-API-Key': EMAIL_INGEST_API_KEY
        }

        response = requests.post(
            f'{BACKEND_API_URL}/api/emails/ingest',
            json=payload,
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            logger.log_text(f'Email ingested successfully: {response.json()}')
            return 'OK', 200
        else:
            logger.log_text(f'Backend error: {response.status_code} - {response.text}', severity='ERROR')
            return f'Backend error: {response.status_code}', 500

    except Exception as e:
        logger.log_text(f'Error processing email: {str(e)}', severity='ERROR')
        return f'Internal Server Error: {str(e)}', 500
```

**2. Créer `requirements.txt`:**
```txt
google-cloud-logging==3.5.0
google-api-python-client==2.100.0
google-auth-httplib2==0.1.1
google-auth-oauthlib==1.1.0
requests==2.31.0
Flask==3.0.0
```

**3. Déployer la Cloud Function:**
```bash
gcloud functions deploy gmail-ingest-function \
  --runtime python311 \
  --trigger-topic gmail-ingest-topic \
  --entry-point process_gmail_webhook \
  --set-env-vars BACKEND_API_URL=https://backend-xxxx.run.app,EMAIL_INGEST_API_KEY=votre_api_key \
  --region us-central1
```

#### B. Configurer Gmail Push Notifications

**1. Activer l'API Gmail:**
```bash
gcloud services enable gmail.googleapis.com
```

**2. Créer un topic Pub/Sub:**
```bash
gcloud pubsub topics create gmail-ingest-topic
```

**3. Donner les permissions à Gmail:**
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \
  --role=roles/pubsub.publisher
```

**4. Configurer le watch sur votre email:**

Créez un script Python `setup_gmail_watch.py`:
```python
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
import os

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def setup_gmail_watch():
    # Authentification OAuth
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json',  # Téléchargé depuis GCP Console
        SCOPES
    )
    creds = flow.run_local_server(port=0)

    service = build('gmail', 'v1', credentials=creds)

    # Configurer le watch sur l'adresse email
    request_body = {
        'topicName': 'projects/YOUR_PROJECT_ID/topics/gmail-ingest-topic',
        'labelIds': ['INBOX']
    }

    result = service.users().watch(userId='me', body=request_body).execute()
    print(f"Watch configured: {result}")
    print(f"Expiration: {result.get('expiration')}")

if __name__ == '__main__':
    setup_gmail_watch()
```

**Exécutez:**
```bash
python setup_gmail_watch.py
```

**Note**: Le watch expire après 7 jours. Vous devez le renouveler automatiquement (via Cloud Scheduler).

---

### Étape 4: Variables d'Environnement

#### A. Backend (Cloud Run)

**Variables nécessaires:**

```bash
# Dans GCP Secret Manager ou .env
EMAIL_INGEST_API_KEY=votre_cle_api_securisee_32_caracteres_min

# Optionnel (si vous voulez externaliser la config SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=votre-nouvelle-adresse@gmail.com
SMTP_PASSWORD=votre_mot_de_passe_app
```

**Déploiement avec secrets:**
```bash
# Créer le secret
echo "votre_cle_api" | gcloud secrets create email-ingest-api-key --data-file=-

# Donner accès au service Cloud Run
gcloud secrets add-iam-policy-binding email-ingest-api-key \
  --member=serviceAccount:YOUR_SERVICE_ACCOUNT@YOUR_PROJECT.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor

# Redéployer le backend avec le secret
gcloud run deploy backend \
  --update-secrets EMAIL_INGEST_API_KEY=email-ingest-api-key:latest
```

#### B. Cloud Function

**Variables déjà configurées lors du déploiement:**
- `BACKEND_API_URL`: URL de votre backend Cloud Run
- `EMAIL_INGEST_API_KEY`: Même clé que dans le backend

---

### Étape 5: Améliorer la Sécurité (Recommandé)

#### A. Externaliser les Credentials SMTP

**Au lieu de hard-coder dans main.py**, utilisez les variables d'environnement:

```python
# backend/main.py

def send_reset_email(to_email, reset_link):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        logger.error("SMTP credentials not configured")
        raise ValueError("SMTP not configured")

    msg = MIMEText(f"Voici votre lien de réinitialisation : {reset_link}")
    msg['Subject'] = "Réinitialisation de votre mot de passe"
    msg['From'] = smtp_user
    msg['To'] = to_email

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
```

#### B. Rotation de l'API Key

**Créer un système de rotation automatique:**

1. Générer une nouvelle API key tous les 90 jours
2. Mettre à jour Secret Manager
3. Redéployer backend et Cloud Function

---

## 🧪 Tester l'Email Ingest

### Test 1: Test Manuel de l'Endpoint

```bash
# Tester l'endpoint backend directement
curl -X POST https://your-backend.run.app/api/emails/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: votre_cle_api" \
  -d '{
    "source": "gmail",
    "source_id": "test-123",
    "title": "@sales Nouveau prospect - John Doe",
    "content": "Bonjour, je suis intéressé par vos services...",
    "metadata": {
      "from_email": "client@example.com",
      "date": "2026-02-01T10:00:00Z"
    }
  }'
```

**Résultat attendu:**
```json
{
  "success": true,
  "document_ids": [123, 456],
  "agents_matched": 2,
  "agents": [
    {"id": 1, "name": "Sales Assistant"},
    {"id": 5, "name": "Lead Qualifier"}
  ],
  "tags_extracted": ["@sales"],
  "message": "Email ingéré avec succès vers 2 companion(s)"
}
```

### Test 2: Envoyer un Email Réel

**Une fois configuré:**

1. Envoyer un email à: `votre-nouvelle-adresse@gmail.com`
2. Sujet: `@sales Nouveau client potentiel`
3. Contenu: `Informations sur le client...`

**Vérifier dans les logs:**
```bash
# Logs Cloud Function
gcloud functions logs read gmail-ingest-function --limit 50

# Logs Backend
gcloud run logs read backend --limit 50
```

**Vérifier dans l'interface:**
1. Aller sur `/agents`
2. Ouvrir un agent avec le tag `@sales`
3. Onglet "Documents RAG" → Le nouvel email doit apparaître comme document

---

## 📊 Système de Tags Email

### Comment ça Marche

**1. Configurer les tags sur un agent:**

Interface `/agents` → Créer/Modifier agent → Champ "Email Tags"

Exemples:
- `@sales, @commercial`
- `@support, @technique`
- `@finance, @comptabilite`

**2. Envoyer un email avec tags:**

```
À: votre-adresse@gmail.com
Sujet: @sales @urgent Nouveau prospect Fortune 500
```

**3. Backend extrait les tags:**
- Regex: `@([a-zA-Z0-9_-]+)`
- Extrait: `["@sales", "@urgent"]`

**4. Backend trouve les agents:**
- Cherche tous les agents avec `email_tags` contenant `@sales` ou `@urgent`
- Crée un document pour chaque agent matché

**5. Dédoublonnage:**
- Si le même email arrive 2 fois → Vérifie `source_id`
- Ne crée pas de doublon

---

## 🔒 Sécurité

### API Key Generation (Recommandé)

```python
import secrets

# Générer une clé API sécurisée
api_key = secrets.token_urlsafe(32)
print(f"EMAIL_INGEST_API_KEY={api_key}")
```

### Protection Contre les Timing Attacks

Le backend utilise `hmac.compare_digest()` pour comparer les API keys:

```python
# backend/main.py ligne 2635
if not hmac.compare_digest(api_key, expected_key):
    raise HTTPException(status_code=401, detail="Invalid API Key")
```

### Rate Limiting (À Implémenter)

**Recommandation**: Ajouter un rate limiting sur `/api/emails/ingest`:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/emails/ingest")
@limiter.limit("100/hour")  # Max 100 emails par heure
async def ingest_email(...):
    ...
```

---

## 📝 Checklist de Changement d'Email

- [ ] **Backend SMTP (Envoi)**
  - [ ] Modifier `msg['From']` dans `send_reset_email()` (ligne 2172)
  - [ ] Modifier `server.login()` (ligne 2177)
  - [ ] Générer un nouveau mot de passe d'application Gmail
  - [ ] Tester l'envoi d'email (reset password)

- [ ] **Cloud Function Gmail (Réception)**
  - [ ] Créer/déployer la Cloud Function si elle n'existe pas
  - [ ] Configurer Gmail API et Pub/Sub
  - [ ] Exécuter `setup_gmail_watch.py` sur la nouvelle adresse
  - [ ] Configurer le renouvellement automatique du watch (Cloud Scheduler)

- [ ] **Variables d'Environnement**
  - [ ] Créer `EMAIL_INGEST_API_KEY` dans Secret Manager
  - [ ] (Optionnel) Créer `SMTP_USER`, `SMTP_PASSWORD`, etc.
  - [ ] Redéployer backend avec les nouveaux secrets

- [ ] **Tests**
  - [ ] Test endpoint `/api/emails/ingest` avec curl
  - [ ] Envoyer un email réel avec @tags
  - [ ] Vérifier dans les logs Cloud Function
  - [ ] Vérifier dans les logs Backend
  - [ ] Vérifier dans l'interface `/agents` que le document apparaît

- [ ] **Documentation**
  - [ ] Mettre à jour `.env.example`
  - [ ] Documenter la nouvelle adresse email pour l'équipe
  - [ ] Mettre à jour CLAUDE.md si nécessaire

---

## 🆘 Dépannage

### Problème: Les emails n'arrivent pas au backend

**Vérifier:**
1. Cloud Function est déployée: `gcloud functions list`
2. Gmail watch est actif: Vérifier l'expiration dans les logs
3. Pub/Sub topic existe: `gcloud pubsub topics list`
4. Permissions Pub/Sub correctes

**Logs à consulter:**
```bash
# Logs Pub/Sub
gcloud logging read "resource.type=pubsub_topic" --limit 50

# Logs Cloud Function
gcloud functions logs read gmail-ingest-function --limit 50
```

### Problème: Erreur "Invalid API Key"

**Vérifier:**
1. API Key est identique dans Cloud Function ET Backend
2. Pas d'espace ou caractère invisible dans la clé
3. Secret Manager est accessible par le service account

### Problème: Emails ingérés mais pas de documents créés

**Vérifier:**
1. Les @tags dans le sujet sont bien formatés (`@tag` pas `#tag` ou `tag`)
2. Les agents ont bien les email_tags configurés (JSON array)
3. Les tags sont en lowercase (normalisation automatique)

**Logs Backend:**
```bash
gcloud run logs read backend --limit 100 | grep "email"
```

---

## 📚 Ressources

- [Gmail API - Push Notifications](https://developers.google.com/gmail/api/guides/push)
- [Cloud Functions Python](https://cloud.google.com/functions/docs/tutorials/pubsub)
- [Gmail App Passwords](https://support.google.com/accounts/answer/185833)
- [Secret Manager Best Practices](https://cloud.google.com/secret-manager/docs/best-practices)

---

## 🎯 Résumé

**Pour changer l'adresse email d'ingestion:**

1. **Backend (SMTP)**: Modifier `main.py` lignes 2172-2177
2. **Cloud Function**: Reconfigurer Gmail watch sur la nouvelle adresse
3. **Secrets**: Mettre à jour `EMAIL_INGEST_API_KEY` et credentials SMTP
4. **Tester**: Envoyer un email avec @tags et vérifier l'ingestion

**L'architecture actuelle utilise `cohenjeremy046@gmail.com`** pour:
- Envoi d'emails (reset password)
- Réception d'emails pour ingestion (via Cloud Function Gmail)

**Questions?** Consultez les sections de dépannage ou les logs GCP.
