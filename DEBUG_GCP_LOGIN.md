# Debug - Problème login sur GCP Dev

## 🔴 Situation

- Backend répond 200 OK (connexion réussie)
- Message "Connexion réussie" s'affiche
- **MAIS** la page reste sur `/login` ou `/en/login`

## 🔍 Diagnostic urgent

### 1. Ouvrir DevTools sur le serveur GCP

1. Aller sur: `https://dev-taic-frontend-XXXXX.run.app/en/login`
2. **F12** pour ouvrir DevTools
3. Onglet **Console**
4. Se connecter

### 2. Vérifier quels logs apparaissent

**Si mes nouveaux logs apparaissent** (avec émojis 🔑 🌍 🎯 etc.):
→ Les modifications ont été déployées
→ Le problème est ailleurs

**Si les logs n'apparaissent PAS**:
→ Les modifications n'ont PAS été déployées
→ La version sur GCP est l'ancienne

### 3. Vérifier la version déployée

Pour savoir quelle version est déployée sur GCP, regardez dans les logs Cloud Build:

```bash
gcloud builds list --limit=1
```

Ou vérifiez quel commit a été buildé.

## 💡 Solutions possibles

### Solution A: Les modifications ne sont pas déployées

Si vous avez lancé `gcloud builds submit --config cloudbuild_dev.yaml` SANS avoir commité les changements dans login.js, alors l'ancienne version a été déployée.

**Cloud Build utilise les fichiers du Git, pas les fichiers locaux non commités.**

**Solution**: Vous devez soit:
1. Faire un commit temporaire pour tester
2. Ou utiliser `.gcloudignore` pour forcer l'upload des fichiers locaux

### Solution B: Le problème est différent en production

Si les logs apparaissent mais que ça ne redirige pas:

**Causes possibles**:
- `router.locale` retourne `undefined` en production
- Le cookie NEXT_LOCALE n'est pas défini (problème de domaine/sécurité)
- `window.location.href` est bloqué par un Content Security Policy

**Debug**: Regardez dans la console les valeurs de:
```javascript
console.log("🌍 Current locale:", router.locale);
console.log("📍 Detected locale:", currentLocale);
console.log("🎯 Target path:", targetPath);
```

### Solution C: Utiliser un build local puis push de l'image

Au lieu de `gcloud builds submit`, vous pouvez:

```bash
# Build l'image localement
cd frontend
docker build -t gcr.io/PROJECT_ID/dev-taic-frontend:latest .

# Push l'image
docker push gcr.io/PROJECT_ID/dev-taic-frontend:latest

# Redéployer Cloud Run avec cette image
gcloud run deploy dev-taic-frontend \
  --image gcr.io/PROJECT_ID/dev-taic-frontend:latest \
  --region europe-west1
```

## 🎯 Action immédiate

**ÉTAPE 1**: Vérifiez sur GCP Dev si les logs avec émojis apparaissent dans la console

**Si OUI** → Copiez-moi tous les logs, je vais identifier le problème exact

**Si NON** → Les modifications ne sont pas déployées. Il faut soit:
- Faire un commit Git temporaire
- Ou rebuild avec les fichiers locaux

---

**Question**: Quand vous avez lancé le déploiement GCP, avez-vous fait un commit Git avant ? Ou avez-vous juste lancé `gcloud builds submit` avec les fichiers modifiés mais non commités ?
