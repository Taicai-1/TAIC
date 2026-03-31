# 🚨 Problème Cross-Domain Cookies - Analyse et Solution

## 🔍 Diagnostic du Problème

### Symptômes
- Login backend réussit (200 OK)
- Toast "Connexion réussie" s'affiche
- **Mais pas de redirection vers /agents**
- L'utilisateur reste sur la page login

### Cause Racine: Architecture Cross-Domain

```
Frontend: https://dev-taic-frontend-817946451913.europe-west1.run.app
Backend:  https://dev-taic-backend-817946451913.europe-west1.run.app
          ↑
     Domaines différents (cross-origin)
```

**Les cookies HttpOnly avec `SameSite=Strict` ne fonctionnent PAS en cross-domain !**

---

## 📊 Pourquoi les Cookies Échouent

### Configuration Backend Actuelle

```python
response.set_cookie(
    key="token",
    value=access_token,
    httponly=True,
    secure=True,  # HTTPS only
    samesite="strict",  # ⚠️ PROBLÈME ICI
    max_age=86400,
    path="/"
)
```

### Comportement du Navigateur

```
1. Backend (dev-taic-backend...run.app) définit cookie SameSite=Strict
2. Frontend (dev-taic-frontend...run.app) essaie de lire le cookie
3. Navigateur: "Domaines différents ! Cookie SameSite=Strict bloqué" ❌
4. Cookie n'est JAMAIS envoyé avec les requêtes
```

### Logs Navigateur (DevTools)

```
Set-Cookie was blocked because it had the "SameSite=Strict" attribute
but came from a cross-site response.
```

---

## ⚠️ Options et Leurs Compromis

### Option 1: SameSite=None (❌ Pas Recommandé)

```python
response.set_cookie(
    ...
    samesite="none",  # Permet cross-domain
    secure=True       # Requis avec SameSite=None
)
```

**Problèmes:**
- ❌ Vulnérable aux attaques CSRF cross-site
- ❌ Moins sécurisé que SameSite=Strict
- ❌ Certains navigateurs bloquent quand même

### Option 2: localStorage (✅ Solution Temporaire)

```javascript
localStorage.setItem("token", response.data.access_token);
```

**Avantages:**
- ✅ Fonctionne en cross-domain
- ✅ Simple à implémenter
- ✅ Compatible tous navigateurs

**Inconvénients:**
- ⚠️ Vulnérable XSS (token accessible par JavaScript)
- ⚠️ Moins sécurisé que HttpOnly cookies

### Option 3: Domaine Unique (✅ Solution Long Terme)

Utiliser un seul domaine avec reverse proxy:

```
Frontend: https://taic.ai/
Backend:  https://taic.ai/api/
          ↑
     Même domaine ! Cookies SameSite=Strict fonctionnent
```

**Avantages:**
- ✅ Cookies HttpOnly SameSite=Strict fonctionnent
- ✅ Sécurité maximale
- ✅ Pas de problèmes CORS

**Configuration:**
```
Cloud Load Balancer
├── /     → Frontend (Cloud Run)
└── /api  → Backend (Cloud Run)
```

### Option 4: Proxy Backend URLs (✅ Alternative)

Configurer frontend pour proxifier les requêtes backend:

**next.config.js:**
```javascript
module.exports = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'https://dev-taic-backend-817946451913.europe-west1.run.app/:path*',
      },
    ]
  },
}
```

**Résultat:**
```
Frontend appelle: https://dev-taic-frontend.../api/login
Next.js proxie vers: https://dev-taic-backend.../login
Navigateur voit: Même origine !
```

---

## ✅ Solution Implémentée (Phase 1.5)

**Approche Hybride Temporaire:**

### Backend
```python
# Défini le cookie HttpOnly (pour future migration)
response.set_cookie(...)

# Renvoie aussi le token dans le body (pour localStorage)
return {"access_token": access_token, "token_type": "bearer"}
```

### Frontend
```javascript
// Login.js
const response = await axios.post(`${API_URL}/login`, payload, {
  withCredentials: true  // Prépare pour cookies
});

// TEMPORAIRE: Stocke aussi en localStorage
localStorage.setItem("token", response.data.access_token);
```

### Pourquoi Cette Approche ?

1. **Fonctionne immédiatement** avec cross-domain
2. **Prépare la migration** (cookies déjà configurés)
3. **Pas de downtime** (compatible avec code existant)
4. **Facile à migrer** quand domaine unique disponible

---

## 🔜 Roadmap Migration Cookies

### Phase 1.5 (Actuelle) - localStorage + Cookies Hybrides

```
✅ Backend défini cookies HttpOnly
✅ Frontend utilise localStorage
⚠️ Vulnérable XSS mais fonctionne
```

### Phase 2 - Domaine Unique

**Option A: Cloud Load Balancer**
```bash
# 1. Créer Load Balancer
gcloud compute url-maps create taic-lb

# 2. Configurer routes
gcloud compute url-maps add-path-matcher taic-lb \
  --path-matcher-name=main \
  --default-service=frontend \
  --backend-service-path-rules="/api/*=backend"

# 3. Mapper au domaine
gcloud compute target-https-proxies create taic-proxy \
  --url-map=taic-lb \
  --ssl-certificates=taic-cert

# 4. DNS taic.ai → Load Balancer IP
```

**Résultat:**
```
https://taic.ai/         → Frontend
https://taic.ai/api/     → Backend
↑ Même domaine ! Cookies fonctionnent
```

**Option B: Next.js Rewrites (Plus Simple)**
```javascript
// next.config.js
module.exports = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: process.env.BACKEND_URL + '/:path*',
      },
    ]
  },
}
```

**Frontend:**
```javascript
// Au lieu de:
axios.get('https://dev-taic-backend.../agents')

// Utiliser:
axios.get('/api/agents')  // Proxifié par Next.js
```

### Phase 3 - Migration localStorage → Cookies Uniquement

Une fois domaine unique configuré:

```javascript
// Frontend ne stocke plus rien
const response = await axios.post('/api/login', payload, {
  withCredentials: true
});
// Cookie HttpOnly automatiquement inclus

// Vérification auth
const user = await axios.get('/api/auth/verify', {
  withCredentials: true
});
```

---

## 📋 Checklist Migration Domaine Unique

### Prérequis
- [ ] Acheter domaine `taic.ai`
- [ ] Configurer DNS (Cloudflare ou Google Domains)
- [ ] Certificat SSL pour `taic.ai`

### Option A: Cloud Load Balancer
- [ ] Créer Cloud Load Balancer
- [ ] Configurer backend path `/api/*`
- [ ] Configurer frontend path `/*`
- [ ] SSL certificate pour domaine
- [ ] DNS A record → Load Balancer IP
- [ ] Tester CORS (doit être same-origin)
- [ ] Migrer vers cookies uniquement

### Option B: Next.js Rewrites (Recommandé)
- [ ] Ajouter rewrites dans `next.config.js`
- [ ] Update API calls: `${API_URL}/agents` → `/api/agents`
- [ ] Déployer frontend avec rewrites
- [ ] Tester CORS (doit être same-origin)
- [ ] Migrer vers cookies uniquement

---

## 🧪 Tests Cross-Domain Cookies

### Test 1: Vérifier le Problème

```bash
# Login depuis frontend
curl -X POST https://dev-taic-backend.../login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test"}' \
  -c cookies.txt -v

# Voir Set-Cookie header
cat cookies.txt
# domain=dev-taic-backend...run.app

# Essayer d'utiliser depuis frontend (domaine différent)
curl https://dev-taic-frontend.../api/some-endpoint \
  -b cookies.txt
# Cookie NOT sent (cross-domain) ❌
```

### Test 2: Avec Domaine Unique (après migration)

```bash
# Login depuis taic.ai
curl -X POST https://taic.ai/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test"}' \
  -c cookies.txt -v

# Voir Set-Cookie header
cat cookies.txt
# domain=taic.ai

# Utiliser depuis taic.ai
curl https://taic.ai/api/agents \
  -b cookies.txt
# Cookie sent (same domain) ✅
```

---

## 💰 Coûts Options

### Option A: Cloud Load Balancer
- Load Balancer: ~$18/mois (base)
- Trafic: $0.008/GB (sortie)
- **Total estimé: ~$25-30/mois**

### Option B: Next.js Rewrites
- **Gratuit** (pas d'infra supplémentaire)
- Léger overhead latency (~10-20ms)
- **Total: $0/mois**

**Recommandation:** Commencer avec Option B (Next.js Rewrites)

---

## 📝 Résumé

### Situation Actuelle
- ❌ Cross-domain cookies ne fonctionnent pas
- ✅ localStorage fonctionne (mais moins sécurisé)
- ✅ Approche hybride temporaire implémentée

### Solution Court Terme (Maintenant)
- ✅ localStorage + HttpOnly cookies en parallèle
- ✅ Fonctionnel avec cross-domain
- ⚠️ Vulnérable XSS mais acceptable temporairement

### Solution Long Terme (Phase 2)
- ✅ Domaine unique via Next.js Rewrites
- ✅ Cookies HttpOnly SameSite=Strict uniquement
- ✅ Sécurité maximale (XSS impossible)

---

**Status Actuel:** localStorage temporaire (Phase 1.5)
**Prochaine Étape:** Configurer Next.js rewrites ou Load Balancer
**Timeline:** 2-4 semaines pour migration complète
