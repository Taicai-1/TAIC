# Script PowerShell pour déployer RAG CEO sur GCP
# Exécutez ce script en tant qu'administrateur

param(
    [string]$ProjectId = "",
    [string]$OpenAIKey = "",
    [string]$Region = "europe-west1"
)

Write-Host "🚀 Déploiement RAG CEO sur Google Cloud Platform" -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Green

# Fonction pour vérifier si gcloud est installé
function Test-GcloudInstalled {
    try {
        $null = Get-Command gcloud -ErrorAction Stop
        return $true
    }
    catch {
        return $false
    }
}

# Fonction pour obtenir les informations du projet
function Get-ProjectInfo {
    if ([string]::IsNullOrEmpty($ProjectId)) {
        $ProjectId = Read-Host "Entrez votre Project ID GCP (ex: rag-ceo-123456)"
    }
    
    if ([string]::IsNullOrEmpty($OpenAIKey)) {
        $OpenAIKey = Read-Host "Entrez votre clé API OpenAI" -AsSecureString
        $OpenAIKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($OpenAIKey))
    }
    
    Write-Host "`n📋 Configuration:" -ForegroundColor Cyan
    Write-Host "  Project ID: $ProjectId" -ForegroundColor White
    Write-Host "  Region: $Region" -ForegroundColor White
    Write-Host "  OpenAI Key: [HIDDEN]" -ForegroundColor White
    Write-Host ""
    
    return @{
        ProjectId = $ProjectId
        OpenAIKey = $OpenAIKey
        Region = $Region
    }
}

# Fonction pour configurer GCP
function Initialize-GCP {
    param($Config)
    
    Write-Host "🔐 Authentification GCP..." -ForegroundColor Yellow
    gcloud auth login
    
    Write-Host "📝 Configuration du projet..." -ForegroundColor Yellow
    gcloud config set project $Config.ProjectId
    gcloud config set compute/region $Config.Region
    
    Write-Host "🔧 Activation des APIs..." -ForegroundColor Yellow
    $apis = @(
        "cloudbuild.googleapis.com",
        "run.googleapis.com",
        "sql-component.googleapis.com",
        "secretmanager.googleapis.com"
    )
    
    foreach ($api in $apis) {
        Write-Host "  Activation de $api..." -ForegroundColor Gray
        gcloud services enable $api
    }
    
    Write-Host "✅ APIs activées" -ForegroundColor Green
}

# Fonction pour créer les secrets
function New-Secrets {
    param($Config)
    
    Write-Host "🔐 Création des secrets..." -ForegroundColor Yellow
    
    # Créer le secret OpenAI
    $OpenAIKey = $Config.OpenAIKey
    echo $OpenAIKey | gcloud secrets create OPENAI_API_KEY --data-file=-
    
    # Créer le secret JWT
    $JWTSecret = -join ((1..32) | ForEach {'{0:X}' -f (Get-Random -Max 16)})
    echo $JWTSecret | gcloud secrets create JWT_SECRET_KEY --data-file=-
    
    Write-Host "✅ Secrets créés" -ForegroundColor Green
}

# Fonction pour créer la base de données
function New-Database {
    param($Config)
    
    Write-Host "🗄️ Création de la base de données..." -ForegroundColor Yellow
    
    # Créer l'instance Cloud SQL
    gcloud sql instances create rag-ceo-db `
        --database-version=POSTGRES_15 `
        --cpu=1 `
        --memory=3840MB `
        --region=$Config.Region `
        --root-password=admin123 `
        --authorized-networks=0.0.0.0/0
    
    # Créer la base de données
    gcloud sql databases create ragdb --instance=rag-ceo-db
    
    # Créer l'utilisateur
    gcloud sql users create raguser --instance=rag-ceo-db --password=ragpassword
    
    Write-Host "✅ Base de données créée" -ForegroundColor Green
}

# Fonction pour déployer l'application
function Deploy-Application {
    param($Config)
    
    Write-Host "🔨 Déploiement de l'application..." -ForegroundColor Yellow
    
    # Déployer avec Cloud Build
    gcloud builds submit --config cloudbuild.yaml
    
    Write-Host "✅ Application déployée" -ForegroundColor Green
}

# Fonction pour obtenir les URLs
function Get-ServiceUrls {
    param($Config)
    
    Write-Host "🔗 Récupération des URLs..." -ForegroundColor Yellow
    
    $backendUrl = gcloud run services describe rag-backend --region=$Config.Region --format="value(status.url)"
    $frontendUrl = gcloud run services describe rag-frontend --region=$Config.Region --format="value(status.url)"
    
    Write-Host "`n🎉 Déploiement réussi!" -ForegroundColor Green
    Write-Host "=============================" -ForegroundColor Green
    Write-Host "`n📱 URLs de vos services:" -ForegroundColor Cyan
    Write-Host "  Backend API: $backendUrl" -ForegroundColor White
    Write-Host "  Frontend App: $frontendUrl" -ForegroundColor White
    Write-Host "  API Documentation: $backendUrl/docs" -ForegroundColor White
    Write-Host "`n🚀 Testez votre application:" -ForegroundColor Cyan
    Write-Host "  1. Ouvrez: $frontendUrl" -ForegroundColor White
    Write-Host "  2. Créez un compte" -ForegroundColor White
    Write-Host "  3. Téléchargez un document" -ForegroundColor White
    Write-Host "  4. Posez une question" -ForegroundColor White
    Write-Host "`n📊 Monitoring:" -ForegroundColor Cyan
    Write-Host "  Console GCP: https://console.cloud.google.com/run?project=$($Config.ProjectId)" -ForegroundColor White
}

# Fonction principale
function Main {
    try {
        # Vérifier gcloud
        if (-not (Test-GcloudInstalled)) {
            Write-Host "❌ gcloud CLI n'est pas installé" -ForegroundColor Red
            Write-Host "Téléchargez-le depuis: https://cloud.google.com/sdk/docs/install" -ForegroundColor Yellow
            exit 1
        }
        
        Write-Host "✅ gcloud CLI trouvé" -ForegroundColor Green
        
        # Obtenir les informations du projet
        $config = Get-ProjectInfo
        
        # Demander confirmation
        $confirm = Read-Host "Continuer avec cette configuration? (y/N)"
        if ($confirm -ne "y" -and $confirm -ne "Y") {
            Write-Host "❌ Déploiement annulé" -ForegroundColor Red
            exit 0
        }
        
        # Étapes de déploiement
        Initialize-GCP -Config $config
        New-Secrets -Config $config
        New-Database -Config $config
        Deploy-Application -Config $config
        Get-ServiceUrls -Config $config
        
        Write-Host "`n🎉 Déploiement terminé avec succès!" -ForegroundColor Green
        
    }
    catch {
        Write-Host "❌ Erreur lors du déploiement: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Vérifiez les logs et réessayez" -ForegroundColor Yellow
        exit 1
    }
}

# Exécuter le script
Main
