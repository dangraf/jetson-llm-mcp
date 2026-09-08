"""Jetson LLM MCP server — exposes local Jetson models to Claude Code.

Targets jetson-xav2, which runs ollama on port 11434.

Uses ollama's native /api/chat rather than the OpenAI-compatible endpoint,
because only the native API accepts `options`, and `num_ctx` is not optional
here: ollama sizes the default context from total VRAM (32768) without
subtracting the model weights. The Xavier shares one pool of memory between
CPU and GPU, so 22 GB of weights plus a 32k KV cache exhausts the machine and
takes it down hard. Every request below pins num_ctx.
"""

import httpx
from mcp.server.fastmcp import FastMCP

JETSON_HOST = "jetson-xav2"
OLLAMA_PORT = 11434

DEFAULT_MODEL = "qwen3.6:35b-a3b"      # MoE, ~3B active params per token
SMALL_MODEL = "qwen3.6:27b"            # dense, smaller memory footprint
THINKING_MODEL = "qwen3:30b-thinking"  # older, emits a chain of thought

# The shutdowns that drove these numbers down were electrical, not software.
# The Jetson was on a tired 19V adapter that could not hold its rail through
# the load step from ~4W idle to ~50W under prefill, and the board browned out
# and switched itself off — no OOM, no thermal event, no kernel log, because
# nothing in software was failing. num_batch looked like the culprit only
# because a bigger batch means a steeper current transient.
#
# On a healthy 19V/60W supply, measured on jetson-xav2 with qwen3.6:35b-a3b:
#   30022 tokens in 32768 ctx, default batch -> 144 tok/s, peak draw 50.6W
# Peaks reach 84% of a 60W supply, so keep an eye on the adapter rather than
# on these constants if the machine starts dropping again.
NUM_CTX = 32768

# A cold model costs ~30s or more to load; generation itself is quick.
TIMEOUT = 180

mcp = FastMCP("jetson-llm")


def _url(path: str) -> str:
    return f"http://{JETSON_HOST}:{OLLAMA_PORT}{path}"


@mcp.tool()
async def ask_jetson(
    prompt: str,
    max_tokens: int = 150,
    model: str = DEFAULT_MODEL,
    num_ctx: int = NUM_CTX,
    think: bool = False,
) -> str:
    """
    Ask a local model on Jetson AGX Xavier (jetson-xav2, port 11434).
    The first call after an idle period adds ~30s of model loading.
    Models: qwen3.6:35b-a3b (default), qwen3.6:27b, qwen3:30b-thinking.
    Switching model evicts the loaded one — only one fits in memory.
    qwen3.6 reasons by default and would spend the whole token budget
    thinking, so thinking is off unless you pass think=True — in which case
    give it a far larger max_tokens.
    Prefill runs at ~144 tok/s, so a 30000-token prompt costs about 3 minutes.
    Use for: quick classifications, short code review, sanity checks.
    NOT for: long analysis or tasks Claude can handle directly.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": think,
        "options": {
            "num_predict": max(10, min(max_tokens, 400)),
            "num_ctx": max(512, min(num_ctx, 32768)),
        },
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(_url("/api/chat"), json=payload)
        r.raise_for_status()
        data = r.json()

        # Models without a reasoning mode reject the "think" key outright.
        # Retry without it rather than failing a perfectly valid request.
        if "error" in data and "think" in str(data["error"]).lower():
            payload.pop("think")
            r = await client.post(_url("/api/chat"), json=payload)
            r.raise_for_status()
            data = r.json()

    if "error" in data:
        return f"Jetson error: {data['error']}"

    message = data.get("message", {})
    content = (message.get("content") or "").strip()

    # Thinking models put the chain of thought in a separate field and leave
    # content empty when the token budget runs out mid-thought. Surface it
    # rather than returning a silent empty string. The native API calls it
    # "thinking"; the OpenAI-compatible one calls it "reasoning".
    if not content:
        thinking = (message.get("thinking") or message.get("reasoning") or "").strip()
        reason = data.get("done_reason", "unknown")
        if thinking:
            return f"[no answer — only reasoning, {reason}]\n{thinking}"
        return f"[empty response from {model}, done_reason={reason}]"

    return content


@mcp.tool()
async def check_jetson_status() -> str:
    """Check if the Jetson LLM service is online, which models are available,
    and which one is currently loaded in memory."""
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
                f"{m['name']} ({m['size_vram'] / 1e9:.1f} GB, ctx={m.get('context_length')})"
                for m in r.json().get("models", [])
            ]
            results.append(f"loaded: {loaded or 'none — next call pays the load time'}")
        except Exception as e:
            results.append(f"loaded: unknown — {e}")

    return "\n".join(results)


if __name__ == "__main__":
    mcp.run(transport="stdio")
