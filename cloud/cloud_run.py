"""Google Cloud Run deployment.

Deploys a pushed Artifact Registry image to Cloud Run, waits for the
operation, then retrieves the real public service URL.

Commands use subprocess argument arrays only. The returned URL always comes
from the live `gcloud run services describe` output — never fabricated.
"""

import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

ProgressCallback = Optional[Callable[[str], Awaitable[Any]]]

DEPLOY_TIMEOUT_SECONDS = 600
DESCRIBE_TIMEOUT_SECONDS = 120


async def _emit(callback: ProgressCallback, line: str) -> None:
    if callback is None:
        return
    try:
        result = callback(line)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        pass


def build_deploy_command(
    service: str,
    image_ref: str,
    region: str,
    project_id: str,
    container_port: int,
) -> List[str]:
    """Pure helper (unit-testable): argument array for `gcloud run deploy`."""
    return [
        "gcloud",
        "run",
        "deploy",
        service,
        "--image",
        image_ref,
        "--region",
        region,
        "--project",
        project_id,
        "--platform",
        "managed",
        "--allow-unauthenticated",
        "--port",
        str(container_port),
        "--set-env-vars",
        f"PORT={container_port}",
        "--quiet",
        "--format=json",
    ]


def parse_service_url(describe_json: str) -> str:
    """Pure helper (unit-testable): extract the live URL from gcloud JSON.

    Tolerates surrounding non-JSON progress output by parsing the outermost
    {...} span.
    """
    text = describe_json or ""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise RuntimeError(
            "Cloud Run deployment finished but no service URL was returned. "
            "Check the service in the Cloud Console."
        )
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Could not parse Cloud Run deployment output as JSON.") from exc
    url = (data.get("status") or {}).get("url", "") if isinstance(data, dict) else ""
    if not url:
        raise RuntimeError(
            "Cloud Run deployment finished but no service URL was returned. "
            "Check the service in the Cloud Console."
        )
    return url


async def deploy_service(
    image_ref: str,
    service: str,
    region: str,
    project_id: str,
    container_port: int,
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    """Deploy image to Cloud Run and return the real service URL."""
    image_ref = (image_ref or "").strip()
    service = (service or "").strip()
    if not image_ref or not service or not project_id or not region:
        raise ValueError("Image, service name, region and project ID are all required.")
    if not 1 <= int(container_port) <= 65535:
        raise ValueError(f"Invalid container port: {container_port}")

    cmd = build_deploy_command(service, image_ref, region, project_id, int(container_port))
    await _emit(progress_callback, f"$ gcloud run deploy {service} --region {region} ...")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output_lines: list[str] = []
    try:
        assert proc.stdout is not None
        while True:
            line = await asyncio.wait_for(
                proc.stdout.readline(), timeout=DEPLOY_TIMEOUT_SECONDS
            )
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                output_lines.append(text)
                if len(text) < 300:
                    await _emit(progress_callback, text)
        await asyncio.wait_for(proc.wait(), timeout=60)
    except asyncio.TimeoutError as exc:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError(
            f"Cloud Run deployment timed out after {DEPLOY_TIMEOUT_SECONDS}s. "
            "Check the service status in the Cloud Console."
        ) from exc

    raw_output = "\n".join(output_lines)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Cloud Run deployment failed (exit {proc.returncode}).\n"
            f"{raw_output[-2000:] if raw_output else '(no output)'}\n"
            "Common causes: invalid port, missing IAM permission "
            "(roles/run.admin), or the container crashing on startup."
        )

    # Prefer the URL embedded in the deploy JSON output.
    try:
        url = parse_service_url(raw_output[raw_output.index("{"): raw_output.rindex("}") + 1])
        return {"success": True, "url": url, "service": service, "region": region}
    except (ValueError, RuntimeError):
        pass

    # Fallback: explicit describe call — the URL always comes from GCP.
    return await describe_service(service, region, project_id, progress_callback)


async def describe_service(
    service: str,
    region: str,
    project_id: str,
    progress_callback: ProgressCallback = None,
) -> Dict[str, Any]:
    cmd = [
        "gcloud",
        "run",
        "services",
        "describe",
        service,
        "--region",
        region,
        "--project",
        project_id,
        "--format=json",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DESCRIBE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError("Timed out while retrieving the Cloud Run service URL.") from exc
    text = (stdout or b"").decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(
            "Deployment may have succeeded but the service URL could not be retrieved.\n"
            f"{text.strip()[:1000]}"
        )
    url = parse_service_url(text)
    await _emit(progress_callback, f"Service URL: {url}")
    return {"success": True, "url": url, "service": service, "region": region}
