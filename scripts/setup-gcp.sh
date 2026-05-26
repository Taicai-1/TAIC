# Configuration GCP pour RAG CEO
#!/bin/bash

set -e

echo "🚀 Configuration Google Cloud Platform pour RAG CEO"

# Variables
PROJECT_ID=""
REGION="europe-west1"
OPENAI_API_KEY=""

# Fonction pour demander les informations
get_project_info() {
    echo "📋 Configuration du projet GCP"
    echo
    
    if [ -z "$PROJECT_ID" ]; then
        echo "Entrez votre Project ID GCP (ex: rag-ceo-prod-123456):"
        read PROJECT_ID
    fi
    
    if [ -z "$OPENAI_API_KEY" ]; then
        echo "Entrez votre clé API OpenAI:"
        read -s OPENAI_API_KEY
    fi
    
    echo
    echo "Configuration:"
    echo "  Project ID: $PROJECT_ID"
    echo "  Region: $REGION"
    echo "  OpenAI API Key: [HIDDEN]"
    echo
}

# Vérifier gcloud CLI
check_gcloud() {
    if ! command -v gcloud &> /dev/null; then
        echo "❌ gcloud CLI n'est pas installé"
        echo "Installez-le depuis: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi
    echo "✅ gcloud CLI trouvé"
}

# Authentification et configuration du projet
setup_project() {
    echo "🔐 Authentification GCP..."
    gcloud auth login
    
    echo "📝 Configuration du projet..."
    gcloud config set project $PROJECT_ID
    
    echo "📍 Configuration de la région..."
    gcloud config set compute/region $REGION
}

# Activer les APIs nécessaires
enable_apis() {
    echo "🔧 Activation des APIs nécessaires..."
    gcloud services enable cloudbuild.googleapis.com
    gcloud services enable run.googleapis.com
    gcloud services enable sql-component.googleapis.com
    gcloud services enable secretmanager.googleapis.com
    gcloud services enable storage.googleapis.com
    echo "✅ APIs activées"
}

# Créer les secrets
create_secrets() {
    echo "🔐 Création des secrets..."
    
    # OpenAI API Key
    echo $OPENAI_API_KEY | gcloud secrets create OPENAI_API_KEY --data-file=- || echo "Secret OPENAI_API_KEY existe déjà"
    
    # JWT Secret
    JWT_SECRET=$(openssl rand -hex 32)
    echo $JWT_SECRET | gcloud secrets create JWT_SECRET_KEY --data-file=- || echo "Secret JWT_SECRET_KEY existe déjà"
    
    echo "✅ Secrets créés"
}

# Créer la base de données Cloud SQL
create_database() {
    echo "🗄️ Création de la base de données Cloud SQL..."
    
    # Créer l'instance
    gcloud sql instances create rag-ceo-db \
        --database-version=POSTGRES_15 \
        --cpu=1 \
        --memory=3840MB \
        --region=$REGION \
        --root-password=admin123 \
        --authorized-networks=0.0.0.0/0 || echo "Instance existe déjà"
    
    # Créer la base de données
    gcloud sql databases create ragdb --instance=rag-ceo-db || echo "Database existe déjà"
    
    # Créer l'utilisateur
    gcloud sql users create raguser --instance=rag-ceo-db --password=ragpassword || echo "User existe déjà"
    
    echo "✅ Base de données configurée"
}

# Créer un bucket pour les fichiers
create_storage() {
    echo "📦 Création du bucket de stockage (EU - data sovereignty)..."
    gsutil mb -l europe-west1 gs://$PROJECT_ID-documents || echo "Bucket existe déjà"
    echo "✅ Bucket créé en europe-west1"
}

# Donner les permissions nécessaires
setup_permissions() {
    echo "🔑 Configuration des permissions..."
    
    # Obtenir le compte de service Cloud Build
    PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
    CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
    
    # Donner les permissions pour Cloud Run
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$CLOUDBUILD_SA" \
        --role="roles/run.developer"
    
    # Donner les permissions pour Secret Manager
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$CLOUDBUILD_SA" \
        --role="roles/secretmanager.secretAccessor"
    
    echo "✅ Permissions configurées"
}

# Fonction principale
main() {
    echo "🎯 Configuration GCP pour RAG CEO"
    echo "================================"
    
    get_project_info
    check_gcloud
    setup_project
    enable_apis
    create_secrets
    create_database
    create_storage
    setup_permissions
    
    echo
    echo "🎉 Configuration terminée avec succès!"
    echo
    echo "📋 Informations importantes:"
    echo "  Project ID: $PROJECT_ID"
    echo "  Region: $REGION"
    echo "  Database: rag-ceo-db"
    echo "  Storage: gs://$PROJECT_ID-rag-storage"
    echo
    echo "🚀 Prochaine étape: Déployer votre application"
    echo "   Exécutez: ./deploy.sh"
}

# Exécuter le script
main
