@echo off
title AppLydi - Installation et Déploiement Automatique
color 0A

echo.
echo ===============================================
echo 🚀 AppLydi - Installation Google Cloud SDK
echo ===============================================
echo.

:: Vérifier si gcloud est installé
where gcloud >nul 2>nul
if %errorlevel% equ 0 (
    echo ✅ Google Cloud SDK déjà installé
    goto :deploy
)

echo ⚠️  Google Cloud SDK n'est pas installé
echo.
echo 📥 Téléchargement et installation automatique...
echo    Ceci va prendre quelques minutes...
echo.

:: Créer un dossier temporaire
set TEMP_DIR=%TEMP%\gcloud-install
if not exist "%TEMP_DIR%" mkdir "%TEMP_DIR%"

:: Télécharger l'installateur
echo 📥 Téléchargement de Google Cloud SDK...
powershell -Command "(New-Object Net.WebClient).DownloadFile('https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe', '%TEMP_DIR%\GoogleCloudSDKInstaller.exe')"

if %errorlevel% neq 0 (
    echo ❌ Erreur lors du téléchargement
    echo Veuillez installer manuellement depuis: https://cloud.google.com/sdk/docs/install
    pause
    exit /b 1
)

echo ✅ Téléchargement terminé

:: Lancer l'installateur
echo 🔧 Installation de Google Cloud SDK...
echo    ⚠️  Suivez les instructions dans la fenêtre qui s'ouvre
echo    ⚠️  Redémarrez ce script après l'installation
echo.
start /wait "%TEMP_DIR%\GoogleCloudSDKInstaller.exe"

:: Nettoyer
rmdir /s /q "%TEMP_DIR%"

echo.
echo 🔄 Redémarrage nécessaire...
echo    Fermez cette fenêtre et relancez le script
echo.
pause
exit /b 0

:deploy
echo.
echo 🎯 Google Cloud SDK installé - Démarrage du déploiement...
echo.

:: Appeler le script de déploiement AppLydi
call "%~dp0deploy-applydi.bat"
