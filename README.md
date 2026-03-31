# TAIC Companion - Chatbot IA Personnalisé

## 🎯 Vue d'ensemble

TAIC Companion est une plateforme SaaS permettant aux entreprises de créer des chatbots IA personnalisés basés sur leurs propres documents. Chaque client peut télécharger ses documents et obtenir des réponses précises basées sur son contenu spécifique.

## 🚀 Fonctionnalités

- **Authentification sécurisée** : Système JWT avec gestion multi-utilisateurs
- **Upload de documents** : Support PDF, TXT, DOCX
- **RAG personnalisé** : Réponses basées sur les documents de chaque utilisateur
- **Interface moderne** : Interface utilisateur intuitive avec Tailwind CSS
- **Déploiement cloud** : Prêt pour Google Cloud Platform
- **Monitoring** : Logs et métriques intégrés

## 🏗️ Architecture

```
├── backend/          # API FastAPI
│   ├── auth.py      # Authentification JWT
│   ├── database.py  # Modèles SQLAlchemy
│   ├── main.py      # Application principale
│   ├── rag_engine.py # Logique RAG
│   └── ...
├── frontend/         # Interface Next.js
│   ├── pages/       # Pages React
│   ├── styles/      # Styles Tailwind CSS
│   └── ...
├── cloudbuild.yaml  # Configuration CI/CD
└── docker-compose.yml # Développement local
```

## 📦 Installation

### Prérequis
- Docker et Docker Compose
- Node.js 18+ (pour développement local)
- Python 3.11+ (pour développement local)
- Clé API OpenAI

### Développement local

1. **Cloner le projet**
```bash
git clone <votre-repo>
cd rag-ceo
```

2. **Configuration**
```bash
# Copier les variables d'environnement
cp backend/.env.example backend/.env

# Modifier les variables dans backend/.env
OPENAI_API_KEY=your-openai-api-key
JWT_SECRET_KEY=your-secret-key
```

3. **Démarrer avec Docker Compose**
```bash
docker-compose up --build
```

4. **Accéder à l'application**
- Frontend : http://localhost:3000
- Backend API : http://localhost:8080
- Documentation API : http://localhost:8080/docs

## 🌐 Déploiement sur Google Cloud Platform

### 1. Prérequis GCP

```bash
# Installer Google Cloud SDK
# Créer un projet GCP
gcloud config set project applydi

# Activer les APIs nécessaires
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable sql-component.googleapis.com
gcloud services enable secretmanager.googleapis.com
```

### 2. Configuration des secrets

```bash
# Créer les secrets
gcloud secrets create OPENAI_API_KEY --data-file=<(echo "your-openai-key")
gcloud secrets create JWT_SECRET_KEY --data-file=<(echo "your-jwt-secret")
```

### 3. Base de données

```bash
# Créer une instance Cloud SQL
gcloud sql instances create applydi-db-instance \
  --database-version=POSTGRES_15 \
  --cpu=1 \
  --memory=3840MB \
  --region=europe-west1

# Créer la base de données
gcloud sql databases create applydidb --instance=applydi-db-instance
```

### 4. Déploiement

```bash
# Déclencher le build
gcloud builds submit --config cloudbuild.yaml
```

## 💰 Modèle économique

### Tarification suggérée
- **Starter** : 29€/mois - 1 utilisateur, 100 documents
- **Professional** : 99€/mois - 5 utilisateurs, 500 documents  
- **Enterprise** : 299€/mois - Utilisateurs illimités, documents illimités

### Coûts GCP estimés
- **Cloud Run** : ~20€/mois (2 services)
- **Cloud SQL** : ~50€/mois (instance small)
- **Stockage** : ~5€/mois
- **OpenAI API** : Variable selon usage

## 🔧 Améliorations recommandées

### Court terme (1-2 semaines)
1. **Tests automatisés** : Pytest + Jest
2. **Monitoring avancé** : Google Cloud Monitoring
3. **Cache** : Redis pour les réponses fréquentes
4. **Limitation de débit** : Rate limiting par utilisateur

### Moyen terme (1-2 mois)
1. **Base vectorielle** : Pinecone ou Weaviate
2. **Gestion des équipes** : Organisations et permissions
3. **Analytics** : Tableau de bord usage
4. **API publique** : Endpoints pour intégrations

### Long terme (3-6 mois)
1. **Multi-tenant** : Isolation complète des données
2. **Customisation** : Branding par client
3. **Intégrations** : Slack, Teams, Zapier
4. **Mobile** : Application mobile

## 🚦 Checklist de lancement

- [ ] Tests de charge avec 100+ utilisateurs simultanés
- [ ] Backup automatique des données
- [ ] Monitoring et alertes configurés
- [ ] Documentation API complète
- [ ] Support client (chat, email)
- [ ] Conditions d'utilisation et politique de confidentialité
- [ ] Processus de facturation automatisé
- [ ] Stratégie de marketing et acquisition

## 🔒 Sécurité

- Authentification JWT avec expiration
- Chiffrement des mots de passe (bcrypt)
- CORS configuré
- Validation des inputs
- Secrets dans Google Secret Manager
- Isolation des données par utilisateur

## 📞 Support

Pour toute question technique ou commerciale :
- Email : support@applydi.com
- Documentation : https://docs.applydi.com
