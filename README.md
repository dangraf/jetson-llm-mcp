# jetson-llm-mcp

An MCP server that exposes local LLMs running on a Jetson AGX Xavier to Claude Code.

Two tools: `ask_jetson` (send a prompt to a local model) and
`check_jetson_status` (see what is available and what is loaded).

The point is to offload small, cheap work — quick classifications, short code
review, sanity checks — to hardware you already own, instead of spending API
tokens on it.

## Target

The server talks to **`jetson-xav2`** over HTTP, to a stock ollama install on
port 11434. Nothing needs to be installed on the Jetson beyond ollama itself,
and `ollama.service` is enabled there, so it comes back on its own after a
reboot:

```console
$ ssh [name]@[host] 'systemctl is-enabled ollama; systemctl is-active ollama'
enabled
active
```

Available models:

| Model | Notes |
| --- | --- |
| `qwen3-coder:30b` | Default. Plain answers, no reasoning trace. |
| `qwen3:30b-thinking` | Emits a chain of thought — see the caveat below. |

## Performance

Measured on `jetson-xav2` with `qwen3-coder:30b`:

```console
$ curl -s http://jetson-xav2:11434/api/generate -d '{...,"options":{"num_predict":60}}'
load      : 0.3 s
eval      : 24 tokens on 1.3 s  => 18.92 tok/s
```

So roughly **19 tok/s once warm**, plus about **30 s** the first time a model
is loaded after an idle period. Budget `max_tokens` accordingly — the default
of 150 is a few seconds of generation on a warm model.

## Two constraints worth knowing

**Only one 30b model fits at a time.** The Xavier has unified memory — the GPU
shares the system's ~30 GiB rather than having its own VRAM — and a loaded 30b
model occupies ~25 GB of it. Asking for the other one evicts the first, and asking while
the first is still resident can fail outright:

```json
{"error":{"message":"model failed to load, this may be due to resource
limitations or an internal error, check ollama server logs for details"}}
```

`check_jetson_status` reports what is currently resident, so you can tell a
slow first call from a genuine problem.

**Thinking models put their reasoning in a separate field.** With
`qwen3:30b-thinking`, ollama's OpenAI-compatible endpoint returns the chain of
thought in `reasoning` and leaves `content` empty when `max_tokens` runs out
mid-thought. Reading `content` alone yields a silent empty string — exactly
what low `max_tokens` provokes. `ask_jetson` falls back to `reasoning` and
labels it:

```
[no answer — only reasoning, length]
We are to determine if 17 is a prime number.
 A prime number is a natural number greater than 1 that has no positive divisors
```

If you see that, raise `max_tokens` or use the default non-thinking model.

## Setup

Requires Python 3.10+, `mcp>=1.0` and `httpx>=0.27`. Register it with Claude
Code as a stdio server:

```json
{
  "mcpServers": {
    "jetson-llm": {
      "type": "stdio",
      "command": "/path/to/python3",
      "args": ["/path/to/jetson-llm-mcp/server.py"]
    }
  }
}
```

After editing `server.py`, reconnect the server (`/mcp` → `jetson-llm`) — for a
stdio server that spawns a fresh process and re-reads the file. A full restart
of Claude Code is only needed if you change the configuration above, which is
read at session start.

## Why not jetson-xav1

`jetson-xav1` also exists and also runs ollama, hosting `deepseek-r1:32b`,
`deepseek-r1:14b` and a `deepseek32b-slim` derivative. It is deliberately not
used:

- deepseek-r1 is older, and the distilled qwen3 models on xav2 do the same jobs
  better.
- Its 32b path ran through a hand-built `llama.cpp` on port 11435 at **~1.4
  tok/s**, about 13× slower than xav2.
- That llama-server has **no systemd unit**. It was started by hand via
  `~/start_llama_server.sh`, so it does not survive a reboot — which is why
  this server pointed at a dead port until it was retargeted.
- ollama and llama-server cannot share the Xavier's NvMap CUDA carveout, so
  running both on one machine means fighting over memory. The start script
  works around that with `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` and `-ngl 32`
  (32 layers on GPU, 32 on CPU, against an NvMap limit of ~9–13 GB).

If xav1 is ever brought back, it needs a host argument here and a systemd unit
there.
