# Guide d'installation Airbyte sur GCP

## Présentation

Ce guide vous accompagne dans le déploiement d'Airbyte sur Google Cloud Platform pour automatiser l'ingestion de données clients dans TAIC Companion.

## Architecture

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│  Sources Data   │ ───> │  Airbyte VM      │ ───> │ TAIC Backend    │
│  (APIs, DBs)    │      │  GCP             │      │ PostgreSQL      │
└─────────────────┘      └──────────────────┘      └─────────────────┘
```

## Prérequis

- Accès GCP avec droits Compute Engine
- gcloud CLI installé et configuré
- Budget: ~60€/mois (VM e2-standard-2 + IP statique + stockage)

## Étape 1: Déployer la VM

Exécutez le script de déploiement:

```bash
# Rendre le script exécutable
chmod +x deploy-airbyte-vm.sh

# Lancer le déploiement
./deploy-airbyte-vm.sh
```

Le script va:
1. Réserver une IP statique
2. Configurer le pare-feu (ports 8000, 22)
3. Créer la VM Ubuntu 22.04
4. Installer Docker et Docker Compose
5. Préparer l'environnement Airbyte

**Durée:** 5-7 minutes

## Étape 2: Installer Airbyte

Une fois la VM créée, connectez-vous:

```bash
# Connexion SSH
gcloud compute ssh airbyte-vm --zone=europe-west1-b

# Passer en utilisateur airbyte
sudo su - airbyte

# Aller dans le répertoire d'installation
cd /opt/airbyte

# Télécharger et installer Airbyte
bash <(curl -Ls https://raw.githubusercontent.com/airbytehq/airbyte/master/run-ab-platform.sh)
```

Airbyte va télécharger les images Docker (~5-10 min selon connexion).

## Étape 3: Accéder à l'interface

Une fois l'installation terminée, accédez à l'interface web:

```
http://VOTRE_IP_STATIQUE:8000
```

Identifiants par défaut:
- **Email:** airbyte@example.com (à changer)
- **Password:** password (à changer)

## Étape 4: Configuration initiale

### 4.1 Sécuriser l'accès

**Option A: Restreindre l'accès par IP (Recommandé)**

```bash
# Remplacer 0.0.0.0/0 par votre IP
gcloud compute firewall-rules update allow-airbyte-web \
  --source-ranges=VOTRE_IP_PUBLIQUE/32
```

**Option B: Configurer un reverse proxy avec authentification**

Créer un fichier `docker-compose.override.yml`:

```yaml
version: "3.8"
services:
  airbyte-webapp:
    environment:
      - BASIC_AUTH_USERNAME=admin
      - BASIC_AUTH_PASSWORD=votremotdepasse
```

### 4.2 Configurer les connexions

Dans l'interface Airbyte:

1. **Sources** → Ajouter les sources de données clients
   - Exemples: Google Sheets, PostgreSQL, REST API, Salesforce, etc.
   - 300+ connecteurs disponibles

2. **Destinations** → Configurer votre base de données
   - Type: PostgreSQL
   - Host: Votre Cloud SQL instance
   - Port: 5432
   - Database: votre_db
   - User/Password: credentials Cloud SQL

3. **Connections** → Créer les pipelines
   - Sélectionner source + destination
   - Choisir les tables/données à synchroniser
   - Définir la fréquence (ex: toutes les heures, quotidien)

## Étape 5: Intégration avec TAIC Companion

### 5.1 Synchroniser vers PostgreSQL

Créez une table dédiée pour les données ingérées:

```sql
-- Dans votre base TAIC Companion
CREATE SCHEMA IF NOT EXISTS airbyte_data;

-- Exemple de table pour données client
CREATE TABLE airbyte_data.customer_documents (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(255),
    content TEXT,
    source VARCHAR(255),
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5.2 Créer un agent qui utilise ces données

Modifiez `rag_engine.py` pour inclure les données Airbyte:

```python
# Ajouter dans la méthode de récupération de contexte
def get_additional_context(self, query: str, agent_id: int):
    """Récupère du contexte depuis les données Airbyte"""
    db = SessionLocal()
    try:
        # Recherche dans les données synchronisées
        results = db.execute(text("""
            SELECT content, source
            FROM airbyte_data.customer_documents
            WHERE customer_id = :agent_id
            AND content ILIKE :query
            LIMIT 5
        """), {"agent_id": agent_id, "query": f"%{query}%"})

        return [row.content for row in results]
    finally:
        db.close()
```

## Cas d'usage typiques

### 1. Ingestion de tickets support (Zendesk/Freshdesk)

- **Source:** Zendesk connector
- **Destination:** PostgreSQL
- **Fréquence:** Temps réel (webhooks) ou toutes les heures
- **Usage:** Agent de support qui connaît l'historique des tickets

### 2. Documentation produit (Notion/Confluence)

- **Source:** Notion API / Confluence
- **Destination:** PostgreSQL
- **Fréquence:** Quotidienne
- **Usage:** Agent documentation technique

### 3. Données CRM (Salesforce/HubSpot)

- **Source:** Salesforce connector
- **Destination:** PostgreSQL
- **Fréquence:** Toutes les 6 heures
- **Usage:** Agent commercial avec contexte client

### 4. Analytics (Google Analytics, Mixpanel)

- **Source:** Google Analytics connector
- **Destination:** PostgreSQL
- **Fréquence:** Quotidienne
- **Usage:** Agent d'analyse de données

## Maintenance

### Vérifier les logs

```bash
# Se connecter à la VM
gcloud compute ssh airbyte-vm --zone=europe-west1-b

# Voir les logs Airbyte
sudo su - airbyte
cd /opt/airbyte
docker compose logs -f
```

### Mettre à jour Airbyte

```bash
sudo su - airbyte
cd /opt/airbyte
docker compose down
bash <(curl -Ls https://raw.githubusercontent.com/airbytehq/airbyte/master/run-ab-platform.sh)
```

### Sauvegarder la configuration

```bash
# Sauvegarder les données Airbyte
cd /opt/airbyte
tar -czf airbyte-backup-$(date +%Y%m%d).tar.gz data/

# Copier vers Cloud Storage
gcloud storage cp airbyte-backup-*.tar.gz gs://votre-bucket/backups/
```

## Monitoring et alertes

### Configurer les alertes GCP

```bash
# Alerte si CPU > 80%
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Airbyte VM High CPU" \
  --condition-display-name="CPU > 80%" \
  --condition-threshold-value=0.8 \
  --condition-threshold-duration=300s
```

### Vérifier l'état des syncs

Dans l'interface Airbyte:
- Dashboard → Voir les syncs récents
- Connections → Vérifier les erreurs
- Logs → Investiguer les problèmes

## Optimisations

### Augmenter la performance

Si vous rencontrez des lenteurs:

```bash
# Upgrade vers e2-standard-4 (4 vCPUs, 16 GB)
gcloud compute instances set-machine-type airbyte-vm \
  --zone=europe-west1-b \
  --machine-type=e2-standard-4

# Redémarrer
gcloud compute instances stop airbyte-vm --zone=europe-west1-b
gcloud compute instances start airbyte-vm --zone=europe-west1-b
```

### Réduire les coûts

```bash
# Planifier l'arrêt nocturne (économie ~50%)
gcloud compute instances add-resource-policies airbyte-vm \
  --resource-policies=stop-weeknights \
  --zone=europe-west1-b
```

## Dépannage

### Airbyte ne démarre pas

```bash
# Vérifier Docker
sudo systemctl status docker

# Vérifier les conteneurs
docker compose ps

# Redémarrer Airbyte
docker compose down
docker compose up -d
```

### Port 8000 inaccessible

```bash
# Vérifier le pare-feu
gcloud compute firewall-rules list | grep airbyte

# Tester depuis la VM
curl http://localhost:8000
```

### Problème de mémoire

```bash
# Vérifier l'utilisation
free -h
docker stats

# Nettoyer les images inutilisées
docker system prune -a
```

## Sécurité

### Checklist de sécurité

- [ ] Changer les identifiants par défaut
- [ ] Restreindre l'accès par IP
- [ ] Activer HTTPS avec Let's Encrypt
- [ ] Sauvegarder régulièrement
- [ ] Monitorer les logs d'accès
- [ ] Mettre à jour Airbyte mensuellement
- [ ] Utiliser Secret Manager pour les credentials

### Configurer HTTPS (optionnel)

```bash
# Installer Caddy comme reverse proxy
sudo apt install -y caddy

# Configurer Caddy
sudo nano /etc/caddy/Caddyfile
```

```
airbyte.votre-domaine.com {
    reverse_proxy localhost:8000
}
```

## Support

- **Documentation Airbyte:** https://docs.airbyte.com/
- **Community Slack:** https://airbyte.com/community
- **GitHub Issues:** https://github.com/airbytehq/airbyte/issues

## Coûts estimés (europe-west1)

| Ressource | Spécification | Coût mensuel |
|-----------|---------------|--------------|
| VM | e2-standard-2 | ~60€ |
| IP statique | 1 IP | ~3€ |
| Stockage | 100 GB SSD | ~17€ |
| **Total** | | **~80€/mois** |

## Prochaines étapes

1. Déployer la VM avec `./deploy-airbyte-vm.sh`
2. Installer Airbyte
3. Configurer vos premières sources de données
4. Créer des agents TAIC qui utilisent ces données
5. Automatiser les syncs quotidiens

Besoin d'aide ? Contactez votre équipe DevOps.
