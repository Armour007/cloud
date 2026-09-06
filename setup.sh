#!/usr/bin/env bash
# GitContainer Cloud — one-command macOS/Linux setup.
# Idempotent: safe to re-run; never overwrites existing .env values.
# Cloud (gcloud/GCP) problems are warnings — setup still completes.
set -u
cd "$(dirname "$0")"

ok()   { echo "  [OK] $1"; }
warn() { echo "  [!!] $1"; }
fail() { echo "  [XX] $1"; }
act()  { echo "  ---> $1"; }
have() { command -v "$1" >/dev/null 2>&1; }

# .env helpers (awk-based upsert; never prints values)
dotenv_get() { [ -f .env ] && awk -F= -v k="$1" '$1==k{sub($1"=","");print;exit}' .env | tr -d '\r' || true; }
dotenv_set() {
  key="$1"; value="$2"
  [ -f .env ] || : > .env
  awk -F= -v k="$key" -v v="$value" 'BEGIN{done=0} $1==k && !done{print k"="v; done=1; next} {print} END{if(!done) print k"="v}' .env > .env.tmp && mv .env.tmp .env
}

echo ""
echo "========================================="
echo "        GitContainer Cloud Setup"
echo "========================================="
echo ""

# [1/8] Python
echo "[1/8] Python"
if have python3 && python3 -c 'import sys; assert sys.version_info >= (3, 9)' 2>/dev/null; then
  ok "$(python3 --version 2>&1)"
else
  fail "Python 3.9+ not found. Install it, then re-run setup."; exit 1
fi

# [2/8] Git
echo "[2/8] Git"
have git && ok "$(git --version)" || warn "Git not found (needed to analyze repositories)."

# [3/8] Docker
echo "[3/8] Docker"
if have docker; then
  ok "$(docker --version)"
  if docker info >/dev/null 2>&1; then ok "Docker daemon is running."
  else
    warn "Docker is installed but not running."
    act "Please start Docker, then press ENTER to retry."
    read -r _
    docker info >/dev/null 2>&1 && ok "Docker daemon is running." || warn "Daemon still unreachable. Image builds will fail until Docker runs."
  fi
else warn "Docker not found. Install Docker to build images: https://docs.docker.com/get-docker/"; fi

# [4/8] Google Cloud CLI
echo "[4/8] Google Cloud CLI"
if have gcloud; then ok "$(gcloud --version 2>/dev/null | head -n1)"; GCLOUD=1; else warn "gcloud not found. Required ONLY for Cloud Run deployment: https://cloud.google.com/sdk/docs/install"; GCLOUD=0; fi

# [5/8] Python environment
echo "[5/8] Python environment"
[ -x .venv/bin/python ] || { act "Creating virtual environment (.venv)..."; python3 -m venv .venv || { fail "Could not create .venv."; exit 1; }; }
ok "Virtual environment ready."
act "Installing requirements (this can take a few minutes)..."
.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
.venv/bin/python -m pip install -r requirements.txt || { fail "pip install failed. Check network and re-run."; exit 1; }
ok "Dependencies installed."

# [6/8] AI provider
echo "[6/8] AI provider"
[ -f .env ] || { cp .env.example .env; act "Created .env from .env.example (never commit this file)."; }
provider="$(dotenv_get AI_PROVIDER | tr '[:upper:]' '[:lower:]')"
case "$provider" in openrouter|gemini|groq|openai) ;; *) provider="openrouter";; esac
case "$provider" in
  openrouter) pkey="OPENROUTER_API_KEY";; gemini) pkey="GEMINI_API_KEY";;
  groq) pkey="GROQ_API_KEY";; openai) pkey="OPENAI_API_KEY";;
esac
existing="$(dotenv_get "$pkey")"
if [ -n "$existing" ] && [ "$existing" != "your-key-here" ]; then
  ok "AI provider '$provider' already configured in .env."
else
  echo ""
  echo "  Which AI provider would you like to use?"
  echo "    1. OpenRouter (recommended - free models available)"
  echo "    2. Gemini (Google free tier)"
  echo "    3. Groq (fast inference)"
  printf "  Choose AI provider [1/2/3] (default: 1): "; read -r choice
  case "$choice" in
    2) provider="gemini"; pkey="GEMINI_API_KEY"; url="https://aistudio.google.com/apikey";;
    3) provider="groq"; pkey="GROQ_API_KEY"; url="https://console.groq.com/keys";;
    *) provider="openrouter"; pkey="OPENROUTER_API_KEY"; url="https://openrouter.ai/keys";;
  esac
  act "$url"
  printf "  Enter your %s API key (hidden): " "$provider"
  if [ -t 0 ]; then stty -echo; read -r key; stty echo; echo ""; else read -r key; fi
  if [ -z "$key" ]; then warn "Empty key. Add $pkey to .env later."
  else dotenv_set "AI_PROVIDER" "$provider"; dotenv_set "$pkey" "$key"; ok "AI provider '$provider' saved to .env."; fi
  unset key
fi

# [7/8] Google Cloud (optional — warnings only)
echo "[7/8] Google Cloud (optional, only for Cloud Run deployment)"
if [ "$GCLOUD" = "1" ]; then
  account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1)"
  if [ -z "$account" ]; then
    warn "gcloud is not authenticated."; act "Run: gcloud auth login  (then re-run setup)"
  else
    ok "Authenticated."
    project="$(gcloud config get-value project 2>/dev/null)"
    if [ -z "$project" ] || [ "$project" = "(unset)" ]; then
      envproj="$(dotenv_get GCP_PROJECT_ID)"
      if [ -n "$envproj" ]; then act "Setting gcloud project to '$envproj' from .env..."; gcloud config set project "$envproj" >/dev/null 2>&1; project="$envproj";
      else warn "No GCP project selected."; act "List: gcloud projects list  |  Set: gcloud config set project PROJECT_ID"; project=""; fi
    fi
    if [ -n "$project" ]; then
      ok "Project: $project"
      [ "$(dotenv_get GCP_PROJECT_ID)" = "$project" ] || dotenv_set "GCP_PROJECT_ID" "$project"
      enabled="$(gcloud services list --enabled --format='value(config.name)' --project "$project" 2>/dev/null)"
      for api in run.googleapis.com artifactregistry.googleapis.com; do
        echo "$enabled" | grep -q "$api" && ok "$api enabled." || warn "$api not enabled. Enable: gcloud services enable $api --project $project"
      done
      warn "Cloud Run needs a billing-enabled project. Without billing, Dockerfile generation still works; deployment reports the real error."
    fi
  fi
else warn "Skipped (gcloud not installed)."; fi

# [8/8] Configuration
echo "[8/8] Configuration"
if .venv/bin/python -c "import sys; sys.path.insert(0, '.'); from tools.ai_providers import get_ai_status; print('AI:', get_ai_status())" 2>/dev/null; then
  ok "Application configuration loads."
else fail "Application import check failed."; exit 1; fi

echo ""
echo "========================================="
echo "        Setup complete!"
echo "========================================="
echo ""
echo "  Start GitContainer:"
echo ""
echo "      ./start.sh"
echo ""
echo "  Then open:"
echo ""
echo "      http://localhost:8000"
echo ""
echo "========================================="
