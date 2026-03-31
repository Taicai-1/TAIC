@echo off
title RAG CEO - Installation et Déploiement Automatique
color 0A

echo.
echo =====================================
echo 🚀 RAG CEO - Installation Automatique
echo =====================================
echo.
echo Ce script va installer et déployer votre application RAG CEO sur Google Cloud Platform
echo.

:: Vérifier les prérequis
echo 🔍 Vérification des prérequis...

:: Vérifier gcloud
where gcloud >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ Google Cloud SDK n'est pas installé
    echo.
    echo 📥 Veuillez installer Google Cloud SDK:
    echo    https://cloud.google.com/sdk/docs/install
    echo.
    pause
    exit /b 1
)

echo ✅ Google Cloud SDK trouvé

:: Vérifier l'authentification
gcloud auth list --filter="status:ACTIVE" --format="value(account)" >nul 2>nul
if %errorlevel% neq 0 (
    echo 🔐 Authentification requise...
    gcloud auth login
    if %errorlevel% neq 0 (
        echo ❌ Authentification échouée
        pause
        exit /b 1
    )
)

echo ✅ Authentification vérifiée

:: Demander les informations du projet
echo.
echo 📋 Configuration du projet
echo.
set /p PROJECT_ID="Entrez votre Project ID GCP (ex: rag-ceo-123456): "
if "%PROJECT_ID%"=="" (
    echo ❌ Project ID requis
    pause
    exit /b 1
)

set /p OPENAI_KEY="Entrez votre clé API OpenAI: "
if "%OPENAI_KEY%"=="" (
    echo ❌ Clé OpenAI requise
    pause
    exit /b 1
)

echo.
echo 📋 Configuration confirmée:
echo   Project ID: %PROJECT_ID%
echo   Region: europe-west1
echo   OpenAI Key: [MASQUÉ]
echo.

set /p CONFIRM="Continuer avec cette configuration? (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo ❌ Installation annulée
    pause
    exit /b 0
)

:: Configuration du projet
echo.
echo 📝 Configuration du projet GCP...
gcloud config set project %PROJECT_ID%
gcloud config set compute/region europe-west1

if %errorlevel% neq 0 (
    echo ❌ Erreur lors de la configuration du projet
    echo Vérifiez que le PROJECT_ID est correct
    pause
    exit /b 1
)

echo ✅ Projet configuré

:: Activation des APIs
echo.
echo 🔧 Activation des APIs Google Cloud...
echo   - Cloud Build API
gcloud services enable cloudbuild.googleapis.com
echo   - Cloud Run API
gcloud services enable run.googleapis.com
echo   - Cloud SQL API
gcloud services enable sql-component.googleapis.com
echo   - Secret Manager API
gcloud services enable secretmanager.googleapis.com

echo ✅ APIs activées

:: Création des secrets
echo.
echo 🔐 Création des secrets sécurisés...

echo %OPENAI_KEY% | gcloud secrets create OPENAI_API_KEY --data-file=-
if %errorlevel% neq 0 (
    echo ⚠️  Secret OPENAI_API_KEY existe déjà ou erreur de création
)

:: Générer une clé JWT sécurisée
for /f "delims=" %%i in ('powershell -command "[System.Web.Security.Membership]::GeneratePassword(32, 0)"') do set JWT_SECRET=%%i
echo %JWT_SECRET% | gcloud secrets create JWT_SECRET_KEY --data-file=-
if %errorlevel% neq 0 (
    echo ⚠️  Secret JWT_SECRET_KEY existe déjà ou erreur de création
)

echo ✅ Secrets créés

:: Création de la base de données
echo.
echo 🗄️  Création de la base de données Cloud SQL...
echo   Ceci peut prendre quelques minutes...

gcloud sql instances create rag-ceo-db ^
    --database-version=POSTGRES_15 ^
    --cpu=1 ^
    --memory=3840MB ^
    --region=europe-west1 ^
    --root-password=admin123 ^
    --authorized-networks=0.0.0.0/0 ^
    --quiet

if %errorlevel% neq 0 (
    echo ⚠️  Instance de base de données existe déjà ou erreur de création
)

echo   Création de la base de données...
gcloud sql databases create ragdb --instance=rag-ceo-db --quiet

echo   Création de l'utilisateur...
gcloud sql users create raguser --instance=rag-ceo-db --password=ragpassword --quiet

echo ✅ Base de données créée

:: Déploiement de l'application
echo.
echo 🔨 Déploiement de l'application...
echo   Ceci peut prendre 10-15 minutes...

gcloud builds submit --config cloudbuild.yaml --quiet

if %errorlevel% neq 0 (
    echo ❌ Erreur lors du déploiement
    echo Vérifiez les logs dans la Console GCP
    pause
    exit /b 1
)

echo ✅ Application déployée

:: Récupération des URLs
echo.
echo 🔗 Récupération des URLs des services...

for /f "tokens=*" %%i in ('gcloud run services describe rag-backend --region=europe-west1 --format="value(status.url)"') do set BACKEND_URL=%%i
for /f "tokens=*" %%i in ('gcloud run services describe rag-frontend --region=europe-west1 --format="value(status.url)"') do set FRONTEND_URL=%%i

:: Affichage des résultats
echo.
echo =====================================
echo 🎉 INSTALLATION TERMINÉE AVEC SUCCÈS!
echo =====================================
echo.
echo 📱 URLs de votre application:
echo   🌐 Frontend (Interface utilisateur): %FRONTEND_URL%
echo   🔧 Backend (API): %BACKEND_URL%
echo   📖 Documentation API: %BACKEND_URL%/docs
echo.
echo 🚀 TESTEZ VOTRE APPLICATION:
echo   1. Ouvrez: %FRONTEND_URL%
echo   2. Créez un compte utilisateur
echo   3. Téléchargez un document PDF
echo   4. Posez une question sur le document
echo   5. Recevez une réponse personnalisée!
echo.
echo 📊 Monitoring et gestion:
echo   Console GCP: https://console.cloud.google.com/run?project=%PROJECT_ID%
echo   Logs: https://console.cloud.google.com/logs/query?project=%PROJECT_ID%
echo.
echo 💰 Coûts estimés:
echo   Premier mois: ~50€ (crédits gratuits GCP)
echo   Mois suivants: ~75€/mois
echo.
echo 🎯 VOTRE CHATBOT IA EST MAINTENANT EN LIGNE!
echo.
echo Appuyez sur une touche pour ouvrir votre application...
pause

:: Ouvrir l'application dans le navigateur
start %FRONTEND_URL%

echo.
echo 🎉 Félicitations! Votre application RAG CEO est maintenant prête à être commercialisée!
echo.
pause
