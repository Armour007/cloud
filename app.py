"""Minimal FastAPI app for GitHub URL to Dockerfile generator."""

import asyncio
import json
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from tools import gitingest_tool, clone_repo_tool, create_container_tool
from api_analytics.fastapi import Analytics

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="GitHub to Dockerfile Generator")

# Add API Analytics middleware
app.add_middleware(Analytics, api_key=os.getenv("FASTAPI_ANALYTICS_KEY"))

# Setup templates
templates = Jinja2Templates(directory="templates")

# Mount static files (we'll create this directory)
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Store for session data
sessions = {}

# Store for cloud deployment requests (deploy_id -> deploy spec).
# Cloud deployment is optional: local GitHub -> AI -> Dockerfile flow
# works without any GCP configuration.
deploys: Dict[str, Dict[str, Any]] = {}


def _cloud_status_safe() -> Dict[str, Any]:
    """Secret-free cloud status for templates/health checks.

    Never fails: if the cloud module is unavailable the feature is
    simply reported as disabled and local mode keeps working.
    """
    try:
        from cloud import get_cloud_status

        return dict(get_cloud_status())
    except Exception:
        return {
            "enabled": False,
            "configured": False,
            "project_id_set": False,
            "region": "asia-south1",
            "repository": "gitcontainer-images",
            "registry_host": "asia-south1-docker.pkg.dev",
            "gcloud_available": False,
            "docker_available": False,
        }


class CloudDeployRequest(BaseModel):
    """Request body for POST /api/cloud/deploy (all plain data, no secrets)."""

    repo_url: str = Field(default="", description="GitHub repository URL")
    dockerfile: str = Field(default="", description="AI-generated Dockerfile content")
    project_name: str = Field(default="", description="Project/repository display name")
    technology_stack: str = Field(default="")
    port_recommendations: List[Any] = Field(default_factory=list)
    service_name: str = Field(default="", description="Optional Cloud Run service override")
    region: str = Field(default="", description="Optional GCP region override")
    session_id: str = Field(
        default="",
        description="Optional generation session id to reuse the cloned source",
    )


@app.get("/favicon.ico")
async def favicon():
    """Serve the main favicon."""
    return FileResponse("static/icons8-docker-doodle-32.png")


@app.get("/favicon-16x16.png")
async def favicon_16():
    """Serve 16x16 favicon."""
    return FileResponse("static/icons8-docker-doodle-16.png")


@app.get("/favicon-32x32.png") 
async def favicon_32():
    """Serve 32x32 favicon."""
    return FileResponse("static/icons8-docker-doodle-32.png")


@app.get("/apple-touch-icon.png")
async def apple_touch_icon():
    """Serve Apple touch icon (120x120 is close to the 180x180 standard)."""
    return FileResponse("static/icons8-docker-doodle-120.png")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with the input form."""
    return templates.TemplateResponse(request, "index.jinja", {
        "repo_url": "",
        "loading": False,
        "streaming": False,
        "result": None,
        "error": None,
        "cloud": _cloud_status_safe(),
    })


@app.get("/health")
async def health_check():
    """Health check endpoint (registered before the catch-all routes)."""
    return {"status": "healthy", "cloud": _cloud_status_safe()}


@app.get("/api/cloud/config")
async def cloud_config():
    """Secret-free cloud configuration status for the deployment UI."""
    return _cloud_status_safe()


@app.post("/api/cloud/deploy")
async def create_cloud_deployment(spec: CloudDeployRequest):
    """Create a cloud deployment job; progress streams over /ws/deploy/{deploy_id}."""
    from cloud.config import validate_github_url

    repo_url = (spec.repo_url or "").strip()
    dockerfile = (spec.dockerfile or "").strip()
    if not repo_url:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="repo_url is required.")
    if not dockerfile:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="dockerfile is required.")
    try:
        validate_github_url(repo_url)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc))

    # Reuse the already-cloned source from generation when available so the
    # deployment builds exactly what the user reviewed.
    local_path = ""
    session_id = (spec.session_id or "").strip()
    if session_id and session_id in sessions:
        local_path = str(sessions[session_id].get("local_path", ""))

    deploy_id = str(abs(hash(repo_url + dockerfile[:64] + str(asyncio.get_event_loop().time()))))
    deploys[deploy_id] = {
        "repo_url": repo_url,
        "dockerfile": dockerfile,
        "project_name": (spec.project_name or "").strip(),
        "technology_stack": (spec.technology_stack or "").strip(),
        "port_recommendations": list(spec.port_recommendations or []),
        "service_name": (spec.service_name or "").strip(),
        "region": (spec.region or "").strip(),
        "local_path": local_path,
        "status": "pending",
    }
    return {"deploy_id": deploy_id, "status": "pending"}


@app.get("/{path:path}", response_class=HTMLResponse)
async def dynamic_github_route(request: Request, path: str):
    """Handle GitHub-style URLs by replacing gitcontainer.com with github.com."""
    # Skip certain paths that shouldn't be treated as GitHub routes
    skip_paths = {"health", "api", "favicon.ico", "favicon-16x16.png", "favicon-32x32.png", "apple-touch-icon.png", "static", "ws"}
    
    # Split path into segments
    segments = [segment for segment in path.split('/') if segment]
    
    # If it's a skip path, let it fall through
    if segments and segments[0] in skip_paths:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    
    # Check if we have at least 2 segments (username/repo)
    if len(segments) < 2:
        return templates.TemplateResponse(request, "index.jinja", {
            "repo_url": "",
            "loading": False,
            "streaming": False,
            "result": None,
            "error": f"Invalid GitHub URL format. Expected format: gitcontainer.com/username/repository",
            "pre_filled": False,
            "cloud": _cloud_status_safe(),
        })
    
    # Use only the first two segments (username/repo)
    username, repo = segments[0], segments[1]
    github_url = f"https://github.com/{username}/{repo}"
    
    return templates.TemplateResponse(request, "index.jinja", {
        "repo_url": github_url,
        "loading": False,
        "streaming": False,
        "result": None,
        "error": None,
        "pre_filled": True,
        "cloud": _cloud_status_safe(),
    })


@app.post("/{path:path}", response_class=HTMLResponse)
async def dynamic_github_route_post(
    request: Request,
    path: str,
    repo_url: str = Form(...),
    additional_instructions_hidden: str = Form("")
):
    """Handle POST requests for GitHub-style URLs, reusing the generate_dockerfile logic."""
    return await generate_dockerfile(request, repo_url, additional_instructions_hidden)


@app.post("/", response_class=HTMLResponse) 
async def generate_dockerfile(
    request: Request, 
    repo_url: str = Form(...),
    additional_instructions_hidden: str = Form("")
):
    """Redirect to streaming page for Dockerfile generation."""
    # Store the repo URL and additional instructions in a session (simple in-memory for demo)
    session_id = str(hash(repo_url + str(asyncio.get_event_loop().time())))
    sessions[session_id] = {
        "repo_url": repo_url,
        "additional_instructions": additional_instructions_hidden.strip() if additional_instructions_hidden else "",
        "status": "pending"
    }
    
    # Redirect to streaming page
    return templates.TemplateResponse(request, "index.jinja", {
        "repo_url": repo_url,
        "loading": False,
        "streaming": True,
        "session_id": session_id,
        "result": None,
        "error": None,
        "cloud": _cloud_status_safe(),
    })


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for streaming Dockerfile generation."""
    await websocket.accept()
    
    try:
        if session_id not in sessions:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": "Invalid session ID"
            }))
            return
        
        repo_url = sessions[session_id]["repo_url"]
        additional_instructions = sessions[session_id].get("additional_instructions", "")
        
        # Step 1: Clone repository
        await websocket.send_text(json.dumps({
            "type": "status", 
            "content": f"🔄 Cloning repository: {repo_url}"
        }))
        
        clone_result = await clone_repo_tool(repo_url)
        
        if not clone_result["success"]:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": f"Failed to clone repository: {clone_result['error']}"
            }))
            return

        # Remember the cloned source so a later cloud deployment builds
        # exactly the repository the user reviewed.
        sessions[session_id]["local_path"] = clone_result.get("local_path", "")
        sessions[session_id]["repo_name"] = clone_result.get("repo_name", "")
        
        # Step 2: Analyze with gitingest
        await websocket.send_text(json.dumps({
            "type": "status",
            "content": "📊 Analyzing repository structure..."
        }))
        
        ingest_result = await gitingest_tool(clone_result['local_path'])
        
        if not ingest_result["success"]:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": f"Failed to analyze repository: {ingest_result['error']}"
            }))
            return
        
        # Step 3: Generate Dockerfile with streaming
        await websocket.send_text(json.dumps({
            "type": "status",
            "content": "🐳 Generating Dockerfile with AI..."
        }))
        
        container_result = await create_container_tool(
            gitingest_summary=ingest_result['summary'],
            gitingest_tree=ingest_result['tree'], 
            gitingest_content=ingest_result['content'],
            project_name=clone_result['repo_name'],
            websocket=websocket,  # Pass WebSocket for streaming
            additional_instructions=additional_instructions
        )
        
        if not container_result["success"]:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": f"Failed to generate Dockerfile: {container_result['error']}"
            }))
            return
        
        # Send final result
        final_result = {
            "project_name": container_result['project_name'],
            "technology_stack": container_result['technology_stack'],
            "dockerfile": container_result['dockerfile'],
            "docker_compose": container_result.get('docker_compose_suggestion', ''),
            "reasoning": container_result.get('base_image_reasoning', ''),
            "additional_notes": container_result.get('additional_notes', ''),
            "repo_url": repo_url,
            "session_id": session_id,
            "port_recommendations": container_result.get("port_recommendations", []),
            "repo_info": {
                "name": clone_result['repo_name'],
                "size_mb": clone_result['repo_size_mb'],
                "file_count": clone_result['file_count']
            }
        }
        
        await websocket.send_text(json.dumps({
            "type": "complete",
            "content": "Generation complete!",
            "result": final_result
        }))
        
        # Store result in session for potential refresh
        sessions[session_id]["result"] = final_result
        sessions[session_id]["status"] = "complete"
        
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        print(f"Error in WebSocket endpoint: {e}")
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": f"Unexpected error: {str(e)}"
            }))
        except Exception as send_error:
            print(f"Could not send error message, WebSocket likely closed: {send_error}")
    finally:
        # Clean up session data
        try:
            if session_id in sessions:
                sessions[session_id]["status"] = "disconnected"
        except:
            pass


@app.websocket("/ws/deploy/{deploy_id}")
async def deploy_websocket_endpoint(websocket: WebSocket, deploy_id: str):
    """WebSocket endpoint streaming real build -> push -> deploy progress."""
    await websocket.accept()

    async def send(payload: Dict[str, Any]) -> None:
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception as exc:
            print(f"Deploy WebSocket send failed for {deploy_id}: {exc}")

    try:
        if deploy_id not in deploys:
            await send({"type": "error", "content": "Invalid deployment ID."})
            return

        spec = deploys[deploy_id]
        spec["status"] = "running"

        from cloud.deployment import run_cloud_deployment

        async def on_progress(kind: str, message: str) -> None:
            # Reuse the existing streaming message vocabulary:
            # status / chunk-style logs surfaced as deploy_log.
            if kind == "log":
                await send({"type": "deploy_log", "content": message})
            elif kind == "step":
                await send({"type": "deploy_step", "content": message})
            else:
                await send({"type": "status", "content": message})

        try:
            result = await run_cloud_deployment(
                repo_url=spec["repo_url"],
                dockerfile_content=spec["dockerfile"],
                project_name=spec.get("project_name", ""),
                technology_stack=spec.get("technology_stack", ""),
                port_recommendations=spec.get("port_recommendations", []),
                service_name_override=spec.get("service_name", ""),
                region_override=spec.get("region", ""),
                local_path=spec.get("local_path", ""),
                progress_callback=on_progress,
            )
        except Exception as exc:
            spec["status"] = "failed"
            await send({"type": "error", "content": f"Cloud deployment failed. Reason: {exc}"})
            return

        spec["status"] = "complete"
        spec["result"] = result
        await send({
            "type": "deploy_complete",
            "content": "Deployment successful",
            "result": result,
        })
    except WebSocketDisconnect:
        print(f"Deploy WebSocket disconnected for {deploy_id}")
    except Exception as e:
        print(f"Error in deploy WebSocket endpoint: {e}")
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": f"Unexpected error: {str(e)}",
            }))
        except Exception as send_error:
            print(f"Could not send deploy error, WebSocket likely closed: {send_error}")


if __name__ == "__main__":
    import uvicorn

    def _server_port() -> int:
        """Port from PORT env (platforms like Cloud Run assign it); safe fallback 8000."""
        try:
            port = int(os.getenv("PORT", "8000"))
            return port if 1 <= port <= 65535 else 8000
        except ValueError:
            return 8000

    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=_server_port()) 