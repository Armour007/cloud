"""Cloud configuration: environment variables, validation, name sanitization.

No secrets are ever exposed through the frontend — use get_cloud_status()
for the safe subset and get_cloud_config() on the backend only.

Environment variables:
    GCP_PROJECT_ID          Google Cloud project id (required for deploy)
    GCP_REGION              e.g. asia-south1 (default: asia-south1)
    GCP_ARTIFACT_REGISTRY   Artifact Registry repo name (default: gitcontainer-images)
                            (also accepts GCP_ARTIFACT_REPOSITORY as an alias)
    GCP_SERVICE_NAME        Optional fixed Cloud Run service name override
"""

import os
import re
import shutil
from dataclasses import dataclass
from typing import Dict, Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_REGION = "asia-south1"
DEFAULT_REGISTRY = "gitcontainer-images"
DEFAULT_TAG = "latest"

_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_REGION_RE = re.compile(r"^[a-z]+-[a-z]+[0-9]$")
_REPO_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9._-]{0,126}[a-z0-9])?$")


@dataclass(frozen=True)
class CloudConfig:
    project_id: str = ""
    region: str = DEFAULT_REGION
    repository: str = DEFAULT_REGISTRY
    service_name_override: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.project_id)

    @property
    def registry_host(self) -> str:
        return f"{self.region}-docker.pkg.dev"


def get_cloud_config() -> CloudConfig:
    """Read cloud configuration from environment (backend use only)."""
    repository = (
        os.getenv("GCP_ARTIFACT_REGISTRY")
        or os.getenv("GCP_ARTIFACT_REPOSITORY")
        or DEFAULT_REGISTRY
    ).strip()
    return CloudConfig(
        project_id=os.getenv("GCP_PROJECT_ID", "").strip(),
        region=os.getenv("GCP_REGION", DEFAULT_REGION).strip() or DEFAULT_REGION,
        repository=repository,
        service_name_override=os.getenv("GCP_SERVICE_NAME", "").strip(),
    )


def get_cloud_status() -> Dict[str, object]:
    """Safe, secret-free cloud status for the frontend/API health checks."""
    config = get_cloud_config()
    return {
        "enabled": config.enabled,
        "configured": config.enabled,
        "project_id_set": bool(config.project_id),
        "region": config.region,
        "repository": config.repository,
        "registry_host": config.registry_host,
        "gcloud_available": is_gcloud_available(),
        "docker_available": is_docker_available(),
    }


def is_gcloud_available() -> bool:
    return shutil.which("gcloud") is not None


def is_docker_available() -> bool:
    return shutil.which("docker") is not None


def validate_github_url(url: str) -> Tuple[str, str]:
    """Validate a GitHub URL, returning (owner, repo). Raises ValueError."""
    url = (url or "").strip()
    if not url:
        raise ValueError("Repository URL is empty.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != "github.com":
        raise ValueError("Only https://github.com URLs are supported.")
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("Invalid GitHub URL format. Expected: https://github.com/owner/repo")
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not repo:
        raise ValueError("Invalid GitHub URL format. Expected: https://github.com/owner/repo")
    return parts[0], repo


def sanitize_image_name(name: str) -> str:
    """Sanitize a string for use as a Docker/Artifact Registry image name."""
    name = (name or "").lower().strip().replace("/", "-").replace("_", "-")
    name = re.sub(r"[^a-z0-9._-]+", "-", name)
    name = re.sub(r"[-._]{2,}", "-", name).strip("-._")
    if not name:
        return "app"
    if not _REPO_NAME_RE.match(name):
        name = re.sub(r"[^a-z0-9-]+", "-", name).strip("-")
        name = name or "app"
    return name[:128]


def sanitize_service_name(name: str) -> str:
    """Sanitize a string for use as a Cloud Run service name.

    Rules: lowercase, start with a letter, end alphanumeric, interior
    alphanumerics/dashes, max 63 chars.
    """
    name = (name or "").lower().strip().replace("/", "-").replace("_", "-")
    name = re.sub(r"[^a-z0-9-]+", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    if not name or not name[0].isalpha():
        name = f"app-{name}" if name else "gitcontainer-app"
        name = re.sub(r"-{2,}", "-", name).strip("-")
    if len(name) > 63:
        name = name[:63].rstrip("-")
    if not name[-1].isalnum():
        name = name.rstrip("-") + "0"
    return name or "gitcontainer-app"


def validate_project_id(project_id: str) -> str:
    project_id = (project_id or "").strip()
    if not project_id:
        raise ValueError(
            "GCP_PROJECT_ID is not configured. "
            "Set GCP_PROJECT_ID in your .env file. "
            "See README 'Google Cloud Setup' for instructions."
        )
    if not _PROJECT_RE.match(project_id):
        raise ValueError(
            f"Invalid GCP project ID: '{project_id}'. "
            "Project IDs are 6-30 lowercase letters, digits or hyphens, "
            "starting with a letter and not ending with a hyphen."
        )
    return project_id


def validate_region(region: str) -> str:
    region = (region or "").strip() or DEFAULT_REGION
    if not _REGION_RE.match(region):
        raise ValueError(
            f"Invalid GCP region: '{region}'. Example valid regions: "
            "asia-south1, us-central1, europe-west1."
        )
    return region


def validate_repository_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 128:
        raise ValueError(
            f"Invalid Artifact Registry repository name: '{name}'. "
            "Create it with: "
            f"gcloud artifacts repositories create {DEFAULT_REGISTRY} "
            "--repository-format=docker --location=REGION"
        )
    return name


def build_image_reference(
    project_id: str, region: str, repository: str, image: str, tag: str = DEFAULT_TAG
) -> str:
    """Standard Artifact Registry reference: REGION-docker.pkg.dev/PROJECT/REPO/IMAGE:TAG."""
    image = sanitize_image_name(image)
    tag = (tag or DEFAULT_TAG).strip() or DEFAULT_TAG
    tag = re.sub(r"[^A-Za-z0-9_.-]+", "-", tag)[:128].strip(".-") or DEFAULT_TAG
    return f"{region}-docker.pkg.dev/{project_id}/{repository}/{image}:{tag}"


def derive_names(repo_url: str, project_name: str = "") -> Tuple[str, str]:
    """Derive (image_name, service_name) from repo URL and/or project name."""
    try:
        owner, repo = validate_github_url(repo_url)
        base = repo or project_name or "app"
    except ValueError:
        base = project_name or "app"
    image = sanitize_image_name(base)
    service = sanitize_service_name(base)
    _ = owner if "owner" in dir() else None
    return image, service
