# Rapport d'installation Airbyte sur GCP

**Date :** 5 février 2026
**Objectif :** Mise en place d'une plateforme d'ingestion de données automatisée pour TAIC Companion
**Statut :** ✅ Opérationnel

---

## 1. Infrastructure déployée

### VM Google Cloud Platform

| Paramètre | Valeur |
|-----------|--------|
| **Nom** | airbyte-vm |
| **Région/Zone** | europe-west1-b (Belgique) |
| **Type de machine** | e2-standard-4 (4 vCPU, 16 GB RAM) |
| **Système d'exploitation** | Ubuntu 24.04 LTS Minimal |
| **Disque de démarrage** | 100 GB SSD équilibré (pd-balanced) |
| **IP externe** | 34.52.136.17 (statique réservée) |
| **Tags réseau** | airbyte-vm |
| **Coût estimé** | ~120€/mois |

### Logiciels installés

- **Docker** : 29.2.1
- **Airbyte** : v2.0.1 (via abctl)
- **Kubernetes** : kind (Kubernetes in Docker)
- **Helm Charts** : airbyte 2.0.19, nginx-ingress 4.14.3

---

## 2. Configuration de sécurité

### Pare-feu GCP

**Règle créée :** `allow-airbyte-8000`

```yaml
Direction: INGRESS
Protocole: TCP
Port: 8000
Source IP autorisée: 90.103.144.35/32 (IP du bureau)
Cibles: VMs avec tag "airbyte-vm"
Priorité: 1000
```

⚠️ **IMPORTANT :** L'accès est restreint à l'IP `90.103.144.35` uniquement. Si cette IP change (connexion depuis un autre lieu, redémarrage box internet), il faudra mettre à jour la règle de pare-feu.

**Commande pour mettre à jour l'IP autorisée :**
```bash
gcloud compute firewall-rules update allow-airbyte-8000 --source-ranges=NOUVELLE_IP/32
```

### Authentification Airbyte

**Mode :** Authentification basique activée avec cookies non sécurisés (HTTP)

**Credentials actuels :**
```
URL d'accès: http://34.52.136.17:8000
Password: TGSn3jhF18UdRKwNzefbw4DGxPq8qOPz
Client-Id: c70826be-8d85-4126-a051-00ce5e4c19ab
Client-Secret: JXwQzKmUWxvmkgkTc3oVNJidYywPJPVU
```

**Récupération des credentials :**
```bash
gcloud compute ssh airbyte-vm --zone=europe-west1-b
sudo abctl local credentials
```

---

## 3. Architecture technique

```
┌─────────────────────────────────────────────────────────────┐
│                    Internet (Restreint)                     │
└───────────────────────────┬─────────────────────────────────┘
                            │ IP autorisée: 90.103.144.35
                            │
                ┌───────────▼──────────┐
                │  Pare-feu GCP        │
                │  Port 8000 (TCP)     │
                └───────────┬──────────┘
                            │
                ┌───────────▼──────────────────────────────────┐
                │  VM airbyte-vm (34.52.136.17)                │
                │  Ubuntu 24.04, 4 vCPU, 16 GB RAM             │
                │                                              │
                │  ┌────────────────────────────────────┐      │
                │  │  Kubernetes (kind)                 │      │
                │  │  ┌──────────────────────────────┐  │      │
                │  │  │  Namespace: airbyte-abctl    │  │      │
                │  │  │                              │  │      │
                │  │  │  • airbyte-server            │  │      │
                │  │  │  • airbyte-worker            │  │      │
                │  │  │  • airbyte-db (PostgreSQL)   │  │      │
                │  │  │  • airbyte-cron              │  │      │
                │  │  │  • temporal                  │  │      │
                │  │  │  • nginx-ingress             │  │      │
                │  │  └──────────────────────────────┘  │      │
                │  └────────────────────────────────────┘      │
                └──────────────────────────────────────────────┘
```

### Composants Airbyte déployés

| Service | Rôle | Port |
|---------|------|------|
| **airbyte-server** | API REST et orchestration | 8001 |
| **airbyte-webapp** | Interface web utilisateur | 80 (via ingress) |
| **airbyte-worker** | Exécution des jobs de synchronisation | 9000 |
| **airbyte-db** | Base de données PostgreSQL interne | 5432 |
| **airbyte-cron** | Planification des syncs | - |
| **temporal** | Moteur de workflow | 7233 |
| **nginx-ingress** | Reverse proxy et exposition HTTP | 8000 |

---

## 4. Commandes d'administration

### Gestion du service

```bash
# Se connecter à la VM
gcloud compute ssh airbyte-vm --zone=europe-west1-b

# Vérifier le statut d'Airbyte
sudo abctl local status

# Voir les credentials
sudo abctl local credentials

# Arrêter Airbyte
sudo abctl local uninstall

# Démarrer/Réinstaller Airbyte
sudo abctl local install --low-resource-mode --insecure-cookies

# Voir les logs des conteneurs Docker
sudo docker ps
sudo docker logs <container-id>

# Vérifier les ressources
sudo docker stats
free -h
df -h
```

### Monitoring

```bash
# Vérifier que le port 8000 écoute
sudo ss -tlnp | grep 8000

# Tester l'accès local depuis la VM
curl http://localhost:8000

# Voir les pods Kubernetes
sudo kubectl --kubeconfig=/root/.airbyte/abctl/abctl.kubeconfig get pods -n airbyte-abctl

# Logs d'un pod spécifique
sudo kubectl --kubeconfig=/root/.airbyte/abctl/abctl.kubeconfig logs -n airbyte-abctl <pod-name>
```

---

## 5. Prochaines étapes recommandées

### Configuration initiale

1. **Créer les premières sources de données**
   - Identifier les sources prioritaires (Google Sheets, Salesforce, APIs, etc.)
   - Configurer les connecteurs avec les credentials appropriés
   - Tester les connexions

2. **Configurer la destination PostgreSQL**
   - Utiliser le Cloud SQL de TAIC Companion
   - Créer un schéma dédié : `airbyte_data`
   - Configurer les permissions utilisateur

3. **Mettre en place les pipelines (Connections)**
   - Définir les fréquences de synchronisation
   - Configurer les transformations de données si nécessaire
   - Tester les syncs manuellement avant automatisation

### Intégration avec TAIC Companion

**Étapes d'intégration :**

1. **Créer le schéma de données dans PostgreSQL**
```sql
-- Sur la base TAIC Companion
CREATE SCHEMA IF NOT EXISTS airbyte_data;

-- Table exemple pour données ingérées
CREATE TABLE airbyte_data.customer_documents (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(255),
    source_id VARCHAR(255),
    content TEXT,
    metadata JSONB,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

2. **Modifier le RAG engine** pour inclure les données Airbyte
   - Étendre `backend/rag_engine.py` pour interroger `airbyte_data`
   - Combiner les résultats des documents uploadés + données Airbyte
   - Créer des embeddings pour les nouvelles données

3. **Automatiser le traitement**
   - Script cron pour vectoriser les nouvelles données
   - Endpoint API pour forcer le traitement manuel
   - Monitoring des syncs via webhooks

**Fichier de référence :** `airbyte_integration_example.py` (si créé)

---

## 6. Considérations de sécurité

### Points d'amélioration recommandés

#### Priorité HAUTE

1. **Configurer HTTPS avec certificat SSL**
   - Acheter/configurer un domaine (ex: airbyte.taic-companion.com)
   - Obtenir un certificat Let's Encrypt (gratuit)
   - Configurer Nginx comme reverse proxy HTTPS
   - Désactiver l'accès HTTP direct

2. **Restreindre l'accès par VPN**
   - Mettre en place un VPN d'entreprise
   - Autoriser uniquement les IPs du VPN dans le pare-feu
   - Retirer l'autorisation de l'IP publique individuelle

3. **Utiliser Secret Manager**
   - Stocker les credentials Airbyte dans GCP Secret Manager
   - Ne jamais commiter les credentials dans le code
   - Rotation régulière des mots de passe

#### Priorité MOYENNE

4. **Configurer les sauvegardes**
```bash
# Script de backup à planifier (cron quotidien)
cd /root/.airbyte/abctl/data
tar -czf /backups/airbyte-$(date +%Y%m%d).tar.gz airbyte-volume-db/
gsutil cp /backups/airbyte-*.tar.gz gs://votre-bucket-backup/airbyte/
```

5. **Monitoring et alertes**
   - Configurer Cloud Monitoring pour la VM
   - Alertes CPU/RAM > 80%
   - Alertes disque > 85%
   - Alertes échec de sync Airbyte

6. **Mise à jour régulière**
```bash
# Vérifier la version actuelle
sudo abctl version

# Mettre à jour Airbyte (mensuel recommandé)
sudo abctl local uninstall
sudo abctl local install --low-resource-mode --insecure-cookies
```

---

## 7. Limitation de la configuration actuelle

### ⚠️ Risques identifiés

1. **HTTP non chiffré**
   - Les données transitent en clair sur Internet
   - Risque d'interception des credentials API
   - **Mitigation temporaire :** Accès restreint par IP

2. **Authentification basique**
   - Un seul mot de passe pour tous les utilisateurs
   - Pas de gestion de rôles/permissions
   - **Mitigation :** Mot de passe fort, changement régulier

3. **IP autorisée unique**
   - Si l'IP change (travail à distance, nouveau lieu), accès bloqué
   - **Solution :** VPN d'entreprise ou liste d'IPs autorisées

4. **Pas de haute disponibilité**
   - Instance unique, pas de réplication
   - Si la VM tombe, Airbyte est inaccessible
   - **Acceptable** pour un environnement de développement/test

5. **Stockage local**
   - Données sur le disque de la VM uniquement
   - Pas de sauvegarde automatique configurée
   - **Action requise :** Mettre en place des backups

---

## 8. Coûts d'exploitation

### Coûts mensuels estimés (europe-west1)

| Ressource | Détails | Coût mensuel |
|-----------|---------|--------------|
| VM e2-standard-4 | 4 vCPU, 16 GB RAM, 730h/mois | ~120€ |
| Disque SSD 100GB | pd-balanced | ~17€ |
| IP statique | 1 IP externe | ~3€ |
| Trafic réseau sortant | Estimé 100 GB/mois | ~10€ |
| **Total** | | **~150€/mois** |

### Optimisations possibles

1. **Arrêt nocturne** (économie ~40%)
   - Arrêter la VM de 22h à 7h si pas de syncs nocturnes
   - Économie : ~50€/mois

2. **Disque HDD standard** (pd-standard)
   - Si performance non critique
   - Économie : ~8€/mois

3. **Commitment Use Discount**
   - Engagement 1 an : -30% sur la VM
   - Engagement 3 ans : -50% sur la VM

---

## 9. Ressources et documentation

### Documentation officielle

- **Airbyte Docs :** https://docs.airbyte.com/
- **abctl CLI :** https://docs.airbyte.com/using-airbyte/getting-started/oss-quickstart
- **Connecteurs disponibles :** https://docs.airbyte.com/integrations/ (300+ sources)
- **API Reference :** https://reference.airbyte.com/reference/start

### Support

- **Community Slack :** https://airbyte.com/community
- **GitHub Issues :** https://github.com/airbytehq/airbyte/issues
- **Forum :** https://discuss.airbyte.io/

### Fichiers de configuration

```
/root/.airbyte/abctl/
├── abctl.kubeconfig          # Config Kubernetes
├── data/
│   ├── airbyte-local-pv/     # Volumes persistants
│   └── airbyte-volume-db/    # Base de données PostgreSQL
└── logs/                      # Logs d'installation
```

---

## 10. Checklist de mise en production

Avant de connecter des données sensibles clients :

- [ ] Configurer HTTPS avec certificat SSL
- [ ] Mettre en place un VPN ou restreindre davantage les IPs
- [ ] Configurer les sauvegardes automatiques quotidiennes
- [ ] Tester la restauration depuis backup
- [ ] Configurer Cloud Monitoring et alertes
- [ ] Documenter les procédures de disaster recovery
- [ ] Former l'équipe sur l'utilisation d'Airbyte
- [ ] Établir un calendrier de maintenance et mises à jour
- [ ] Valider la conformité RGPD (localisation des données)
- [ ] Mettre en place un processus d'audit des syncs

---

## Contact et support technique

**Installation réalisée par :** Jeremy
**Date :** 5 février 2026
**Assistance technique :** Claude Code (Anthropic)

**Pour toute question ou incident :**
1. Consulter les logs : `sudo abctl local status` et `sudo docker logs`
2. Vérifier la documentation Airbyte
3. Contacter le support GCP si problème infrastructure

---

**Statut actuel : ✅ OPÉRATIONNEL EN DÉVELOPPEMENT**

*Note : Cette installation est adaptée pour un environnement de développement/test. Une revue de sécurité complète est recommandée avant utilisation en production avec des données sensibles clients.*
