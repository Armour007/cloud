"""GitContainer Cloud — isolated Google Cloud deployment layer.

Existing GitContainer logic (tools/) remains responsible for repository
analysis and Dockerfile generation. This package is responsible only for:

    Dockerfile + source -> docker build -> Artifact Registry -> Cloud Run

All subprocess invocations use argument arrays (no shell) and all
user-derived names are sanitized before use.
"""

from .config import get_cloud_config, get_cloud_status
from .deployment import run_cloud_deployment, detect_app_port

__all__ = [
    "get_cloud_config",
    "get_cloud_status",
    "run_cloud_deployment",
    "detect_app_port",
]
