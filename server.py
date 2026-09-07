"""Jetson LLM MCP server — exposes local Jetson models to Claude Code.

Targets jetson-xav2, which runs a stock ollama install on port 11434.
jetson-xav1 is deliberately not used: its deepseek-r1 models are older and
slower (~1.4 tok/s via a hand-built llama-server), and the distilled qwen3
models on xav2 outperform them at ~19 tok/s.

Only one 30b model fits in VRAM at a time — asking for a second one while
another is loaded fails with "model failed to load".
"""

import httpx
from mcp.server.fastmcp import FastMCP

JETSON_HOST = "jetson-xav2"
OLLAMA_PORT = 11434

DEFAULT_MODEL = "qwen3-coder:30b"   # plain answers, no reasoning trace
THINKING_MODEL = "qwen3:30b-thinking"

# Warm generation is ~19 tok/s, but a cold model costs ~30s to load.
TIMEOUT = 120

mcp = FastMCP("jetson-llm")


def _url(path: str) -> str:
    return f"http://{JETSON_HOST}:{OLLAMA_PORT}{path}"


@mcp.tool()
async def ask_jetson(
    prompt: str,
    max_tokens: int = 150,
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Ask a local model on Jetson AGX Xavier (jetson-xav2, port 11434).
    Speed: ~19 tok/s once warm; the first call after an idle period adds
    ~30s of model loading. Default max_tokens=150.
    Models: qwen3-coder:30b (default), qwen3:30b-thinking (shows reasoning).
    Switching model evicts the loaded one — only one 30b fits in VRAM.
    Use for: quick classifications, short code review, sanity checks.
    NOT for: long analysis or tasks Claude can handle directly.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": max(10, min(max_tokens, 400)),
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(_url("/v1/chat/completions"), json=payload)
        r.raise_for_status()
        data = r.json()

    if "error" in data:
        return f"Jetson error: {data['error'].get('message', data['error'])}"

    choice = data["choices"][0]
    message = choice["message"]
    content = (message.get("content") or "").strip()

    # Thinking models put the chain of thought in a separate field and leave
    # content empty when max_tokens runs out mid-thought. Surface it rather
    # than returning a silent empty string.
    if not content:
        reasoning = (message.get("reasoning") or "").strip()
        if reasoning:
            return f"[no answer — only reasoning, {choice['finish_reason']}]\n{reasoning}"
        return f"[empty response from {model}, finish_reason={choice['finish_reason']}]"

    return content


@mcp.tool()
async def check_jetson_status() -> str:
    """Check if the Jetson LLM service is online, which models are available,
    and which one is currently loaded in VRAM."""
    results = []

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(_url("/api/tags"))
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            results.append(f"{JETSON_HOST}:{OLLAMA_PORT} — OK, available: {models}")
        except Exception as e:
            results.append(f"{JETSON_HOST}:{OLLAMA_PORT} — OFFLINE: {e}")
            return "\n".join(results)

        try:
            r = await client.get(_url("/api/ps"))
            r.raise_for_status()
            loaded = [
                f"{m['name']} ({m['size_vram'] / 1e9:.1f} GB VRAM)"
                for m in r.json().get("models", [])
            ]
            results.append(f"loaded: {loaded or 'none — next call pays ~30s load'}")
        except Exception as e:
            results.append(f"loaded: unknown — {e}")

    return "\n".join(results)


if __name__ == "__main__":
    mcp.run(transport="stdio")
