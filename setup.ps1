#Requires -Version 5.1
<#
.SYNOPSIS
  GitContainer Cloud — one-command Windows setup.
.DESCRIPTION
  Checks prerequisites, creates .venv, installs requirements, creates .env,
  configures the AI provider (OpenRouter default) and optionally GCP.
  Idempotent: safe to re-run; never overwrites existing .env values.
  Cloud (gcloud/GCP) problems are warnings — setup still completes.
#>
$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ScriptDir

function Write-Step($text) { Write-Host $text }
function Write-Ok($text) { Write-Host "  [OK] $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  [!!] $text" -ForegroundColor Yellow }
function Write-Fail($text) { Write-Host "  [XX] $text" -ForegroundColor Red }
function Write-Action($text) { Write-Host "  ---> $text" -ForegroundColor Cyan }

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Read-SecretValue($prompt) {
    # Masked input on interactive consoles; plain read when stdin is
    # redirected (pipes/CI). The value is never written to output.
    if (-not [Console]::IsInputRedirected) {
        try {
            $secure = Read-Host $prompt -AsSecureString -ErrorAction Stop
            $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
            try {
                return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
            } finally {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
            }
        } catch { }
    }
    return Read-Host $prompt
}

function Get-DotEnvValue($path, $key) {
    if (-not (Test-Path -LiteralPath $path)) { return "" }
    $line = Get-Content -LiteralPath $path | Where-Object { $_ -match "^\s*$key\s*=" } | Select-Object -First 1
    if (-not $line) { return "" }
    return ($line -split "=", 2)[1].Trim()
}

function Set-DotEnvValue($path, $key, $value) {
    # Upsert one KEY=value line, preserving everything else. Never prints $value.
    if (-not (Test-Path -LiteralPath $path)) { New-Item -ItemType File -Path $path -Force | Out-Null }
    $lines = Get-Content -LiteralPath $path
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^\s*$key\s*=" -and -not $found) { $found = $true; "$key=$value" } else { $line }
    }
    if (-not $found) { $out += "$key=$value" }
    Set-Content -LiteralPath $path -Value $out -Encoding UTF8
}

Write-Host ""
Write-Host "========================================="
Write-Host "        GitContainer Cloud Setup"
Write-Host "========================================="
Write-Host ""

# [1/8] Python
Write-Step "[1/8] Python"
$pyOk = $false
if (Test-Command "python") {
    $ver = (& python --version 2>&1).ToString()
    if ($ver -match "Python (\d+)\.(\d+)") {
        if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 9)) {
            Write-Ok $ver; $pyOk = $true
        } else { Write-Fail "$ver (need 3.9+)"; }
    } else { Write-Fail "Could not parse version: $ver" }
} else { Write-Fail "Python not found. Install from https://www.python.org/downloads/ (tick 'Add to PATH')." }
if (-not $pyOk) { Write-Host ""; Write-Fail "Setup cannot continue without Python 3.9+."; exit 1 }

# [2/8] Git
Write-Step "[2/8] Git"
if (Test-Command "git") { Write-Ok ((& git --version 2>&1).ToString()) }
else { Write-Warn "Git not found. Install from https://git-scm.com/downloads (needed to analyze repositories)." }

# [3/8] Docker
Write-Step "[3/8] Docker"
if (Test-Command "docker") {
    Write-Ok ((& docker --version 2>&1).ToString())
    & docker info 2>$null | Out-Null
    if ($?) { Write-Ok "Docker daemon is running." }
    else {
        Write-Warn "Docker Desktop is installed but not running."
        Write-Action "Please start Docker Desktop, then press ENTER to retry."
        [void][System.Console]::ReadLine()
        & docker info 2>$null | Out-Null
        if ($?) { Write-Ok "Docker daemon is running." }
        else { Write-Warn "Docker daemon still unreachable. Local image builds will fail until Docker Desktop runs." }
    }
} else { Write-Warn "Docker not found. Install Docker Desktop to build images: https://www.docker.com/products/docker-desktop/" }

# [4/8] Google Cloud CLI
Write-Step "[4/8] Google Cloud CLI"
$gcloudOk = $false
if (Test-Command "gcloud") {
    Write-Ok ((& gcloud --version 2>&1 | Select-Object -First 1).ToString())
    $gcloudOk = $true
} else {
    Write-Warn "gcloud not found. Required ONLY for Cloud Run deployment."
    Write-Action "Install: https://cloud.google.com/sdk/docs/install then re-run setup."
}

# [5/8] Python environment
Write-Step "[5/8] Python environment"
$venvPy = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Action "Creating virtual environment (.venv)..."
    & python -m venv .venv
    if (-not (Test-Path -LiteralPath $venvPy)) { Write-Fail "Could not create .venv."; exit 1 }
}
Write-Ok "Virtual environment ready."
Write-Action "Installing requirements (this can take a few minutes)..."
& $venvPy -m pip install --upgrade pip 2>&1 | Out-Null
& $venvPy -m pip install -r (Join-Path $ScriptDir "requirements.txt")
if ($?) { Write-Ok "Dependencies installed." }
else { Write-Fail "pip install failed. Check your network and re-run setup."; exit 1 }

# [6/8] AI provider
Write-Step "[6/8] AI provider"
$envFile = Join-Path $ScriptDir ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $ScriptDir ".env.example") -Destination $envFile
    Write-Action "Created .env from .env.example (never commit this file)."
}
$provider = (Get-DotEnvValue $envFile "AI_PROVIDER").ToLower()
if ($provider -notin @("openrouter", "gemini", "groq", "openai")) { $provider = "openrouter" }
$providerKey = @{ openrouter = "OPENROUTER_API_KEY"; gemini = "GEMINI_API_KEY"; groq = "GROQ_API_KEY"; openai = "OPENAI_API_KEY" }[$provider]
$existingKey = Get-DotEnvValue $envFile $providerKey
if ($existingKey -and $existingKey -ne "your-key-here") {
    Write-Ok "AI provider '$provider' already configured in .env."
} else {
    Write-Host ""
    Write-Host "  Which AI provider would you like to use?"
    Write-Host "    1. OpenRouter (recommended - free models available)"
    Write-Host "    2. Gemini (Google free tier)"
    Write-Host "    3. Groq (fast inference)"
    $choice = Read-Host "  Choose AI provider [1/2/3] (default: 1)"
    switch ($choice) {
        "2" { $provider = "gemini"; $providerKey = "GEMINI_API_KEY" }
        "3" { $provider = "groq"; $providerKey = "GROQ_API_KEY" }
        default { $provider = "openrouter"; $providerKey = "OPENROUTER_API_KEY" }
    }
    $keyHelp = @{
        openrouter = "Get a key at https://openrouter.ai/keys (email signup, no card for free models)"
        gemini     = "Get a key at https://aistudio.google.com/apikey (Google account)"
        groq       = "Get a key at https://console.groq.com/keys"
    }[$provider]
    Write-Action $keyHelp
    $plain = Read-SecretValue "  Enter your $provider API key (input hidden on interactive terminals)"
    if (-not $plain) { Write-Warn "Empty key entered. You can add $providerKey to .env later." }
    else {
        Set-DotEnvValue $envFile "AI_PROVIDER" $provider
        Set-DotEnvValue $envFile $providerKey $plain
        $plain = $null
        Write-Ok "AI provider '$provider' saved to .env."
    }
}

# [7/8] Google Cloud (optional — warnings only)
Write-Step "[7/8] Google Cloud (optional, only for Cloud Run deployment)"
if ($gcloudOk) {
    $account = (& gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>$null).ToString().Trim()
    if (-not $account) {
        Write-Warn "gcloud is not authenticated."
        Write-Action "Run: gcloud auth login  (then re-run setup to finish cloud checks)"
    } else {
        Write-Ok "Authenticated."
        $project = (& gcloud config get-value project 2>$null).ToString().Trim()
        $envProject = Get-DotEnvValue $envFile "GCP_PROJECT_ID"
        if ((-not $project) -or ($project -eq "(unset)")) {
            if ($envProject) {
                Write-Action "Setting gcloud project to '$envProject' from .env..."
                & gcloud config set project $envProject 2>&1 | Out-Null
                $project = $envProject
            } else {
                Write-Warn "No GCP project selected."
                Write-Action "List projects: gcloud projects list  |  Set one: gcloud config set project PROJECT_ID"
                $project = ""
            }
        }
        if ($project) {
            Write-Ok "Project: $project"
            if ($envProject -ne $project) { Set-DotEnvValue $envFile "GCP_PROJECT_ID" $project }
            $services = (& gcloud services list --enabled --format="value(config.name)" --project $project 2>$null).ToString()
            foreach ($api in @("run.googleapis.com", "artifactregistry.googleapis.com")) {
                if ($services -match $api) { Write-Ok "$api enabled." }
                else { Write-Warn "$api not enabled. Enable: gcloud services enable $api --project $project" }
            }
            Write-Warn "Cloud Run needs a billing-enabled project. Without billing, Dockerfile generation still works; deployment will report the real error."
        }
    }
} else { Write-Warn "Skipped (gcloud not installed)." }

# [8/8] Configuration
Write-Step "[8/8] Configuration"
& $venvPy -c "import sys; sys.path.insert(0, '.'); from tools.ai_providers import get_ai_status; s=get_ai_status(); print('AI:', s)" 2>$null
if ($?) { Write-Ok "Application configuration loads." }
else { Write-Fail "Application import check failed. Re-run setup or report the error above."; exit 1 }

Write-Host ""
Write-Host "========================================="
Write-Host "        Setup complete!"
Write-Host "========================================="
Write-Host ""
Write-Host "  Start GitContainer:"
Write-Host ""
Write-Host "      .\start.ps1"
Write-Host ""
Write-Host "  Then open:"
Write-Host ""
Write-Host "      http://localhost:8000"
Write-Host ""
Write-Host "========================================="
