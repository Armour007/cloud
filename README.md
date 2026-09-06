![Gitcontainer](docs/image.png)

# Gitcontainer Cloud 🐳☁️

Turn a GitHub repository into a live containerized application.

```text
GitHub → AI → Docker → Artifact Registry → Cloud Run → LIVE
```

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.68+-00a393.svg)](https://fastapi.tiangolo.com/)

## Quick Start

### Windows

```powershell
git clone https://github.com/Armour007/cloud.git
cd cloud
.\setup.ps1
.\start.ps1
```

Then open:

[http://localhost:8000](http://localhost:8000)

### macOS / Linux

```bash
git clone https://github.com/Armour007/cloud.git
cd cloud
chmod +x setup.sh start.sh
./setup.sh
./start.sh
```

Then open:

[http://localhost:8000](http://localhost:8000)

That's the primary setup path. `setup` checks your tools, creates the
environment, and configures your AI provider; `start` runs the app.
Prefer manual setup? See [Advanced Setup](#advanced-setup).

## User workflow

One continuous pipeline — paste a URL, get a live app:

1. Open GitContainer at `http://localhost:8000`.
2. Paste a public GitHub repository URL.
3. Click Analyze — the repository is cloned and analyzed.
4. AI generates a Dockerfile for the detected stack.
5. Review the Dockerfile in the editor.
6. Build the container image.
7. Push the image to Artifact Registry.
8. Deploy to Cloud Run (click **Deploy to Cloud Run**).
9. Watch Build → Push → Deploy progress.
10. Open the generated live `https://....run.app` URL. 🟢

## 🏗️ Architectural boundary

Two applications are involved — don't confuse them:

- `http://localhost:8000` = **GitContainer control interface** (this repo —
  runs on your machine, never deployed anywhere by this project).
- `https://....run.app` = **your deployed target application** (the GitHub
  project you analyzed, Dockerized and running on Cloud Run).

Cloud Run hosts the *generated user application*, not the GitContainer UI.
(Local execution and cloud deployment are implementation stages of the one
workflow above — there is no separate product to learn.)

## ✨ Features

- **🔄 Instant URL Access**: Open `http://localhost:8000/username/repo` to pre-fill any GitHub repository
- **🤖 AI-Powered Analysis**: Free-tier AI providers (OpenRouter default, Gemini/Groq supported) analyze structure and generate intelligent Dockerfiles
- **⚡ Real-time Streaming**: Watch the AI generate your Dockerfile in real-time with WebSocket streaming
- **🎯 Smart Detection**: Automatically detects technology stacks (Python, Node.js, Java, Go, etc.)
- **🔧 Production-Ready**: Generates Dockerfiles following best practices with proper security, multi-stage builds, and optimization
- **📋 Additional Instructions**: Add custom requirements for specialized environments
- **📄 Docker Compose**: Automatically suggests docker-compose.yml for complex applications
- **☁️ One-click Cloud Run deploy**: Build the generated Dockerfile, push to Artifact Registry and go live on Cloud Run (optional, needs GCP)
- **📡 Live deploy progress**: Build → push → deploy streamed over WebSocket with the same UI patterns as generation
- **🎨 Modern UI**: Clean, responsive interface with Monaco editor for syntax highlighting
- **📱 Mobile Friendly**: Works seamlessly on desktop and mobile devices

## ☁️ Cloud Architecture

```
GitHub
  │
  ▼
GitContainer (existing: ingest → analyze → AI Dockerfile)
  │
  ▼
Docker Build (generated Dockerfile + app source)
  │
  ▼
Google Artifact Registry  (REGION-docker.pkg.dev/PROJECT/REPO/IMAGE:TAG)
  │
  ▼
Google Cloud Run (managed, no Kubernetes)
  │
  ▼
Public HTTPS URL (real service URL returned by Cloud Run)
```

Deliberately simple: **Cloud Run instead of GKE** — no Kubernetes, Helm, Terraform, service mesh or background workers. The cloud layer lives in `cloud/` and never touches the analysis/generation core in `tools/`.

## 🤖 AI providers (free-tier support)

No OpenAI purchase required. Pick one during `setup` (OpenRouter preselected):

| Provider | Key | Default model | Notes |
|---|---|---|---|
| OpenRouter (default) | `OPENROUTER_API_KEY` | `openrouter/free` | Auto-selects a currently available free model; key from https://openrouter.ai/keys |
| Gemini | `GEMINI_API_KEY` | `gemini-2.0-flash` | Google free tier; key from https://aistudio.google.com/apikey |
| Groq | `GROQ_API_KEY` | `llama-3.3-70b-versatile` | Fast inference; key from https://console.groq.com/keys |
| OpenAI (optional) | `OPENAI_API_KEY` | `gpt-4o-mini` | Legacy, paid — never required |

Only the selected provider needs a key (`AI_PROVIDER=openrouter` by default;
every model is overridable via `*_MODEL`). Free-model IDs and quotas change
over time — this is free-tier/free-model support, not unlimited free AI. If a
model disappears you'll get a clear error naming it; set a current ID and retry.

## ☁️ Deploying to Cloud Run (prerequisites)

Dockerfile generation works without any of this. The **Deploy to Cloud Run**
button additionally needs (setup checks these and explains what's missing):

1. **Docker Desktop** running (builds execute locally): https://www.docker.com/products/docker-desktop/
2. **Google Cloud CLI**: https://cloud.google.com/sdk/docs/install
3. **Authentication**: `gcloud auth login` (also `gcloud auth application-default login`)
4. **GCP project** with **billing enabled** (Cloud Run requires it):
   `gcloud projects list` → `gcloud config set project PROJECT_ID`
5. **Required APIs**: `gcloud services enable run.googleapis.com artifactregistry.googleapis.com`
6. **Permissions**: `roles/run.admin` + `roles/artifactregistry.writer` (Editor/Owner on a demo project works)
7. **Artifact Registry repo** (Docker format):
   `gcloud artifacts repositories create gitcontainer-images --repository-format=docker --location=asia-south1`
8. **`.env`**: `GCP_PROJECT_ID`, `GCP_REGION` (default `asia-south1`),
   `GCP_ARTIFACT_REGISTRY` (default `gitcontainer-images`)

Never commit `.env` or keys — the app uses your local `gcloud` credentials.
The deployment builds the exact Dockerfile shown in the editor, tags it
`REGION-docker.pkg.dev/PROJECT/REPO/IMAGE:latest`, pushes it, and deploys
with `--port <detected>` + `PORT=<detected>` (see Port handling).

## <a id="advanced-setup"></a>🛠️ Advanced Setup

Prefer manual setup over the scripts?

```bash
git clone https://github.com/Armour007/cloud.git
cd cloud
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set AI_PROVIDER + your provider key
python app.py          # open http://localhost:8000
```

## 🛠️ How It Works

1. **URL Processing**: Paste any GitHub URL (or open `http://localhost:8000/username/repo` to pre-fill it)
2. **Repository Cloning**: Gitcontainer clones the GitHub repository locally using Git (no shell interpolation; owner/repo validated)
3. **Code Analysis**: Uses [gitingest](https://github.com/cyclotruc/gitingest) to analyze the repository structure and extract relevant information
4. **AI Generation**: Sends the analysis to the configured provider (OpenRouter/Gemini/Groq) with specialized prompts for Dockerfile generation
5. **Smart Optimization**: The AI considers:
   - Technology stack detection
   - Dependency management
   - Security best practices
   - Multi-stage builds when beneficial
   - Port configuration
   - Environment variables
   - Health checks

## 📁 Project Structure

```
cloud/
├── app.py                 # Main FastAPI application (+ cloud API/WS routes)
├── setup.ps1 / start.ps1  # Windows one-command setup + start
├── setup.sh / start.sh    # macOS/Linux one-command setup + start
├── requirements.txt       # Python dependencies (no new packages for AI providers)
├── .env                  # Environment variables (created by setup, never commit)
├── .env.example          # Template for all supported variables
├── static/               # Static assets (icons, CSS)
├── templates/
│   └── index.jinja       # Main HTML template (UI preserved; deploy card appended)
├── tools/                # Core functionality modules
│   ├── __init__.py
│   ├── ai_providers.py      # Provider abstraction (openrouter/gemini/groq/openai)
│   ├── create_container.py  # AI Dockerfile generation (provider-agnostic contract)
│   ├── git_operations.py    # GitHub repository cloning
│   └── gitingest.py        # Repository analysis
└── cloud/                # NEW: isolated Cloud Run deployment layer
    ├── __init__.py
    ├── config.py            # Env config, validation, name sanitization
    ├── docker_builder.py    # Safe `docker build` with streamed output
    ├── artifact_registry.py # Tag + push to Artifact Registry
    ├── cloud_run.py         # `gcloud run deploy` + real service URL
    └── deployment.py        # Orchestrator + Cloud Run port detection
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `AI_PROVIDER` | `openrouter` (default) \| `gemini` \| `groq` \| `openai` | No |
| `OPENROUTER_API_KEY` | OpenRouter key (free models available) | Only if `AI_PROVIDER=openrouter` |
| `OPENROUTER_MODEL` | Model ID (default: `openrouter/free`) | No |
| `GEMINI_API_KEY` | Google AI Studio key | Only if `AI_PROVIDER=gemini` |
| `GEMINI_MODEL` | Model ID (default: `gemini-2.0-flash`) | No |
| `GROQ_API_KEY` | GroqCloud key | Only if `AI_PROVIDER=groq` |
| `GROQ_MODEL` | Model ID (default: `llama-3.3-70b-versatile`) | No |
| `OPENAI_API_KEY` | OpenAI key (optional legacy provider) | Only if `AI_PROVIDER=openai` |
| `GCP_PROJECT_ID` | GCP project for Artifact Registry + Cloud Run | Only for cloud deploy |
| `GCP_REGION` | GCP region (default: `asia-south1`) | No |
| `GCP_ARTIFACT_REGISTRY` | Artifact Registry repo name (default: `gitcontainer-images`) | No |
| `GCP_SERVICE_NAME` | Fixed Cloud Run service name (default: derived from repo) | No |
| `PORT` | Server port (default: 8000) | No |
| `HOST` | Server host (default: 0.0.0.0) | No |

### Port handling

Cloud Run routes traffic to the container port and provides it via the
`PORT` env var. The deployer detects the port from the generated
Dockerfile's `EXPOSE` instruction first, then the AI's port
recommendations, defaulting to `8080` (never a blind 3000/5000/8000
assumption). The service is deployed with `--port <detected>` and
`PORT=<detected>` so images that listen on their exposed port work
unchanged.

### Cloud API (used by the deploy UI)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/cloud/config` | Secret-free cloud status (region, repo, CLI availability) |
| `POST /api/cloud/deploy` | Create a deploy job → `{deploy_id}` |
| `WS /ws/deploy/{deploy_id}` | Stream build → push → deploy; emits `status`, `deploy_log`, `deploy_step`, `deploy_complete`, `error` |
| `GET /health` | Health check, now includes secret-free `cloud` status |

### Advanced Usage

You can use the tools programmatically:

```python
from tools import clone_repo_tool, gitingest_tool, create_container_tool
import asyncio

async def generate_dockerfile(github_url):
    # Clone repository
    clone_result = await clone_repo_tool(github_url)
    
    # Analyze with gitingest
    analysis = await gitingest_tool(clone_result['local_path'])
    
    # Generate Dockerfile
    dockerfile = await create_container_tool(
        gitingest_summary=analysis['summary'],
        gitingest_tree=analysis['tree'],
        gitingest_content=analysis['content']
    )
    
    return dockerfile

# Usage
result = asyncio.run(generate_dockerfile("https://github.com/user/repo"))
print(result['dockerfile'])
```

## 🎨 Customization

### Adding Custom Instructions

Use the "Additional instructions" feature to customize generation:

- `"Use Alpine Linux for smaller image size"`
- `"Include Redis and PostgreSQL"`
- `"Optimize for production deployment"`
- `"Add development tools for debugging"`

## ⚠️ Known limitations

- Cloud deploy needs Docker Desktop running, `gcloud` installed/authenticated,
  and an existing Artifact Registry repository — errors are reported with the
  exact remediation command.
- The deployed container must listen on `$PORT` (the deployer sets
  `PORT=<detected-port>`); apps hardcoding a different port without reading
  `PORT` may fail Cloud Run health checks.
- Deployment reuses the cloned source from generation when available,
  otherwise it re-clones from the repo URL.
- Cloned repositories accumulate under `repos/` (git-ignored); delete that
  folder any time to reclaim disk space.
- No fake deployments: without valid GCP setup the UI reports the real
  error and never shows a URL.
- Free-tier AI models rotate and quotas change; models are configurable via
  `*_MODEL` variables and failures name the exact model to replace.

## 🆘 Troubleshooting

| Symptom | Fix |
|---|---|
| `OPENAI_API_KEY` not configured | Only needed when `AI_PROVIDER=openai` — otherwise configure your selected provider's key |
| `OPENROUTER_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` not configured | `setup` asks for the selected provider's key; add it to `.env` |
| `Docker daemon is not reachable` | Start Docker Desktop and wait until it is running |
| `Docker executable not found` | Install Docker Desktop and ensure `docker` is on PATH |
| `gcloud is not installed` | Install from https://cloud.google.com/sdk/docs/install, restart terminal |
| `Google Cloud authentication is unavailable` | Run `gcloud auth login` + `gcloud auth application-default login` |
| `GCP_PROJECT_ID is not configured` | Set it in `.env` (see `.env.example`) |
| Push `denied` / `permission` | Enable Artifact Registry API; grant `roles/artifactregistry.writer`; create the repo (`gcloud artifacts repositories create …`) |
| Push `repository … does not exist` | Create it: `gcloud artifacts repositories create gitcontainer-images --repository-format=docker --location=YOUR_REGION` |
| `Cloud Run deployment failed` | Check port (app must listen on `$PORT`), IAM `roles/run.admin`, and that billing is enabled on the project |
| Live URL loads but app errors | The container crashed on startup — check `gcloud run services logs read SERVICE --region REGION` |
| `Invalid GCP project ID` | 6–30 lowercase letters/digits/hyphens, starts with a letter |
| Port is wrong on Cloud Run | The deployer uses Dockerfile `EXPOSE` first — ensure the generated Dockerfile exposes the app port |

## 🔒 Security

- **Never commit `.env`** or any credential file — `.gitignore` blocks
  `.env`, `.env.*`, `*.key`, `*.pem`, `service-account*.json`.
- The app uses your local `gcloud` credentials at deploy time; no
  service-account keys are stored in the repo — do not add any.
- `git clone` runs without a shell and owner/repo names are allowlisted.
- The `/api/cloud/config` and `/health` endpoints expose **no secrets**
  (only whether a project ID is set, region/repo names, CLI availability).
- If you suspect a secret was committed: rotate it immediately, then purge
  it from history (`git filter-repo`) — do not just delete the file.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **[OpenAI](https://openai.com/)** for providing the GPT-4 API
- **[gitingest](https://github.com/cyclotruc/gitingest)** for repository analysis capabilities
- **[FastAPI](https://fastapi.tiangolo.com/)** for the excellent web framework
- **[Monaco Editor](https://microsoft.github.io/monaco-editor/)** for code syntax highlighting

## 🔗 Links

- **GitHub Repository**: [https://github.com/Armour007/cloud](https://github.com/Armour007/cloud)
- **Demo**: Try it live with example repositories
- **Issues**: [Report bugs or request features](https://github.com/Armour007/cloud/issues)

---

**Made with ❤️ by [Romain Courtois](https://github.com/cyclotruc)**

*Turn any repository into a container in seconds!*