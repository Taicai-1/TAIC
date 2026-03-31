# Recommandations de sécurité - TAIC Companion

## 📊 État actuel de la sécurité

### ✅ Protections en place
1. **JWT Authentication** - Tous les endpoints sensibles protégés par `verify_token`
2. **CORS strict** - Seulement domaines autorisés (taic.ai, localhost)
3. **Validation Pydantic** - Inputs validés et sanitisés
4. **Secrets Manager** - Clés API stockées de façon sécurisée
5. **HTTPS** - Connexions chiffrées via Cloud Run
6. **Password Hashing** - Bcrypt avec salt

### ⚠️ Pourquoi `--allow-unauthenticated` est nécessaire

**Important**: Dans votre architecture (SPA + API REST):
- Le **Frontend** tourne dans le navigateur de l'utilisateur
- Le navigateur fait des appels **directs** au backend
- L'auth Cloud Run (`--no-allow-unauthenticated`) utilise **Google IAM**
- Le navigateur **ne peut pas** s'authentifier via IAM

**Conclusion**: `--allow-unauthenticated` est **nécessaire** pour votre architecture, mais la sécurité est assurée par:
1. JWT au niveau applicatif
2. CORS
3. Rate limiting (à ajouter)

### ❌ Vulnérabilités identifiées

1. **Endpoints de debug exposés** (CRITIQUE)
   - `/test-jwt` - Accessible sans auth
   - `/test-openai` - Accessible sans auth
   - `/debug/whoami` - Accessible sans auth

2. **Pas de rate limiting** (HAUTE)
   - Risque de DDoS
   - Risque de brute force sur `/login`
   - Risque d'abus de l'API

3. **Pas de monitoring des tentatives échouées**
   - Pas de détection d'attaques
   - Pas de bannissement automatique

## 🔒 Solutions recommandées

### 1. Désactiver les endpoints de debug en production (URGENT)

```python
# À ajouter dans main.py
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Désactiver les endpoints de debug en production
if ENVIRONMENT != "production":
    @app.get("/test-jwt")
    async def test_jwt():
        ...
```

### 2. Ajouter du rate limiting (PRIORITAIRE)

**Option A - slowapi (Simple, recommandé)**
```bash
pip install slowapi
```

**Option B - Cloud Armor (Infrastructure, plus robuste)**
- Protection DDoS au niveau GCP
- Rate limiting par IP
- WAF (Web Application Firewall)

### 3. Monitoring et alertes

- Activer Cloud Logging
- Créer des alertes sur:
  - Nombre élevé d'erreurs 401/403
  - Pics de requêtes
  - Erreurs 500

### 4. Headers de sécurité

Ajouter:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Strict-Transport-Security`

## 🚀 Plan d'action recommandé

### Priorité 1 (Urgent - à faire maintenant)
1. ✅ Désactiver endpoints de debug en production
2. ✅ Ajouter rate limiting basique

### Priorité 2 (Important - cette semaine)
1. Configurer Cloud Armor
2. Ajouter headers de sécurité
3. Monitoring et alertes

### Priorité 3 (Amélioration continue)
1. Audit de sécurité régulier
2. Penetration testing
3. Security scanning automatisé

## 📝 Notes

**Backend `--allow-unauthenticated` est OK SI**:
- ✅ Tous endpoints sensibles protégés par JWT (déjà fait)
- ✅ CORS configuré strictement (déjà fait)
- ✅ Rate limiting en place (à faire)
- ✅ Endpoints de debug désactivés en prod (à faire)

**Alternative (plus complexe)**:
- Mettre le backend en privé
- Utiliser Cloud Run Proxy/Gateway
- Le frontend passe par le proxy
- Complexité ++, coût ++
