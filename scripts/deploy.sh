# Script de déploiement amélioré pour GCP
#!/bin/bash

set -e

echo "🚀 Déploiement RAG CEO sur Google Cloud Platform"

# Variables
PROJECT_ID=${1:-""}
REGION=${2:-"europe-west1"}

# Fonction pour obtenir les informations du projet
get_project_info() {
    if [ -z "$PROJECT_ID" ]; then
        echo "Entrez votre Project ID GCP:"
        read PROJECT_ID
    fi
    
    echo "📋 Configuration:"
    echo "  Project ID: $PROJECT_ID"
    echo "  Region: $REGION"
    echo
}

# Vérifier les prérequis
check_prerequisites() {
    echo "🔍 Vérification des prérequis..."
    
    # Vérifier gcloud CLI
    if ! command -v gcloud &> /dev/null; then
        echo "❌ gcloud CLI n'est pas installé"
        echo "Installez-le depuis: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi
    
    # Vérifier l'authentification
    if ! gcloud auth list --filter="status:ACTIVE" --format="value(account)" | grep -q .; then
        echo "❌ Vous n'êtes pas authentifié"
        echo "Exécutez: gcloud auth login"
        exit 1
    fi
    
    echo "✅ Prérequis vérifiés"
}

# Configuration du projet
setup_project() {
    echo "📝 Configuration du projet..."
    gcloud config set project $PROJECT_ID
    gcloud config set compute/region $REGION
    
    # Vérifier que les APIs sont activées
    echo "🔧 Vérification des APIs..."
    REQUIRED_APIS=(
        "cloudbuild.googleapis.com"
        "run.googleapis.com"
        "sql-component.googleapis.com"
        "secretmanager.googleapis.com"
    )
    
    for api in "${REQUIRED_APIS[@]}"; do
        if ! gcloud services list --enabled --filter="name:$api" --format="value(name)" | grep -q .; then
            echo "❌ API $api non activée"
            echo "Exécutez d'abord: ./setup-gcp.sh"
            exit 1
        fi
    done
    
    echo "✅ APIs vérifiées"
}

# Obtenir les informations de la base de données
get_database_info() {
    echo "�️ Récupération des informations de la base de données..."
    
    # Obtenir l'IP de l'instance Cloud SQL
    DB_IP=$(gcloud sql instances describe rag-ceo-db --format="value(ipAddresses[0].ipAddress)")
    if [ -z "$DB_IP" ]; then
        echo "❌ Instance Cloud SQL 'rag-ceo-db' non trouvée"
        echo "Exécutez d'abord: ./setup-gcp.sh"
        exit 1
    fi
    
    DATABASE_URL="postgresql://raguser:ragpassword@$DB_IP:5432/ragdb"
    echo "✅ Base de données trouvée: $DB_IP"
}

# Préparer les fichiers de déploiement
prepare_deployment() {
    echo "📦 Préparation du déploiement..."
    
    # Créer un cloudbuild.yaml temporaire avec les bonnes variables
    cat > cloudbuild-temp.yaml << EOF
steps:
  # Build Backend
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/rag-backend', './backend']
  
  # Push Backend
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/rag-backend']
  
  # Build Frontend
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/rag-frontend', './frontend']
  
  # Push Frontend
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/rag-frontend']
  
  # Deploy Backend
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - 'rag-backend'
      - '--image'
      - 'gcr.io/$PROJECT_ID/rag-backend'
      - '--platform'
      - 'managed'
      - '--region'
      - '$REGION'
      - '--allow-unauthenticated'
      - '--port'
      - '8080'
      - '--set-env-vars'
      - 'DATABASE_URL=$DATABASE_URL'
      - '--set-env-vars'
      - 'GOOGLE_CLOUD_PROJECT=$PROJECT_ID'
      - '--set-env-vars'
      - 'ENVIRONMENT=production'
  
  # Deploy Frontend
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - 'rag-frontend'
      - '--image'
      - 'gcr.io/$PROJECT_ID/rag-frontend'
      - '--platform'
      - 'managed'
      - '--region'
      - '$REGION'
      - '--allow-unauthenticated'
      - '--port'
      - '3000'

images:
  - 'gcr.io/$PROJECT_ID/rag-backend'
  - 'gcr.io/$PROJECT_ID/rag-frontend'

substitutions:
  _PROJECT_ID: '$PROJECT_ID'
  _REGION: '$REGION'
  _DATABASE_URL: '$DATABASE_URL'
EOF

    echo "✅ Fichiers de déploiement préparés"
}

# Déployer avec Cloud Build
deploy_application() {
    echo "🔨 Déploiement avec Cloud Build..."
    
    # Remplacer les variables dans le fichier
    sed -i "s/\$PROJECT_ID/$PROJECT_ID/g" cloudbuild-temp.yaml
    sed -i "s/\$REGION/$REGION/g" cloudbuild-temp.yaml
    sed -i "s|\$DATABASE_URL|$DATABASE_URL|g" cloudbuild-temp.yaml
    
    # Déclencher le build
    gcloud builds submit --config cloudbuild-temp.yaml .
    
    # Nettoyer
    rm -f cloudbuild-temp.yaml
    
    echo "✅ Déploiement terminé"
}

# Obtenir les URLs des services
get_service_urls() {
    echo "🔗 Récupération des URLs des services..."
    
    BACKEND_URL=$(gcloud run services describe rag-backend --region=$REGION --format="value(status.url)")
    FRONTEND_URL=$(gcloud run services describe rag-frontend --region=$REGION --format="value(status.url)")
    
    echo "🎉 Déploiement réussi!"
    echo
    echo "📱 URLs de vos services:"
    echo "  Backend API: $BACKEND_URL"
    echo "  Frontend App: $FRONTEND_URL"
    echo "  API Documentation: $BACKEND_URL/docs"
    echo
    echo "🔧 Configuration frontend:"
    echo "  Mettez à jour NEXT_PUBLIC_API_URL vers: $BACKEND_URL"
    echo
}

# Configurer le frontend avec la bonne URL
update_frontend_config() {
    echo "🔧 Mise à jour de la configuration frontend..."
    
    # Redéployer le frontend avec la bonne URL du backend
    gcloud run deploy rag-frontend \
        --image=gcr.io/$PROJECT_ID/rag-frontend \
        --platform=managed \
        --region=$REGION \
        --allow-unauthenticated \
        --port=3000 \
        --set-env-vars=NEXT_PUBLIC_API_URL=$BACKEND_URL
    
    echo "✅ Frontend reconfiguré"
}

# Fonction principale
main() {
    echo "🎯 Déploiement RAG CEO sur GCP"
    echo "=============================="
    
    get_project_info
    check_prerequisites
    setup_project
    get_database_info
    prepare_deployment
    deploy_application
    get_service_urls
    update_frontend_config
    
    echo
    echo "🎉 Déploiement terminé avec succès!"
    echo
    echo "🚀 Testez votre application:"
    echo "  1. Ouvrez: $FRONTEND_URL"
    echo "  2. Créez un compte"
    echo "  3. Téléchargez un document"
    echo "  4. Posez une question"
    echo
    echo "📊 Monitoring:"
    echo "  Console GCP: https://console.cloud.google.com/run?project=$PROJECT_ID"
    echo "  Logs: https://console.cloud.google.com/logs/query?project=$PROJECT_ID"
}

# Exécuter le script
main
