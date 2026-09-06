import asyncio
import json
from typing import Dict, Any, Optional, Union
from dotenv import load_dotenv
import re

from .ai_providers import (
    build_dockerfile_prompt,
    generate_dockerfile_text,
    get_ai_config,
)

# Load environment variables
load_dotenv()


def _safe_print(text: str, **kwargs: Any) -> None:
    """Print that never crashes on non-UTF-8 Windows consoles (cp1252, ...)."""
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"), **kwargs)


async def create_container_tool(
    gitingest_summary: str,
    gitingest_tree: str,
    gitingest_content: str,
    project_name: Optional[str] = None,
    additional_instructions: Optional[str] = None,
    max_context_chars: int = 50000,  # Limit to stay within context window
    websocket: Optional[Any] = None  # WebSocket connection for streaming
) -> Dict[str, Any]:
    """
    Generate a Dockerfile using the configured AI provider based on gitingest context.

    The provider is selected via AI_PROVIDER (openrouter/gemini/groq/openai,
    default openrouter). The prompt, JSON contract, WebSocket streaming
    protocol and return shape are identical for every provider.
    """
    try:
        # Resolve the AI provider (default: openrouter free-tier models).
        # Raises ValueError for unknown providers; missing keys raise
        # provider-specific errors inside generate_dockerfile_text.
        ai_config = get_ai_config()

        # Truncate content if it exceeds max context to avoid hitting limits
        truncated_content = gitingest_content
        if len(gitingest_content) > max_context_chars:
            truncated_content = gitingest_content[:max_context_chars] + "\n\n... [Content truncated due to length] ..."

        # Shared prompt — identical for every provider.
        prompt = build_dockerfile_prompt(
            gitingest_summary, gitingest_tree, truncated_content, additional_instructions
        )

        # Generate via the selected provider with streaming
        websocket_active = await _emit_ws_message(
            websocket, "status", f"🐳 Generating Dockerfile with {ai_config.provider}..."
        )
        if websocket_active:
            _safe_print(f"🐳 Generating Dockerfile with {ai_config.provider}... (streaming response)\n")
        
        # Collect the provider's response with streaming.
        # The provider emits text via the callback (prints + WS chunks);
        # the full text comes back in the result — never counted twice.
        dockerfile_response = ""
        if websocket_active:
            websocket_active = await _emit_ws_message(websocket, "stream_start", "Starting generation...")
        _safe_print("📝 Response:")
        _safe_print("-" * 50)

        async def _on_provider_chunk(text: str) -> None:
            nonlocal websocket_active
            _safe_print(text, end="", flush=True)
            # Only emit chunks if WebSocket is still active
            if websocket_active:
                websocket_active = await _emit_ws_message(websocket, "chunk", text)

        generated = await generate_dockerfile_text(prompt, ai_config, _on_provider_chunk)
        dockerfile_response = generated["text"]

        _safe_print("\n" + "-" * 50)
        _safe_print("✅ Generation complete!\n")
        if websocket_active:
            await _emit_ws_message(websocket, "status", "✅ Generation complete!")
        
        # Try to parse as JSON, fallback to plain text if needed
        try:
            # First try direct JSON parsing
            dockerfile_data = json.loads(dockerfile_response)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            try:
                # Look for JSON in code blocks
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', dockerfile_response, re.DOTALL)
                if json_match:
                    dockerfile_data = json.loads(json_match.group(1))
                else:
                    # Try to find JSON-like content
                    json_match = re.search(r'(\{[^{}]*"dockerfile"[^{}]*\})', dockerfile_response, re.DOTALL)
                    if json_match:
                        dockerfile_data = json.loads(json_match.group(1))
                    else:
                        raise json.JSONDecodeError("No JSON found", "", 0)
            except (json.JSONDecodeError, AttributeError):
                # If still no valid JSON, treat as plain Dockerfile content
                # Try to extract just the Dockerfile if it looks like one
                dockerfile_content = dockerfile_response
                if 'FROM ' in dockerfile_response:
                    # Extract lines that look like Dockerfile commands
                    lines = dockerfile_response.split('\n')
                    dockerfile_lines = []
                    in_dockerfile = False
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith('FROM ') or stripped.startswith('RUN ') or stripped.startswith('COPY ') or stripped.startswith('WORKDIR ') or stripped.startswith('EXPOSE ') or stripped.startswith('CMD ') or stripped.startswith('ENTRYPOINT '):
                            in_dockerfile = True
                            dockerfile_lines.append(line)
                        elif in_dockerfile and (stripped.startswith('#') or stripped == '' or stripped.startswith('ENV ') or stripped.startswith('ARG ') or stripped.startswith('USER ') or stripped.startswith('VOLUME ') or stripped.startswith('LABEL ')):
                            dockerfile_lines.append(line)
                        elif in_dockerfile and not stripped:
                            dockerfile_lines.append(line)
                        elif in_dockerfile and stripped and not any(stripped.startswith(cmd) for cmd in ['FROM', 'RUN', 'COPY', 'WORKDIR', 'EXPOSE', 'CMD', 'ENTRYPOINT', 'ENV', 'ARG', 'USER', 'VOLUME', 'LABEL', '#']):
                            break
                    
                    if dockerfile_lines:
                        dockerfile_content = '\n'.join(dockerfile_lines).strip()

                dockerfile_data = {
                    "dockerfile": dockerfile_content,
                    "base_image_reasoning": "Generated as plain text response",
                    "technology_stack": "Could not parse detailed analysis",
                    "port_recommendations": [],
                    "additional_notes": "Response was not in expected JSON format",
                    "docker_compose_suggestion": None
                }
        
        return {
            "success": True,
            "dockerfile": dockerfile_data.get("dockerfile", ""),
            "base_image_reasoning": dockerfile_data.get("base_image_reasoning", ""),
            "technology_stack": dockerfile_data.get("technology_stack", ""),
            "port_recommendations": dockerfile_data.get("port_recommendations", []),
            "additional_notes": dockerfile_data.get("additional_notes", ""),
            "docker_compose_suggestion": dockerfile_data.get("docker_compose_suggestion"),
            "project_name": project_name or "generated-project",
            "ai_provider": generated.get("provider", ai_config.provider),
            "ai_model": generated.get("model", ai_config.model),
            "context_truncated": len(gitingest_content) > max_context_chars,
            "original_content_length": len(gitingest_content),
            "used_content_length": len(truncated_content)
        }
        
    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "project_name": project_name or "unknown-project"
        }
        # Only send error message if WebSocket might still be active
        try:
            await _emit_ws_message(websocket, "error", str(e))
        except:
            # WebSocket is definitely closed, just log the error
            print(f"Could not send error to WebSocket: {e}")
        return error_result


async def _emit_ws_message(websocket: Optional[Any], message_type: str, content: str) -> bool:
    """
    Helper function to emit WebSocket messages safely.
    Returns True if message was sent successfully, False if WebSocket is closed or error occurred.
    """
    if websocket is not None:
        try:
            message = {
                "type": message_type,
                "content": content,
                "timestamp": asyncio.get_event_loop().time()
            }
            await websocket.send_text(json.dumps(message))
            return True
        except Exception as e:
            # WebSocket is likely closed, stop trying to send messages
            print(f"WebSocket closed or error occurred: {e}")
            return False
    return False


def run_create_container(
    gitingest_summary: str,
    gitingest_tree: str,
    gitingest_content: str,
    project_name: Optional[str] = None,
    additional_instructions: Optional[str] = None,
    websocket: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Synchronous wrapper for the create_container tool.
    
    Args:
        gitingest_summary (str): Summary from gitingest analysis
        gitingest_tree (str): Directory tree from gitingest
        gitingest_content (str): Full content from gitingest
        project_name (str, optional): Name of the project
        additional_instructions (str, optional): Additional instructions for Dockerfile generation
        websocket (Any, optional): WebSocket connection for streaming
        
    Returns:
        Dict[str, Any]: Dictionary containing generated Dockerfile and metadata
    """
    return asyncio.run(create_container_tool(
        gitingest_summary, gitingest_tree, gitingest_content, project_name, additional_instructions, websocket=websocket
    ))


# Tool definition for OpenAI Agents SDK
create_container_function = {
    "type": "function",
    "function": {
        "name": "generate_dockerfile",
        "description": "Generate a production-ready Dockerfile based on repository analysis from gitingest",
        "parameters": {
            "type": "object",
            "properties": {
                "gitingest_summary": {
                    "type": "string",
                    "description": "Summary of the repository from gitingest analysis"
                },
                "gitingest_tree": {
                    "type": "string",
                    "description": "Directory tree structure from gitingest"
                },
                "gitingest_content": {
                    "type": "string",
                    "description": "Full source code content from gitingest"
                },
                "project_name": {
                    "type": "string",
                    "description": "Optional name for the project/container"
                },
                "additional_instructions": {
                    "type": "string",
                    "description": "Optional additional instructions for customizing the Dockerfile generation"
                }
            },
            "required": ["gitingest_summary", "gitingest_tree", "gitingest_content"]
        }
    }
} 