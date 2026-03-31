# Fix déploiement Cloud Run - Erreur 500

## 🔴 Problème identifié

L'erreur 500 était causée par des fichiers manquants dans le Dockerfile:
- ❌ `next-i18next.config.js` n'était pas copié
- ❌ `next.config.js` n'était pas copié
- ❌ Configuration i18n mal référencée dans `_app.js`

## ✅ Corrections appliquées

### 1. Dockerfile mis à jour
**Fichier**: `frontend/Dockerfile`

Ajouté les fichiers de configuration manquants:
```dockerfile
COPY --from=builder /app/next-i18next.config.js ./next-i18next.config.js
COPY --from=builder /app/next.config.js ./next.config.js
```

### 2. Configuration i18n améliorée
**Fichier**: `frontend/next-i18next.config.js`

- Utilisation de `path.join(process.cwd(), 'public/locales')` au lieu de `require('path').resolve('./public/locales')`
- Plus robuste pour la production

### 3. App.js mis à jour
**Fichier**: `frontend/pages/_app.js`

- Import explicite de la configuration: `import nextI18NextConfig from '../next-i18next.config.js'`
- Passage de la config à `appWithTranslation(App, nextI18NextConfig)`

## 🚀 Déploiement

### Option 1: Déploiement Cloud Build (recommandé)

```bash
# Commit les changements
git add frontend/Dockerfile frontend/next-i18next.config.js frontend/pages/_app.js
git commit -m "Fix: Add i18n config files to production Dockerfile"
git push

# Lancer le build
gcloud builds submit --config cloudbuild_dev.yaml
```

### Option 2: Build et push manuel

```bash
# 1. Build l'image frontend
cd frontend
docker build -t gcr.io/applydi/applydi-frontend .

# 2. Push l'image
docker push gcr.io/applydi/applydi-frontend

# 3. Déployer sur Cloud Run
gcloud run deploy dev-taic-frontend \
  --image=gcr.io/applydi/applydi-frontend \
  --platform=managed \
  --region=europe-west1 \
  --allow-unauthenticated \
  --port=3000 \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=5 \
  --set-env-vars=NEXT_PUBLIC_API_URL=https://dev-taic-backend-817946451913.europe-west1.run.app
```

## 🧪 Vérification après déploiement

### 1. Vérifier que le service démarre

```bash
# Attendre 2-3 minutes que le déploiement se termine
# Ensuite vérifier l'URL
curl -I https://dev-taic-frontend-817946451913.europe-west1.run.app
```

**Résultat attendu**: `HTTP/2 200` ou `HTTP/2 301/302` (pas 500)

### 2. Tester la page de login

Ouvrir dans le navigateur:
```
https://dev-taic-frontend-817946451913.europe-west1.run.app/login
```

**Vérifications**:
- ✅ Page s'affiche correctement
- ✅ Sélecteur de langue visible (🇫🇷/🇬🇧)
- ✅ Changement de langue fonctionne
- ✅ Pas d'erreur 500

### 3. Tester les URLs localisées

```
# Français (par défaut)
https://dev-taic-frontend-817946451913.europe-west1.run.app/login

# Anglais
https://dev-taic-frontend-817946451913.europe-west1.run.app/en/login
```

### 4. Vérifier les logs Cloud Run

Si problème persiste:

```bash
# Console web
https://console.cloud.google.com/run/detail/europe-west1/dev-taic-frontend/logs

# Ou via gcloud (après avoir fait gcloud auth login)
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=dev-taic-frontend" --limit=100 --format=json
```

Chercher dans les logs:
- ❌ `Error: Cannot find module 'next-i18next.config.js'`
- ❌ `ENOENT: no such file or directory, scandir '/app/public/locales'`
- ❌ Erreurs i18next

## 📋 Checklist de déploiement

Avant de déployer:
- [x] ✅ Dockerfile mis à jour avec les fichiers de config
- [x] ✅ next-i18next.config.js utilise `process.cwd()`
- [x] ✅ _app.js importe et passe la config
- [x] ✅ Build local réussi (`npm run build`)

Après déploiement:
- [ ] Service démarre sans erreur 500
- [ ] Page de login accessible
- [ ] Sélecteur de langue fonctionne
- [ ] URLs `/en/*` fonctionnent
- [ ] Dashboard accessible après connexion

## 🔍 Diagnostic en cas d'erreur persistante

### Si erreur 500 persiste

1. **Vérifier que les fichiers locales existent dans le build**:
```bash
# Se connecter au conteneur Cloud Run (via console web)
ls -la /app/public/locales/fr/
ls -la /app/public/locales/en/

# Doit afficher:
# common.json
# errors.json
# auth.json
# agents.json
# dashboard.json
# chat.json
# teams.json
# profile.json
```

2. **Vérifier que next-i18next.config.js existe**:
```bash
ls -la /app/next-i18next.config.js
cat /app/next-i18next.config.js
```

3. **Vérifier les logs pour l'erreur exacte**:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=dev-taic-frontend AND severity>=ERROR" --limit=50
```

### Problèmes possibles et solutions

| Erreur | Cause | Solution |
|--------|-------|----------|
| `Cannot find module 'next-i18next.config.js'` | Fichier non copié | Vérifier Dockerfile ligne 31-32 |
| `ENOENT: no such file or directory, scandir '/app/public/locales'` | Dossier locales manquant | Vérifier que `public/` est bien copié ligne 27 |
| `i18next: instance.init called without passing in an options object` | Config pas passée à appWithTranslation | Vérifier _app.js |
| Page blanche sans erreur | Build incorrect | Rebuild complet avec `docker build --no-cache` |

## 📝 Fichiers modifiés

### 1. frontend/Dockerfile
```diff
+ COPY --from=builder /app/next-i18next.config.js ./next-i18next.config.js
+ COPY --from=builder /app/next.config.js ./next.config.js
```

### 2. frontend/next-i18next.config.js
```diff
+ const path = require('path')
...
- localePath: require('path').resolve('./public/locales')
+ localePath: path.join(process.cwd(), 'public/locales')
```

### 3. frontend/pages/_app.js
```diff
+ import nextI18NextConfig from '../next-i18next.config.js'
...
- export default appWithTranslation(App)
+ export default appWithTranslation(App, nextI18NextConfig)
```

## 🎯 Résumé

**Problème**: Erreur 500 après ajout de i18n
**Cause**: Fichiers de configuration i18n manquants dans le Dockerfile
**Solution**: Copie explicite de `next-i18next.config.js` et `next.config.js`

**Status après fix**: ✅ Build local réussi, prêt pour déploiement

---

**Prochaine étape**: Déployer avec `gcloud builds submit --config cloudbuild_dev.yaml`
