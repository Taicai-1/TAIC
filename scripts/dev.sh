# Script de développement local
#!/bin/bash

echo "🛠️ Démarrage de l'environnement de développement RAG CEO"

# Vérifier Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker n'est pas installé"
    exit 1
fi

# Vérifier docker-compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose n'est pas installé"
    exit 1
fi

# Créer le fichier .env s'il n'existe pas
if [ ! -f backend/.env ]; then
    echo "📝 Création du fichier .env..."
    cp backend/.env.example backend/.env
    echo "⚠️  N'oubliez pas de configurer votre clé OpenAI dans backend/.env"
fi

# Démarrer les services
echo "🚀 Démarrage des services..."
docker-compose up --build

echo "✅ Services démarrés:"
echo "  - Frontend: http://localhost:3000"
echo "  - Backend: http://localhost:8080"
echo "  - API Docs: http://localhost:8080/docs"
