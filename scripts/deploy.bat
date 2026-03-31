@echo off
echo 🚀 Déploiement RAG CEO sur Google Cloud Platform
echo =================================================

:: Vérifier si gcloud est installé
where gcloud >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ gcloud CLI n'est pas installé
    echo Téléchargez-le depuis: https://cloud.google.com/sdk/docs/install
    pause
    exit /b 1
)

echo ✅ gcloud CLI trouvé

:: Demander les informations du projet
set /p PROJECT_ID="Entrez votre Project ID GCP: "
set /p OPENAI_KEY="Entrez votre clé API OpenAI: "

echo.
echo 📋 Configuration:
echo   Project ID: %PROJECT_ID%
echo   Region: europe-west1
echo   OpenAI Key: [HIDDEN]
echo.

set /p CONFIRM="Continuer avec cette configuration? (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo ❌ Déploiement annulé
    pause
    exit /b 0
)

echo.
echo 🔐 Authentification GCP...
gcloud auth login

echo 📝 Configuration du projet...
gcloud config set project %PROJECT_ID%
gcloud config set compute/region europe-west1

echo 🔧 Activation des APIs...
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable sql-component.googleapis.com
gcloud services enable secretmanager.googleapis.com

echo 🔐 Création des secrets...
echo %OPENAI_KEY% | gcloud secrets create OPENAI_API_KEY --data-file=-

:: Générer une clé JWT aléatoirement
for /f "delims=" %%i in ('powershell -command "[guid]::NewGuid().ToString() -replace '-'"') do set JWT_SECRET=%%i
echo %JWT_SECRET% | gcloud secrets create JWT_SECRET_KEY --data-file=-

echo 🗄️ Création de la base de données...
gcloud sql instances create rag-ceo-db --database-version=POSTGRES_15 --cpu=1 --memory=3840MB --region=europe-west1 --root-password=admin123 --authorized-networks=0.0.0.0/0
gcloud sql databases create ragdb --instance=rag-ceo-db
gcloud sql users create raguser --instance=rag-ceo-db --password=ragpassword

echo 🔨 Déploiement de l'application...
gcloud builds submit --config cloudbuild.yaml

echo 🔗 Récupération des URLs...
for /f "tokens=*" %%i in ('gcloud run services describe rag-backend --region=europe-west1 --format="value(status.url)"') do set BACKEND_URL=%%i
for /f "tokens=*" %%i in ('gcloud run services describe rag-frontend --region=europe-west1 --format="value(status.url)"') do set FRONTEND_URL=%%i

echo.
echo 🎉 Déploiement réussi!
echo =============================
echo.
echo 📱 URLs de vos services:
echo   Backend API: %BACKEND_URL%
echo   Frontend App: %FRONTEND_URL%
echo   API Documentation: %BACKEND_URL%/docs
echo.
echo 🚀 Testez votre application:
echo   1. Ouvrez: %FRONTEND_URL%
echo   2. Créez un compte
echo   3. Téléchargez un document
echo   4. Posez une question
echo.
echo 📊 Monitoring:
echo   Console GCP: https://console.cloud.google.com/run?project=%PROJECT_ID%
echo.
echo ✅ Déploiement terminé avec succès!

pause
