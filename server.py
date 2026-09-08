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

# num_batch is not a tuning knob here, it is the difference between working
# and taking the whole machine down. At ollama's default of 512, a prompt over
# roughly 1000 tokens hard-hangs the Xavier: no OOM message, no thermal event,
# no kernel log, the box simply stops answering ICMP and needs a power cycle.
# System memory stays flat at ~6 GB free throughout, so the spike is not in
# RAM — most likely the Tegra NvMap allocator, which hangs the SoC rather than
# failing an allocation. At 128 the same prompts pass.
#
# Measured end to end on jetson-xav2 with qwen3.6:35b-a3b at num_batch=128:
#   1030 tokens in  8192 ctx ->  94 tok/s prefill
#   3522 tokens in  4096 ctx -> 122 tok/s
#   7522 tokens in  8192 ctx -> 126 tok/s   (nearly a full window)
# Bigger contexts load fine but have not been proven with a long prompt.
NUM_CTX = 8192
NUM_BATCH = 128

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
    Prefill runs at ~120 tok/s, so a 7500-token prompt costs about a minute.
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
            "num_ctx": max(512, min(num_ctx, 16384)),
            "num_batch": NUM_BATCH,
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
