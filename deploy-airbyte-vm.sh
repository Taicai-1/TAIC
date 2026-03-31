#!/bin/bash

# Script de déploiement d'une VM Airbyte sur GCP
# Région: europe-west1-b (Belgique)
# Machine: e2-standard-2 (2 vCPUs, 8 GB RAM)

set -e

# Variables de configuration
PROJECT_ID=$(gcloud config get-value project)
ZONE="europe-west1-b"
REGION="europe-west1"
VM_NAME="airbyte-vm"
MACHINE_TYPE="e2-standard-2"
DISK_SIZE="100GB"

echo "🚀 Déploiement de la VM Airbyte"
echo "================================"
echo "Projet: $PROJECT_ID"
echo "Zone: $ZONE"
echo "Machine: $MACHINE_TYPE"
echo ""

# Étape 1: Réserver une IP statique
echo "📍 Étape 1/4: Réservation de l'IP statique..."
gcloud compute addresses create airbyte-static-ip \
  --project=$PROJECT_ID \
  --region=$REGION \
  || echo "IP statique déjà existante"

STATIC_IP=$(gcloud compute addresses describe airbyte-static-ip \
  --region=$REGION \
  --format="get(address)")
echo "✅ IP statique réservée: $STATIC_IP"

# Étape 2: Créer les règles de pare-feu
echo ""
echo "🔒 Étape 2/4: Configuration du pare-feu..."

# Port 8000 pour l'interface web Airbyte
gcloud compute firewall-rules create allow-airbyte-web \
  --project=$PROJECT_ID \
  --direction=INGRESS \
  --priority=1000 \
  --network=default \
  --action=ALLOW \
  --rules=tcp:8000 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=airbyte-server \
  || echo "Règle pare-feu déjà existante"

# Port 22 pour SSH (si pas déjà ouvert)
gcloud compute firewall-rules create allow-ssh \
  --project=$PROJECT_ID \
  --direction=INGRESS \
  --priority=1000 \
  --network=default \
  --action=ALLOW \
  --rules=tcp:22 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=airbyte-server \
  || echo "Règle SSH déjà existante"

echo "✅ Pare-feu configuré"

# Étape 3: Créer le script de démarrage
echo ""
echo "📝 Étape 3/4: Préparation du script de démarrage..."

cat > /tmp/airbyte-startup.sh << 'STARTUP_SCRIPT'
#!/bin/bash

# Mise à jour du système
apt-get update
apt-get upgrade -y

# Installation de Docker
apt-get install -y apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io

# Installation de Docker Compose V2
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Démarrer et activer Docker
systemctl enable docker
systemctl start docker

# Créer un utilisateur pour Airbyte
useradd -m -s /bin/bash airbyte || true
usermod -aG docker airbyte

# Préparer le répertoire Airbyte
mkdir -p /opt/airbyte
chown -R airbyte:airbyte /opt/airbyte

# Message de bienvenue
cat > /etc/motd << 'EOF'
╔══════════════════════════════════════════════╗
║      VM Airbyte - TAIC Companion             ║
╚══════════════════════════════════════════════╝

Pour installer Airbyte, exécutez:
  sudo su - airbyte
  cd /opt/airbyte
  bash <(curl -Ls https://raw.githubusercontent.com/airbytehq/airbyte/master/run-ab-platform.sh)

L'interface sera accessible sur:
  http://$(curl -s ifconfig.me):8000

EOF

echo "✅ Configuration initiale terminée" > /var/log/startup-complete.log
STARTUP_SCRIPT

echo "✅ Script de démarrage créé"

# Étape 4: Créer la VM
echo ""
echo "🖥️  Étape 4/4: Création de la VM..."

gcloud compute instances create $VM_NAME \
  --project=$PROJECT_ID \
  --zone=$ZONE \
  --machine-type=$MACHINE_TYPE \
  --network-interface=address=$STATIC_IP,network-tier=PREMIUM,subnet=default \
  --boot-disk-size=$DISK_SIZE \
  --boot-disk-type=pd-balanced \
  --boot-disk-device-name=$VM_NAME \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --tags=airbyte-server,http-server \
  --metadata-from-file=startup-script=/tmp/airbyte-startup.sh \
  --scopes=https://www.googleapis.com/auth/cloud-platform

echo ""
echo "✅ VM créée avec succès!"
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║         Informations de connexion            ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "IP statique: $STATIC_IP"
echo "Zone: $ZONE"
echo ""
echo "Pour se connecter à la VM:"
echo "  gcloud compute ssh $VM_NAME --zone=$ZONE"
echo ""
echo "⏳ La VM est en cours d'initialisation (3-5 min)..."
echo "   Vérifiez la progression avec:"
echo "   gcloud compute ssh $VM_NAME --zone=$ZONE --command='tail -f /var/log/syslog'"
echo ""
echo "📋 Prochaines étapes:"
echo "  1. Attendez 5 minutes pour l'installation de Docker"
echo "  2. Connectez-vous: gcloud compute ssh $VM_NAME --zone=$ZONE"
echo "  3. Passez en utilisateur airbyte: sudo su - airbyte"
echo "  4. Installez Airbyte: cd /opt/airbyte && bash <(curl -Ls https://raw.githubusercontent.com/airbytehq/airbyte/master/run-ab-platform.sh)"
echo "  5. Accédez à l'interface: http://$STATIC_IP:8000"
echo ""
