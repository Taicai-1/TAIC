#!/bin/bash

# Script d'installation automatisée d'Airbyte
# À exécuter sur la VM après connexion SSH

set -e

echo "╔══════════════════════════════════════════════╗"
echo "║    Installation automatique d'Airbyte        ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Vérifier que Docker est installé
if ! command -v docker &> /dev/null; then
    echo "❌ Docker n'est pas installé. Attendez la fin du script de démarrage de la VM."
    exit 1
fi

echo "✅ Docker détecté: $(docker --version)"

# Vérifier Docker Compose
if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose V2 non trouvé"
    exit 1
fi

echo "✅ Docker Compose détecté: $(docker compose version)"
echo ""

# Créer le répertoire Airbyte
AIRBYTE_DIR="/opt/airbyte"
echo "📁 Création du répertoire $AIRBYTE_DIR..."
sudo mkdir -p $AIRBYTE_DIR
sudo chown -R $USER:$USER $AIRBYTE_DIR
cd $AIRBYTE_DIR

# Télécharger le script d'installation
echo "⬇️  Téléchargement du script d'installation Airbyte..."
curl -Ls https://raw.githubusercontent.com/airbytehq/airbyte/master/run-ab-platform.sh -o run-ab-platform.sh
chmod +x run-ab-platform.sh

# Créer un fichier de configuration personnalisé
echo ""
echo "⚙️  Configuration d'Airbyte..."

cat > .env << 'ENV_FILE'
# Configuration Airbyte pour TAIC Companion

# Version d'Airbyte
VERSION=latest

# Port de l'interface web
PORT=8000

# Configuration de la base de données interne
DATABASE_USER=airbyte
DATABASE_PASSWORD=airbyte
DATABASE_DB=airbyte

# Logs
LOG_LEVEL=INFO

# Workers (ajuster selon CPU disponibles)
# e2-standard-2 = 2 workers recommandés
MAX_SYNC_WORKERS=2
MAX_SPEC_WORKERS=2
MAX_CHECK_WORKERS=2
MAX_DISCOVER_WORKERS=2

# Ressources par worker
JOB_MAIN_CONTAINER_CPU_REQUEST=1
JOB_MAIN_CONTAINER_CPU_LIMIT=2
JOB_MAIN_CONTAINER_MEMORY_REQUEST=1Gi
JOB_MAIN_CONTAINER_MEMORY_LIMIT=2Gi

# Timezone
AIRBYTE_TIMEZONE=Europe/Paris

# Désactiver les analytics (optionnel)
TRACKING_STRATEGY=logging
ENV_FILE

echo "✅ Configuration créée dans .env"

# Lancer Airbyte
echo ""
echo "🚀 Lancement d'Airbyte..."
echo "   Cela peut prendre 5-10 minutes (téléchargement des images Docker)"
echo ""

./run-ab-platform.sh -b

# Attendre que les services soient prêts
echo ""
echo "⏳ Attente du démarrage des services..."
sleep 30

# Vérifier que les conteneurs sont lancés
if docker compose ps | grep -q "Up"; then
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║        ✅ Airbyte installé avec succès!      ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""

    # Récupérer l'IP externe
    EXTERNAL_IP=$(curl -s ifconfig.me)

    echo "📋 Informations d'accès:"
    echo "   URL: http://$EXTERNAL_IP:8000"
    echo ""
    echo "   Identifiants par défaut:"
    echo "   Email: airbyte@example.com"
    echo "   Password: password"
    echo ""
    echo "⚠️  IMPORTANT: Changez ces identifiants dès la première connexion!"
    echo ""
    echo "📊 État des conteneurs:"
    docker compose ps
    echo ""
    echo "📖 Commandes utiles:"
    echo "   Voir les logs:      docker compose logs -f"
    echo "   Arrêter Airbyte:    docker compose down"
    echo "   Redémarrer:         docker compose up -d"
    echo "   Mettre à jour:      ./run-ab-platform.sh"
    echo ""
    echo "🔗 Documentation complète: ../AIRBYTE_SETUP_GUIDE.md"

else
    echo "❌ Erreur lors du démarrage d'Airbyte"
    echo "Vérifiez les logs avec: docker compose logs"
    exit 1
fi
