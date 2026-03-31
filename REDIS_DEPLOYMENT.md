# 🚀 Déploiement Redis en Production - Guide Complet

## ✅ Ce qui a été fait

### 1. Redis Memorystore créé
```
✅ Instance: taic-redis
✅ Host: 10.170.82.115
✅ Port: 6379
✅ Network: default
✅ Region: europe-west1-d
✅ State: READY
✅ Tier: BASIC (1GB RAM)
```

### 2. Fichiers de déploiement mis à jour
- ✅ `cloudbuild.yaml` (production) - Ajouté VPC connector + Redis env vars
- ✅ `cloudbuild_dev.yaml` (dev) - Ajouté VPC connector + Redis env vars
- ⚠️ **CORRIGÉ:** `ENVIRONMENT=development` pour cloudbuild_dev.yaml (était incorrectement en production)

---

## 🔧 Prochaines Étapes

### Étape 1: Créer le VPC Connector (5 minutes)

Le VPC Connector permet à Cloud Run (réseau public) d'accéder à Redis (réseau privé).

```bash
# 1. Activer l'API
gcloud services enable vpcaccess.googleapis.com

# 2. Créer le connector
gcloud compute networks vpc-access connectors create redis-connector \
  --region=europe-west1 \
  --network=default \
  --range=10.8.0.0/28 \
  --min-instances=2 \
  --max-instances=3 \
  --machine-type=e2-micro
```

**Attendre 3-5 minutes**, puis vérifier :
```bash
gcloud compute networks vpc-access connectors describe redis-connector \
  --region=europe-west1
```

Vous devriez voir `state: READY`

**Coût:** ~15€/mois (2 instances e2-micro 24/7)

---

### Étape 2: Vérifier les Modifications

Les fichiers suivants ont été modifiés automatiquement :

#### `cloudbuild.yaml` (Production)
```yaml
# Ajouté:
- '--vpc-connector'
- 'redis-connector'

# Dans --set-env-vars, ajouté:
REDIS_HOST=10.170.82.115,REDIS_PORT=6379
```

#### `cloudbuild_dev.yaml` (Dev)
```yaml
# Ajouté:
- '--vpc-connector'
- 'redis-connector'

# CORRIGÉ:
ENVIRONMENT=development  # (était production par erreur)

# Dans --set-env-vars, ajouté:
REDIS_HOST=10.170.82.115,REDIS_PORT=6379
```

---

### Étape 3: Déployer

#### Déploiement DEV (Test)

```bash
# 1. Commit les changements
git add cloudbuild.yaml cloudbuild_dev.yaml
git commit -m "Add Redis Memorystore integration for distributed rate limiting"

# 2. Déployer en dev
gcloud builds submit --config cloudbuild_dev.yaml
```

**Temps:** ~8-12 minutes

---

#### Déploiement PRODUCTION

```bash
# Une fois le dev testé, déployer en production
gcloud builds submit --config cloudbuild.yaml
```

---

### Étape 4: Vérifier le Déploiement

#### 4.1 Vérifier les Variables d'Environnement

```bash
# Backend DEV
gcloud run services describe dev-taic-backend \
  --region=europe-west1 \
  --format="value(spec.template.spec.containers[0].env)"

# Devrait contenir:
# REDIS_HOST=10.170.82.115
# REDIS_PORT=6379
# ENVIRONMENT=development

# Backend PRODUCTION
gcloud run services describe applydi-backend \
  --region=europe-west1 \
  --format="value(spec.template.spec.containers[0].env)"

# Devrait contenir:
# REDIS_HOST=10.170.82.115
# REDIS_PORT=6379
# ENVIRONMENT=production
```

#### 4.2 Vérifier la Connexion Redis

```bash
# Voir les logs Cloud Run
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=applydi-backend" \
  --limit 50 \
  --format "table(timestamp,textPayload)"

# Chercher:
# ✅ "Redis connection successful" (si Redis fonctionne)
# ❌ "Redis connection failed: ..." (si problème)
```

#### 4.3 Tester le Rate Limiting

```bash
# Test en production
# Faire 6 tentatives de login (limite = 5)
for i in {1..6}; do
  curl -X POST https://applydi-backend-XXXXXX.run.app/login \
    -H "Content-Type: application/json" \
    -d '{"username":"test","password":"wrong"}' \
    -w "\nHTTP Status: %{http_code}\n\n"
  sleep 2
done

# La 6ème requête devrait retourner:
# HTTP Status: 429
# {"detail":"Too many login attempts. Please try again in 15 minutes."}
```

#### 4.4 Vérifier Redis Memorystore

```bash
# Se connecter au Redis via Cloud Shell (dans la même région)
gcloud compute ssh redis-test-vm --zone=europe-west1-d

# Dans la VM:
redis-cli -h 10.170.82.115

# Dans redis-cli:
127.0.0.1:6379> KEYS rate_limit:*
1) "rate_limit:auth:35.201.x.x"
2) "rate_limit:public_chat:34.78.x.x"

127.0.0.1:6379> GET rate_limit:auth:35.201.x.x
"5"

127.0.0.1:6379> TTL rate_limit:auth:35.201.x.x
(integer) 847  # Secondes restantes avant expiration
```

---

## 🔍 Architecture Finale

```
                    ┌─────────────────────┐
                    │   Internet          │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Load Balancer      │
                    └──────────┬──────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
┌───────▼────────┐    ┌───────▼────────┐    ┌───────▼────────┐
│  Cloud Run     │    │  Cloud Run     │    │  Cloud Run     │
│  Instance 1    │    │  Instance 2    │    │  Instance 3    │
└───────┬────────┘    └───────┬────────┘    └───────┬────────┘
        │                     │                      │
        │         VPC Connector (redis-connector)    │
        │         10.8.0.0/28                        │
        └──────────────────────┼──────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │      VPC Network (default)                  │
        │                      │                      │
        │      ┌───────────────▼──────────────┐      │
        │      │  Redis Memorystore           │      │
        │      │  10.170.82.115:6379          │      │
        │      │  (rate_limit:* keys)         │      │
        │      └──────────────────────────────┘      │
        │                                             │
        │      ┌──────────────────────────────┐      │
        │      │  Cloud SQL (PostgreSQL)      │      │
        │      │  10.x.x.x:5432               │      │
        │      └──────────────────────────────┘      │
        └─────────────────────────────────────────────┘
```

---

## 📊 Ce que Redis Apporte

| Avant (In-Memory) | Après (Redis) |
|------------------|---------------|
| ❌ Rate limit bypasse si multi-instances | ✅ Rate limit partagé entre instances |
| ❌ Données perdues au restart | ✅ Données persistées |
| ❌ Chaque instance = compteur séparé | ✅ Compteur unique centralisé |
| ❌ Scaling = bypass facile | ✅ Scaling sécurisé |

### Exemple Concret

**Scénario: Attaque brute force login**

#### Sans Redis (AVANT)
```
Attaquant fait 60 tentatives en 1 minute
→ Cloud Run scale de 1 à 3 instances
→ Chaque instance compte indépendamment
→ Résultat: 180 tentatives autorisées (60 × 3)
→ ❌ Rate limiting inefficace
```

#### Avec Redis (APRÈS)
```
Attaquant fait 60 tentatives en 1 minute
→ Cloud Run scale de 1 à 3 instances
→ Toutes les instances partagent le même compteur Redis
→ Après 5 tentatives: HTTP 429 (rate limit)
→ ✅ Attaque bloquée efficacement
```

---

## 🐛 Troubleshooting

### Problème: "Redis connection failed"

**Diagnostic:**
```bash
# 1. Vérifier que le VPC connector existe
gcloud compute networks vpc-access connectors describe redis-connector \
  --region=europe-west1

# 2. Vérifier que Cloud Run utilise le connector
gcloud run services describe applydi-backend \
  --region=europe-west1 \
  --format="value(spec.template.metadata.annotations['run.googleapis.com/vpc-access-connector'])"

# Devrait retourner: redis-connector
```

**Solutions:**
1. VPC connector pas créé → Exécuter Étape 1
2. Cloud Run pas redéployé → Redéployer avec `gcloud builds submit`
3. Mauvaise IP Redis → Vérifier `REDIS_HOST` dans env vars

---

### Problème: Rate limiting ne fonctionne pas

**Diagnostic:**
```bash
# Voir les logs
gcloud logging read "resource.type=cloud_run_revision AND textPayload=~'rate_limit'" \
  --limit 20

# Chercher:
# - "Redis connection failed" → Redis inaccessible
# - "Using fallback" → Redis fonctionne mais erreur ponctuelle
# - Rien → Pas de requêtes de rate limiting
```

**Test Manuel:**
```python
# Dans Cloud Shell (même région)
import redis
r = redis.Redis(host='10.170.82.115', port=6379)
r.ping()  # Devrait retourner True
r.set('test', 'hello')
r.get('test')  # Devrait retourner 'hello'
```

---

### Problème: Coûts élevés

**Coûts attendus:**
- **Redis Memorystore (1GB, BASIC):** ~30€/mois
- **VPC Connector (2 instances e2-micro):** ~15€/mois
- **Total:** ~45€/mois

**Optimisations:**
1. **Redis:** Tier BASIC suffit (pas besoin de HA pour rate limiting)
2. **VPC Connector:** `min-instances=2` suffit (max=3 pour pics)
3. **Alternative:** Cloud Run sur VPC directement (sans connector) = gratuit mais plus complexe

---

## ✅ Checklist Finale

Avant de déployer en production, vérifier :

- [ ] Redis Memorystore créé (`state: READY`)
- [ ] VPC Connector créé (`state: READY`)
- [ ] `cloudbuild.yaml` mis à jour (vpc-connector + REDIS_HOST)
- [ ] `cloudbuild_dev.yaml` mis à jour
- [ ] `ENVIRONMENT=production` en prod, `=development` en dev
- [ ] Git commit + push
- [ ] Déploiement dev testé
- [ ] Rate limiting testé (6 tentatives = 429)
- [ ] Logs vérifiés ("Redis connection successful")
- [ ] Redis Memorystore vérifié (KEYS rate_limit:*)

---

## 📅 Timeline Recommandée

### Aujourd'hui (2h)
1. ✅ Redis créé (fait)
2. ⏳ VPC Connector (5 min + attente 5 min)
3. ⏳ Déploiement DEV (12 min)
4. ⏳ Tests DEV (10 min)

### Demain
1. Déploiement PRODUCTION (12 min)
2. Monitoring 24h
3. Vérifier logs + rate limiting

### Semaine prochaine
- Monitoring continu
- Ajustements si nécessaire
- Phase 2 sécurité (password reset, JWT expiration)

---

## 🎯 Prochaines Commandes à Exécuter

```bash
# 1. Créer VPC Connector
gcloud compute networks vpc-access connectors create redis-connector \
  --region=europe-west1 \
  --network=default \
  --range=10.8.0.0/28 \
  --min-instances=2 \
  --max-instances=3 \
  --machine-type=e2-micro

# 2. Commit changes
git add cloudbuild.yaml cloudbuild_dev.yaml REDIS_DEPLOYMENT.md
git commit -m "feat: Add Redis Memorystore for distributed rate limiting

- Add VPC connector configuration
- Configure Redis host/port in Cloud Run
- Fix ENVIRONMENT variable in dev (was production)
- Enable distributed rate limiting across instances

Redis Host: 10.170.82.115
VPC Connector: redis-connector"

# 3. Déployer DEV
gcloud builds submit --config cloudbuild_dev.yaml

# 4. Tester
# (voir section tests ci-dessus)

# 5. Si OK, déployer PROD
gcloud builds submit --config cloudbuild.yaml
```

---

**Status:** ✅ Prêt pour déploiement
**Prochaine étape:** Créer VPC Connector (commande ci-dessus)
