"""End-to-end deployment orchestration.

Pipeline:
    generated Dockerfile + app source
      -> docker build
      -> tag for Artifact Registry
      -> docker push
      -> gcloud run deploy
      -> live HTTPS URL (from GCP, never fabricated)

Local mode (no GCP configured) is unaffected: analysis + Dockerfile
generation keep working without credentials. Only this orchestrator
requires GCP configuration.
"""

import asyncio
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .artifact_registry import (
    check_gcloud_auth,
    configure_docker_auth,
    push_image,
    tag_image,
)
from .cloud_run import deploy_service
from .config import (
    CloudConfig,
    build_image_reference,
    derive_names,
    get_cloud_config,
    validate_project_id,
    validate_region,
    validate_repository_name,
)
from .docker_builder import build_image

ProgressCallback = Optional[Callable[[str], Awaitable[Any]]]

_EXPOSE_RE = re.compile(r"^\s*EXPOSE\s+(\d+)", re.IGNORECASE | re.MULTILINE)
_PORT_FLAG_RE = re.compile(r"--port[=\s]+(\d{2,5})")
_LISTEN_RE = re.compile(r"(?:listen|port)\s*[:=]\s*(\d{2,5})", re.IGNORECASE)


def detect_app_port(
    dockerfile_content: str, port_recommendations: Optional[List[Any]] = None
) -> int:
    """Determine the container port: Dockerfile EXPOSE > AI hints > 8080.

    Cloud Run defaults to 8080; we never blindly assume 3000/5000/8000 —
    the Dockerfile itself is the source of truth.
    """
    content = dockerfile_content or ""
    match = _EXPOSE_RE.search(content)
    if match:
        try:
            port = int(match.group(1))
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
    for candidate in port_recommendations or []:
        try:
            port = int(str(candidate).strip())
            if 1 <= port <= 65535:
                return port
        except (ValueError, AttributeError):
            continue
    flag = _PORT_FLAG_RE.search(content)
    if flag:
        try:
            port = int(flag.group(1))
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
    return 8080


def cloud_run_notes(container_port: int) -> str:
    return (
        f"Container listens on port {container_port} "
        f"(PORT={container_port} is set on the Cloud Run service). "
        "The image must listen on $PORT for Cloud Run traffic."
    )


async def run_cloud_deployment(
    repo_url: str,
    dockerfile_content: str,
    project_name: str = "",
    technology_stack: str = "",
    port_recommendations: Optional[List[Any]] = None,
    service_name_override: str = "",
    region_override: str = "",
    local_path: str = "",
    progress_callback: Optional[Callable[[str, str], Awaitable[Any]]] = None,
    config: Optional[CloudConfig] = None,
) -> Dict[str, Any]:
    """Run the full build -> push -> deploy pipeline with progress events.

    progress_callback receives (event_type, message) where event_type is one of
    'status' | 'log' | 'step'. Raises RuntimeError with actionable messages.
    """
    cfg = config or get_cloud_config()
    project_id = validate_project_id(cfg.project_id)
    region = validate_region(region_override.strip() if region_override else cfg.region)
    repository = validate_repository_name(cfg.repository)

    if not (dockerfile_content or "").strip():
        raise ValueError("Dockerfile content is empty — generate it first.")
    if not (repo_url or "").strip() and not (local_path or "").strip():
        raise ValueError("Repository URL is required for cloud deployment.")

    async def emit(kind: str, message: str) -> None:
        if progress_callback is None:
            return
        try:
            result = progress_callback(kind, message)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass

    started = time.time()
    image_name, default_service = derive_names(repo_url or project_name, project_name)
    requested = (service_name_override or "").strip() or cfg.service_name_override.strip()
    from .config import sanitize_service_name as _san

    service_name = _san(requested) if requested else default_service
    container_port = detect_app_port(dockerfile_content, port_recommendations)
    remote_ref = build_image_reference(project_id, region, repository, image_name)
    local_tag = f"gitcontainer-local/{image_name}:latest"

    await emit("status", f"Preparing deployment of '{service_name}' to {region}...")
    await emit("step", "build:start")

    # Step 0: ensure source is available (reuse clone from generation if present).
    context_dir = (local_path or "").strip()
    if not context_dir:
        await emit("status", f"Cloning repository: {repo_url}")
        from tools import clone_repo_tool

        clone_result = await clone_repo_tool(repo_url)
        if not clone_result.get("success"):
            raise RuntimeError(
                f"Failed to clone repository: {clone_result.get('error', 'unknown error')}"
            )
        context_dir = clone_result["local_path"]
    else:
        import os as _os

        if not _os.path.isdir(context_dir):
            await emit("status", f"Cloning repository: {repo_url}")
            from tools import clone_repo_tool as _clone

            clone_result = await _clone(repo_url)
            if not clone_result.get("success"):
                raise RuntimeError(
                    f"Failed to clone repository: {clone_result.get('error', 'unknown error')}"
                )
            context_dir = clone_result["local_path"]

    # Step 1: docker build.
    await emit("status", "Building Docker image...")
    async def _build_log(line: str) -> None:
        await emit("log", line)

    await build_image(context_dir, dockerfile_content, local_tag, _build_log)
    await emit("step", "build:done")

    # Step 2: authenticate + push to Artifact Registry.
    await emit("step", "push:start")
    await emit("status", "Authenticating to Google Cloud...")
    await check_gcloud_auth()
    await configure_docker_auth(region, _build_log)
    await emit("status", f"Pushing image to Artifact Registry ({repository})...")
    await tag_image(local_tag, remote_ref, _build_log)
    await push_image(remote_ref, _build_log)
    await emit("step", "push:done")

    # Step 3: deploy to Cloud Run.
    await emit("step", "deploy:start")
    await emit("status", "Deploying to Cloud Run...")
    deploy_result = await deploy_service(
        remote_ref, service_name, region, project_id, container_port, _build_log
    )
    await emit("step", "deploy:done")

    elapsed = int(time.time() - started)
    url = deploy_result["url"]
    await emit("status", f"Deployment successful in {elapsed}s: {url}")

    return {
        "success": True,
        "url": url,
        "service": service_name,
        "region": region,
        "project_id": project_id,
        "repository": repository,
        "image": remote_ref,
        "container_port": container_port,
        "technology_stack": technology_stack or "",
        "notes": cloud_run_notes(container_port),
        "elapsed_seconds": elapsed,
    }
