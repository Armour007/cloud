"""Google Artifact Registry integration.

Flow: local image -> docker tag -> docker push to
REGION-docker.pkg.dev/PROJECT/REPOSITORY/IMAGE:TAG

All commands use subprocess argument arrays (no shell interpolation).
"""

import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .config import is_gcloud_available

ProgressCallback = Optional[Callable[[str], Awaitable[Any]]]

AUTH_TIMEOUT_SECONDS = 120
PUSH_TIMEOUT_SECONDS = 600


async def _emit(callback: ProgressCallback, line: str) -> None:
    if callback is None:
        return
    try:
        result = callback(line)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        pass


async def _run(cmd: List[str], timeout: int) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(cmd[:3])}...") from exc
    text = (stdout or b"").decode("utf-8", errors="replace")
    return proc.returncode or 0, text


async def check_gcloud_auth() -> str:
    """Return the active gcloud account, or raise with actionable guidance."""
    if not is_gcloud_available():
        raise RuntimeError(
            "Google Cloud CLI ('gcloud') is not installed or not on PATH. "
            "Install it from https://cloud.google.com/sdk/docs/install, "
            "then run: gcloud auth login"
        )
    code, out = await _run(
        ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
        AUTH_TIMEOUT_SECONDS,
    )
    account = (out or "").strip().splitlines()[0].strip() if out.strip() else ""
    if code != 0 or not account:
        raise RuntimeError(
            "Google Cloud authentication is unavailable. Run:\n"
            "  gcloud auth login\n"
            "  gcloud auth application-default login"
        )
    return account


async def configure_docker_auth(
    region: str, progress_callback: ProgressCallback = None
) -> Dict[str, Any]:
    """Configure Docker credential helper for Artifact Registry."""
    host = f"{region}-docker.pkg.dev"
    await _emit(progress_callback, f"$ gcloud auth configure-docker {host}")
    code, out = await _run(
        ["gcloud", "auth", "configure-docker", host, "--quiet"],
        AUTH_TIMEOUT_SECONDS,
    )
    if code != 0:
        raise RuntimeError(
            "Failed to configure Docker authentication for Artifact Registry.\n"
            f"{out.strip()[:1000]}\n"
            "Run: gcloud auth login, then retry."
        )
    return {"success": True, "host": host}


async def tag_image(
    local_tag: str, remote_ref: str, progress_callback: ProgressCallback = None
) -> Dict[str, Any]:
    local_tag = (local_tag or "").strip()
    remote_ref = (remote_ref or "").strip()
    if not local_tag or not remote_ref:
        raise ValueError("Both local image tag and remote reference are required.")
    await _emit(progress_callback, f"$ docker tag {local_tag} {remote_ref}")
    code, out = await _run(["docker", "tag", local_tag, remote_ref], AUTH_TIMEOUT_SECONDS)
    if code != 0:
        raise RuntimeError(f"Failed to tag image.\n{out.strip()[:1000]}")
    return {"success": True, "remote_ref": remote_ref}


async def push_image(
    remote_ref: str, progress_callback: ProgressCallback = None
) -> Dict[str, Any]:
    """Push the tagged image. Streams progress lines; raises on failure."""
    remote_ref = (remote_ref or "").strip()
    if not remote_ref:
        raise ValueError("Remote image reference is empty.")
    await _emit(progress_callback, f"$ docker push {remote_ref}")
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "push",
        remote_ref,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    logs: list[str] = []
    try:
        assert proc.stdout is not None
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=PUSH_TIMEOUT_SECONDS)
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logs.append(text)
                await _emit(progress_callback, text)
        await asyncio.wait_for(proc.wait(), timeout=60)
    except asyncio.TimeoutError as exc:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError(f"Image push timed out after {PUSH_TIMEOUT_SECONDS}s.") from exc

    if proc.returncode != 0:
        tail = "\n".join(logs[-20:]) if logs else "(no output)"
        hint = ""
        lowered = tail.lower()
        if "denied" in lowered or "permission" in lowered or "unauthorized" in lowered:
            hint = (
                "\nHint: push permission denied. Ensure the Artifact Registry "
                "repository exists and your account has roles/artifactregistry.writer. "
                "Create it with: gcloud artifacts repositories create REPO "
                "--repository-format=docker --location=REGION"
            )
        if "not found" in lowered or "does not exist" in lowered:
            hint += (
                "\nHint: the Artifact Registry repository may not exist. Create it with: "
                "gcloud artifacts repositories create REPO "
                "--repository-format=docker --location=REGION"
            )
        raise RuntimeError(f"Image push failed (exit {proc.returncode}).\n{tail}{hint}")
    return {"success": True, "remote_ref": remote_ref, "logs": logs}


def parse_gcloud_account_list(output: str) -> str:
    """Pure helper (unit-testable): first active account from gcloud output."""
    for line in (output or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def extract_push_hint(output: str) -> str:
    """Pure helper (unit-testable): actionable hint for a push failure."""
    lowered = (output or "").lower()
    if "denied" in lowered or "permission" in lowered or "unauthorized" in lowered:
        return "permission-denied"
    if "not found" in lowered or "does not exist" in lowered:
        return "repository-missing"
    return ""
