"""Jetson LLM MCP server — exposes local Jetson models to Claude Code.

Both tools use deepseek-r1:32b via llama-server (port 11435).
ollama (port 11434) cannot share the NvMap CUDA carveout with llama-server,
so 14b is not available while 32b is loaded. Use ask_jetson for all queries.
"""

import httpx
from mcp.server.fastmcp import FastMCP

JETSON_HOST = "jetson-xav1"
OLLAMA_PORT = 11434   # ollama — available when llama-server is NOT running
LLAMA_PORT = 11435    # deepseek-r1:32b via llama-server (OpenAI-compatible)

TIMEOUT = 120  # 32b ~1.4 tok/s; 120s ≈ ~170 tokens

mcp = FastMCP("jetson-llm")


def _llama_url(path: str) -> str:
    return f"http://{JETSON_HOST}:{LLAMA_PORT}{path}"


@mcp.tool()
async def ask_jetson(prompt: str, max_tokens: int = 150) -> str:
    """
    Ask deepseek-r1:32b on Jetson AGX Xavier (jetson-xav1, port 11435).
    Speed: ~1.4 tok/s — keep max_tokens low for fast responses.
    Default max_tokens=150 (~1-2 min). Use max_tokens=50 for yes/no answers.
    Use for: quick classifications, short code review, sanity checks.
    NOT for: long analysis or tasks Claude can handle directly.
    """
    payload = {
        "model": "deepseek-r1:32b",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": max(10, min(max_tokens, 400)),
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(_llama_url("/v1/chat/completions"), json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


@mcp.tool()
async def check_jetson_status() -> str:
    """Check if the Jetson LLM services are online and which models are loaded."""
    results = []

    async with httpx.AsyncClient(timeout=5) as client:
        try:
            r = await client.get(f"http://{JETSON_HOST}:{OLLAMA_PORT}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            results.append(f"ollama (port {OLLAMA_PORT}): OK — models: {models}")
        except Exception as e:
            results.append(f"ollama (port {OLLAMA_PORT}): OFFLINE — {e}")

        try:
            r = await client.get(_llama_url("/v1/models"))
            models = [m["id"] for m in r.json().get("data", [])]
            results.append(f"llama-server (port {LLAMA_PORT}): OK — models: {models}")
        except Exception as e:
            results.append(f"llama-server (port {LLAMA_PORT}): OFFLINE — {e}")

    return "\n".join(results)


if __name__ == "__main__":
    mcp.run(transport="stdio")
