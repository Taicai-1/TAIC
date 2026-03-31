@echo off
echo Deploiement AppLydi - Simple
echo ===============================

:: Authentification
echo Authentification...
gcloud auth login

:: Configuration
echo Configuration du projet...
gcloud config set project applydi
gcloud config set compute/region europe-west1

:: APIs
echo Activation des APIs...
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable sql-component.googleapis.com
gcloud services enable secretmanager.googleapis.com

:: Secret OpenAI
set /p OPENAI_KEY="Entrez votre cle OpenAI: "
echo %OPENAI_KEY% | gcloud secrets create OPENAI_API_KEY --data-file=-

:: Base de donnees
echo Creation de la base de donnees...
gcloud sql instances create applydi-db --database-version=POSTGRES_15 --cpu=1 --memory=3840MB --region=europe-west1 --root-password=applydi123 --authorized-networks=0.0.0.0/0
gcloud sql databases create applydidb --instance=applydi-db
gcloud sql users create applydiuser --instance=applydi-db --password=applydipass

:: Deploiement
echo Deploiement de l'application...
gcloud builds submit --config cloudbuild.yaml

:: URLs
echo Recuperation des URLs...
gcloud run services describe applydi-backend --region=europe-west1 --format="value(status.url)"
gcloud run services describe applydi-frontend --region=europe-west1 --format="value(status.url)"

echo Deploiement termine!
pause
