@echo off
title AppLydi - Déploiement Automatique sur GCP
color 0A

echo.
echo ========================================
echo 🚀 AppLydi - Déploiement Automatique
echo ========================================
echo.
echo Projet: AppLydi
echo ID Projet: applydi
echo Numéro: 817946451913
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

:: Configuration du projet AppLydi
echo.
echo 📝 Configuration du projet AppLydi...
gcloud config set project applydi
gcloud config set compute/region europe-west1

if %errorlevel% neq 0 (
    echo ❌ Erreur lors de la configuration du projet
    echo Vérifiez que vous avez accès au projet 'applydi'
    pause
    exit /b 1
)

echo ✅ Projet AppLydi configuré

:: Authentification si nécessaire
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

:: Demander la clé OpenAI
echo.
echo 🔑 Configuration des secrets...
set /p OPENAI_KEY="Entrez votre clé API OpenAI: "
if "%OPENAI_KEY%"=="" (
    echo ❌ Clé OpenAI requise
    pause
    exit /b 1
)

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
echo   Nom: applydi-db
echo   Ceci peut prendre quelques minutes...

gcloud sql instances create applydi-db ^
    --database-version=POSTGRES_15 ^
    --cpu=1 ^
    --memory=3840MB ^
    --region=europe-west1 ^
    --root-password=applydi123 ^
    --authorized-networks=0.0.0.0/0 ^
    --quiet

if %errorlevel% neq 0 (
    echo ⚠️  Instance de base de données existe déjà ou erreur de création
)

echo   Création de la base de données applydidb...
gcloud sql databases create applydidb --instance=applydi-db --quiet

echo   Création de l'utilisateur applydiuser...
gcloud sql users create applydiuser --instance=applydi-db --password=applydipass --quiet

echo ✅ Base de données créée

:: Mise à jour du fichier cloudbuild.yaml avec les variables de base de données
echo.
echo 🔧 Configuration de la base de données...

:: Obtenir l'IP de la base de données
for /f "tokens=*" %%i in ('gcloud sql instances describe applydi-db --format="value(ipAddresses[0].ipAddress)"') do set DB_IP=%%i
echo   IP de la base de données: %DB_IP%

:: Déploiement de l'application
echo.
echo 🔨 Déploiement de l'application AppLydi...
echo   Backend: applydi-backend
echo   Frontend: applydi-frontend
echo   Ceci peut prendre 10-15 minutes...

gcloud builds submit --config cloudbuild.yaml --quiet

if %errorlevel% neq 0 (
    echo ❌ Erreur lors du déploiement
    echo Vérifiez les logs dans la Console GCP
    pause
    exit /b 1
)

echo ✅ Application déployée

:: Mise à jour du backend avec les variables de base de données
echo.
echo 🔧 Configuration finale du backend...

gcloud run services update applydi-backend ^
    --region=europe-west1 ^
    --set-env-vars=DATABASE_URL=postgresql://applydiuser:applydipass@%DB_IP%:5432/applydidb ^
    --quiet

:: Récupération des URLs
echo.
echo 🔗 Récupération des URLs des services...

for /f "tokens=*" %%i in ('gcloud run services describe applydi-backend --region=europe-west1 --format="value(status.url)"') do set BACKEND_URL=%%i
for /f "tokens=*" %%i in ('gcloud run services describe applydi-frontend --region=europe-west1 --format="value(status.url)"') do set FRONTEND_URL=%%i

:: Affichage des résultats
echo.
echo ==========================================
echo 🎉 APPLYDI DÉPLOYÉ AVEC SUCCÈS!
echo ==========================================
echo.
echo 📊 Informations du projet:
echo   Nom: AppLydi
echo   ID: applydi
echo   Numéro: 817946451913
echo   Région: europe-west1
echo.
echo 📱 URLs de votre application:
echo   🌐 AppLydi Frontend: %FRONTEND_URL%
echo   🔧 AppLydi Backend: %BACKEND_URL%
echo   📖 Documentation API: %BACKEND_URL%/docs
echo.
echo 🚀 TESTEZ VOTRE APPLICATION APPLYDI:
echo   1. Ouvrez: %FRONTEND_URL%
echo   2. Créez un compte utilisateur
echo   3. Téléchargez un document PDF
echo   4. Posez une question sur le document
echo   5. Recevez une réponse personnalisée!
echo.
echo 📊 Console et monitoring:
echo   Console GCP: https://console.cloud.google.com/run?project=applydi
echo   Logs: https://console.cloud.google.com/logs/query?project=applydi
echo   Cloud SQL: https://console.cloud.google.com/sql/instances?project=applydi
echo.
echo 💰 Coûts estimés:
echo   Premier mois: ~50€ (crédits gratuits GCP)
echo   Mois suivants: ~75€/mois
echo.
echo 🎯 APPLYDI EST MAINTENANT EN LIGNE!
echo.
echo Appuyez sur une touche pour ouvrir AppLydi...
pause

:: Ouvrir l'application dans le navigateur
start %FRONTEND_URL%

echo.
echo 🎉 Félicitations! AppLydi est maintenant prêt à être commercialisé!
echo.
pause
