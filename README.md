![Gitcontainer](docs/image.png)

# Gitcontainer Cloud 🐳☁️

**AI-Powered Cloud-Native Application Containerization & Deployment.**

**Turn any GitHub repository into a production-ready Docker container — and deploy it to Google Cloud Run with a live HTTPS URL — with AI-powered Dockerfile generation.**

The classic GitContainer experience is fully preserved: paste a GitHub URL, get a tailored Dockerfile. *Cloud deployment is an optional extension*: after the Dockerfile is generated, one action builds the image, pushes it to Google Artifact Registry and deploys it to Cloud Run.

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.68+-00a393.svg)](https://fastapi.tiangolo.com/)

Gitcontainer is an AI-powered web application that automatically generates production-ready Dockerfiles by analyzing GitHub repositories. Simply paste a GitHub URL and get a tailored Dockerfile with intelligent base image selection, dependency management, and Docker best practices.

## 🌟 Quick Access

Simply replace `github.com` with `gitcontainer.com` in any GitHub repository URL to instantly access the Dockerfile generation page for that repository.

For example:
```
https://github.com/username/repo  →  https://gitcontainer.com/username/repo
```

## ✨ Features

- **🔄 Instant URL Access**: Just replace 'github.com' with 'gitcontainer.com' in any GitHub URL
- **🤖 AI-Powered Analysis**: Uses OpenAI GPT-4 to analyze repository structure and generate intelligent Dockerfiles
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

## 🚀 Quick Start

### Prerequisites

**Required for Local Mode** (analyze → generate Dockerfile):

- Python 3.9 or higher
- Git
- OpenAI API key

**Additionally required for Cloud Mode** (build → push → deploy):

- Docker Desktop (running — builds execute locally via the Docker CLI)
- Google Cloud CLI `gcloud`
- Authenticated Google account (`gcloud auth login`)
- GCP project with **billing enabled** (Cloud Run requires it)
- IAM permissions: `roles/run.admin` + `roles/artifactregistry.writer`
  (Editor/Owner on a demo project also works)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Armour007/cloud.git
   cd cloud
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   ```bash
   # Copy the template and fill in your keys
   cp .env.example .env
   # (Windows cmd.exe: copy .env.example .env)
   # Required for Dockerfile generation:
   #   OPENAI_API_KEY=your_openai_api_key_here
   # Optional, only for Cloud Run deployment:
   #   GCP_PROJECT_ID=your-gcp-project-id
   #   GCP_REGION=asia-south1
   #   GCP_ARTIFACT_REGISTRY=gitcontainer-images
   ```

4. **Run the application:**
   ```bash
   python app.py
   ```

5. **Open your browser:**
   Navigate to `http://localhost:8000`

## ☁️ Google Cloud Setup (only for Cloud Run deployment)

Local Dockerfile generation works **without** any of this. To enable
**Deploy to Cloud Run**:

1. **Create/select a GCP project** at https://console.cloud.google.com/
   and note the project ID.
2. **Install the Google Cloud CLI**: https://cloud.google.com/sdk/docs/install
3. **Authenticate** (use the same account that owns the project):
   ```bash
   gcloud auth login
   gcloud auth application-default login
   gcloud config set project YOUR_PROJECT_ID
   ```
4. **Enable required APIs**:
   ```bash
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
   ```
5. **Create the Artifact Registry repository** (Docker format):
   ```bash
   gcloud artifacts repositories create gitcontainer-images \
     --repository-format=docker --location=asia-south1
   ```
   Use the same region you configure in `GCP_REGION`.
6. **Configure environment variables** in `.env`:
   ```env
   GCP_PROJECT_ID=your-gcp-project-id
   GCP_REGION=asia-south1
   GCP_ARTIFACT_REGISTRY=gitcontainer-images
   ```
   Never commit `.env` or service-account keys. The app uses your local
   `gcloud` credentials — no keys are stored in the repo.
7. **Run the app and deploy**: generate a Dockerfile as usual, then click
   **Deploy to Cloud Run**. Watch build → push → deploy progress and open
   the live `https://....run.app` URL.

Required IAM on your account: `roles/run.admin`,
`roles/artifactregistry.writer` (or broader Editor/Owner for a demo
project).

## 🖥️ Local Mode (no GCP needed)

1. Run `python app.py`, open `http://localhost:8000`
2. Paste a GitHub URL (e.g. `https://github.com/cyclotruc/gitingest`)
3. Click **Generate Dockerfile**, watch Clone → Analyze → Generate
4. Review the Dockerfile in the editor, copy it if needed

Nothing GCP-related is required or contacted in this mode.

## ☁️ Cloud Mode (deploy to Cloud Run)

1. Complete the Google Cloud Setup above (one time per machine/project)
2. Generate a Dockerfile as in Local Mode
3. Click **Deploy to Cloud Run** under the result
4. Watch Build → Push → Deploy progress in place
5. Open the live `https://....run.app` URL when it appears

The deployment builds the exact Dockerfile shown in the editor, tags it
`REGION-docker.pkg.dev/PROJECT/REPO/IMAGE:latest`, pushes it, and deploys
with `--port <detected>` + `PORT=<detected>` (see Port handling).

## 🛠️ How It Works

1. **URL Processing**: Access any repository by replacing 'github.com' with 'gitcontainer.com' in the URL
2. **Repository Cloning**: Gitcontainer clones the GitHub repository locally using Git
3. **Code Analysis**: Uses [gitingest](https://github.com/cyclotruc/gitingest) to analyze the repository structure and extract relevant information
4. **AI Generation**: Sends the analysis to OpenAI GPT-4 with specialized prompts for Dockerfile generation
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
├── requirements.txt       # Python dependencies (unchanged — cloud uses CLI tools)
├── .env                  # Environment variables (create this, never commit)
├── .env.example          # Template for all supported variables
├── static/               # Static assets (icons, CSS)
├── templates/
│   └── index.jinja       # Main HTML template (UI preserved; deploy card appended)
├── tools/                # Core functionality modules (untouched)
│   ├── __init__.py
│   ├── create_container.py  # AI Dockerfile generation
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
| `OPENAI_API_KEY` | Your OpenAI API key | Yes |
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

## 🆘 Troubleshooting

| Symptom | Fix |
|---|---|
| `OPENAI_API_KEY not found` | Create `.env` from `.env.example` and set `OPENAI_API_KEY` |
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