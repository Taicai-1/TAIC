# ⚡ Changement d'Email Rapide - Guide Simplifié

## 🎯 Vous voulez changer: `cohenjeremy046@gmail.com` → `votre-nouvelle-adresse@gmail.com`

---

## 📍 Étape 1: Modifier le Backend (5 minutes)

### Fichier: `backend/main.py`

**Cherchez ligne 2172 et modifiez:**

```python
# ❌ AVANT (ligne 2172-2177)
def send_reset_email(to_email, reset_link):
    msg = MIMEText(f"Voici votre lien de réinitialisation : {reset_link}")
    msg['Subject'] = "Réinitialisation de votre mot de passe"
    msg['From'] = "cohenjeremy046@gmail.com"  # ← Changer ici
    msg['To'] = to_email

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login("cohenjeremy046@gmail.com", "qvoo zfco ryva hwpi")  # ← Et ici
        server.send_message(msg)
```

```python
# ✅ APRÈS
def send_reset_email(to_email, reset_link):
    msg = MIMEText(f"Voici votre lien de réinitialisation : {reset_link}")
    msg['Subject'] = "Réinitialisation de votre mot de passe"
    msg['From'] = "VOTRE_NOUVELLE_ADRESSE@gmail.com"  # ← Nouvelle adresse
    msg['To'] = to_email

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login("VOTRE_NOUVELLE_ADRESSE@gmail.com", "VOTRE_MOT_DE_PASSE_APP")  # ← Nouveaux credentials
        server.send_message(msg)
```

---

## 🔑 Étape 2: Obtenir le Mot de Passe d'Application Gmail (2 minutes)

**IMPORTANT**: N'utilisez PAS votre mot de passe Gmail normal!

### A. Activer la validation en deux étapes

1. Aller sur: https://myaccount.google.com/security
2. Cliquer sur **"Validation en deux étapes"**
3. Suivre les étapes pour l'activer (si pas déjà fait)

### B. Créer un mot de passe d'application

1. Aller sur: https://myaccount.google.com/apppasswords
2. Nom de l'application: **"TAIC Backend SMTP"**
3. Google génère un code de 16 caractères: `abcd efgh ijkl mnop`
4. **Copier ce code SANS les espaces**: `abcdefghijklmnop`
5. Utiliser ce code dans `server.login()`

---

## 🚀 Étape 3: Redéployer (1 minute)

### Option A: Déploiement Cloud Run

```bash
# Depuis la racine du projet
gcloud builds submit --config cloudbuild.yaml
```

### Option B: Test Local

```bash
cd backend
python -m uvicorn main:app --reload --port 8080
```

---

## ✅ Étape 4: Tester (30 secondes)

### Test du Reset Password

1. Aller sur: http://localhost:3000/forgot-password (ou votre URL de production)
2. Entrer votre email
3. Cliquer "Envoyer"
4. **Vérifier**: Un email doit arriver depuis `VOTRE_NOUVELLE_ADRESSE@gmail.com`

---

## 📧 Étape 5: Email Ingest (Optionnel - Si vous utilisez cette feature)

**Si vous voulez changer l'adresse qui REÇOIT les emails avec @tags:**

Cette partie est plus complexe car elle nécessite une Cloud Function Gmail.

**Consultez:** `EMAIL_INGEST_CONFIGURATION.md` pour le guide complet.

**Note**: L'email d'envoi (étapes 1-4) et l'email de réception (ingestion) peuvent être différents.

---

## 🔒 Sécurité - Bonnes Pratiques

### ❌ NE PAS FAIRE

```python
# Ne committez JAMAIS les credentials dans Git
server.login("mon-email@gmail.com", "mon_mot_de_passe")  # ❌ Dangereux!
```

### ✅ RECOMMANDÉ

**Utiliser des variables d'environnement:**

```python
# backend/main.py
import os

def send_reset_email(to_email, reset_link):
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    msg = MIMEText(f"Voici votre lien de réinitialisation : {reset_link}")
    msg['Subject'] = "Réinitialisation de votre mot de passe"
    msg['From'] = smtp_user
    msg['To'] = to_email

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
```

**Puis créer un fichier `.env` (NE PAS COMMITTER):**

```bash
# backend/.env
SMTP_USER=votre-adresse@gmail.com
SMTP_PASSWORD=abcdefghijklmnop
```

**Ajouter à `.gitignore`:**
```
.env
*.env
```

---

## 📊 Checklist Rapide

- [ ] Modifier `msg['From']` dans `main.py` ligne 2172
- [ ] Modifier `server.login()` dans `main.py` ligne 2177
- [ ] Obtenir un mot de passe d'application Gmail
- [ ] Tester localement avec `uvicorn`
- [ ] Déployer sur Cloud Run
- [ ] Tester la fonction reset password
- [ ] Vérifier réception de l'email

---

## 🆘 Problèmes Courants

### Erreur: "Username and Password not accepted"

**Cause**: Mauvais mot de passe ou pas de mot de passe d'application

**Solution**:
1. Vérifier que la validation en deux étapes est activée
2. Générer un NOUVEAU mot de passe d'application
3. Copier sans les espaces

---

### Erreur: "SMTP Authentication Error"

**Cause**: Compte Gmail bloqué ou "Accès moins sécurisé" désactivé

**Solution**:
1. Gmail moderne EXIGE un mot de passe d'application
2. Ne pas essayer d'activer "Accès moins sécurisé" (déprécié)

---

### Email n'arrive pas

**Vérifier**:
1. Dossier spam/indésirables
2. Logs backend: `gcloud run logs read backend`
3. Credentials corrects dans le code

---

## 💡 Conseil Pro

**Pour éviter de hard-coder les credentials**, utilisez **Secret Manager** (GCP):

```bash
# 1. Créer les secrets
echo "votre-adresse@gmail.com" | gcloud secrets create smtp-user --data-file=-
echo "votre_mot_de_passe_app" | gcloud secrets create smtp-password --data-file=-

# 2. Donner accès au service Cloud Run
gcloud secrets add-iam-policy-binding smtp-user \
  --member=serviceAccount:YOUR_SERVICE@YOUR_PROJECT.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor

gcloud secrets add-iam-policy-binding smtp-password \
  --member=serviceAccount:YOUR_SERVICE@YOUR_PROJECT.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor

# 3. Déployer avec les secrets
gcloud run deploy backend \
  --update-secrets SMTP_USER=smtp-user:latest,SMTP_PASSWORD=smtp-password:latest
```

---

## 📞 Besoin d'Aide?

- **Documentation complète**: `EMAIL_INGEST_CONFIGURATION.md`
- **Gmail App Passwords**: https://support.google.com/accounts/answer/185833
- **Cloud Run Secrets**: https://cloud.google.com/run/docs/configuring/secrets

---

## 🎯 TL;DR (30 secondes)

```python
# backend/main.py ligne 2172-2177
# CHANGER:
msg['From'] = "NOUVELLE_ADRESSE@gmail.com"
server.login("NOUVELLE_ADRESSE@gmail.com", "MOT_DE_PASSE_APP")

# OBTENIR MOT DE PASSE APP:
# https://myaccount.google.com/apppasswords

# REDÉPLOYER:
gcloud builds submit --config cloudbuild.yaml
```

**C'est fait! ✅**
