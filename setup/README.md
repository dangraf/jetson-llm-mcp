# Setting up a Jetson for this MCP server

Scripts for taking a Jetson AGX Xavier from a fresh JetPack 5 install to a
machine this server can talk to. Written for `jetson-xav2` (L4T R35.6.4,
Ubuntu 20.04, CUDA 11.4) and kept here so the work is repeatable.

All of them require root on the Jetson, print what they change, back up
anything they touch, and abort rather than half-apply. Read one before
running it.

## Order

| Script | What it does |
| --- | --- |
| `01-upgrade-ollama.sh [version]` | Installs or upgrades ollama. Defaults to v0.33.3. |
| `02-harden-ssh.sh [user]` | Turns off password login. Refuses if no key is installed. |
| `03-restrict-ollama.sh` | Leaves ollama on `0.0.0.0` but firewalls port 11434 to loopback and tailnet. |
| `04-tune-memory.sh` | Flash attention, `q8_0` KV cache, and one loaded model at a time. |

Run `ssh-copy-id` before step 2, or it will (correctly) refuse to lock you out.

`fix-stuck-pull.sh <digest>` is not part of setup — it repairs a download
that fails with `Error: EOF` at `pulling manifest`. Run it with no arguments
to list candidates.

## Why the scripts look the way they do

**ollama stays bound to `0.0.0.0`.** Binding it to the tailscale address does
close the LAN hole, but it also breaks `127.0.0.1`, so `ollama pull` and
`ollama list` stop working without an `OLLAMA_HOST` variable in every shell.
The firewall achieves the same protection while leaving the defaults intact.
Note the failure mode if you ever try it: ollama's error says
`run 'ollama serve' to start it` even though the server is running, which
invites you to start a second process that fights the first for the GPU.

**One model at a time.** `OLLAMA_MAX_LOADED_MODELS` defaults to 0, meaning
unlimited. The Xavier shares one memory pool between CPU and GPU and fits
exactly one 20+ GB model, so a second client asking for a different model
takes the whole machine down instead of queueing. Setting it to 1 evicts
instead.

**Quantized KV cache.** `qwen3.6:35b-a3b` has 41 layers but only 2 KV heads,
so its cache costs ~82 KiB/token in f16 and about half that in `q8_0`.
Flash attention is a prerequisite for the quantized cache.

**Never restart ollama during a pull.** It leaves zero-byte state files that
make every later pull of that blob fail instantly. That is what
`fix-stuck-pull.sh` exists for.

## Platform ceiling

Jetson AGX Xavier tops out at JetPack 5.1.5 / L4T 35.6.2 — JetPack 6 requires
Orin, so CUDA stays at 11.4 and Ubuntu at 20.04 permanently. This does not
block ollama: it still publishes `ollama-linux-arm64-jetpack5`, selected by
`grep R35 /etc/nv_tegra_release` in the official installer. Note the artifacts
are `.tar.zst`; older `.tgz` URLs now return 404.

## Provenance

`01`, `03` and `04` are the scripts that were actually run on `jetson-xav2`,
with paths parameterized. `02` is the SSH half of a larger script that also
did the `OLLAMA_HOST` binding described above; that half was dropped rather
than shipped. `02` and `fix-stuck-pull.sh` have not been run in this exact
form — review them with that in mind.
