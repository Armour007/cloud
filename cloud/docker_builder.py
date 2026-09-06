"""Safe Docker image builds.

Builds the AI-generated Dockerfile against the cloned application source.
Uses subprocess argument arrays only (never shell strings) and streams
build output line-by-line to an optional async progress callback.
"""

import asyncio
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .config import is_docker_available

# File name (inside the build context) that carries the AI-generated Dockerfile.
# Using a dedicated name avoids clobbering any Dockerfile already in the repo.
GENERATED_DOCKERFILE_NAME = "Dockerfile.gitcontainer-cloud"

BUILD_TIMEOUT_SECONDS = 600

ProgressCallback = Optional[Callable[[str], Awaitable[Any]]]


async def _emit(callback: ProgressCallback, line: str) -> None:
    if callback is None:
        return
    try:
        result = callback(line)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        pass


async def check_docker() -> None:
    """Raise a helpful error if the Docker CLI is unavailable."""
    if not is_docker_available():
        raise RuntimeError(
            "Docker is unavailable. Install Docker Desktop and ensure "
            "'docker' is on your PATH, then restart the app."
        )
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "info",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "Docker daemon is not reachable. Start Docker Desktop and retry."
            + (f" Details: {detail[:500]}" if detail else "")
        )


def write_generated_dockerfile(context_dir: str, dockerfile_content: str) -> str:
    """Write the generated Dockerfile into the build context. Returns its path."""
    content = (dockerfile_content or "").strip()
    if not content:
        raise ValueError("Dockerfile content is empty — nothing to build.")
    if "FROM" not in content.upper():
        raise ValueError(
            "Generated Dockerfile looks invalid (no FROM instruction). "
            "Regenerate the Dockerfile and retry."
        )
    context = Path(context_dir)
    if not context.is_dir():
        raise ValueError(f"Build context directory does not exist: {context_dir}")
    target = context / GENERATED_DOCKERFILE_NAME
    target.write_text(content + "\n", encoding="utf-8")
    return str(target)


async def build_image(
    context_dir: str,
    dockerfile_content: str,
    image_tag: str,
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """Build a Docker image. Returns {success, image_tag, logs} or raises."""
    await check_docker()

    dockerfile_path = write_generated_dockerfile(context_dir, dockerfile_content)
    dockerfile_name = os.path.basename(dockerfile_path)
    tag = (image_tag or "").strip()
    if not tag:
        raise ValueError("Image tag is empty.")

    cmd: List[str] = ["docker", "build", "-f", dockerfile_name, "-t", tag, "."]
    await _emit(progress_callback, f"$ docker build -f {dockerfile_name} -t {tag} .")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=context_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Docker executable not found on PATH.") from exc

    logs: List[str] = []
    try:
        assert proc.stdout is not None
        while True:
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=BUILD_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError as exc:
                proc.kill()
                raise RuntimeError(
                    f"Docker build timed out after {BUILD_TIMEOUT_SECONDS}s."
                ) from exc
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logs.append(text)
                # Stream only interesting progress lines to avoid WS flooding.
                if _is_worth_streaming(text):
                    await _emit(progress_callback, text)
        await asyncio.wait_for(proc.wait(), timeout=60)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        raise

    if proc.returncode != 0:
        tail = "\n".join(logs[-30:]) if logs else "(no output)"
        raise RuntimeError(f"Docker build failed (exit {proc.returncode}).\n{tail}")

    await _emit(progress_callback, f"Built image: {tag}")
    return {"success": True, "image_tag": tag, "logs": logs}


def _is_worth_streaming(line: str) -> bool:
    markers = ("Step ", " ---> ", "Successfully", "ERROR", "error", "warning", "WARNING")
    return any(m in line for m in markers) or len(line) < 160
