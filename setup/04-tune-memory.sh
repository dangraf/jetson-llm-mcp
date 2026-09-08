#!/bin/bash
# Halvera KV-cachen på jetson-xav2 genom kvantisering.
#
# qwen3.6:35b-a3b har 41 lager och bara 2 KV-huvuden -> ~82 KiB/token i f16.
# q8_0 halverar det till ~41 KiB/token, vilket dubblar den kontext som ryms
# i samma minne. Flash attention är ett krav för kvantiserad KV-cache.
#
# Sätter också OLLAMA_MAX_LOADED_MODELS=1. Standardvärdet 0 betyder
# obegränsat: ollama får försöka hålla två modeller samtidigt, vilket på en
# Xavier med 30 GB delat minne dödar hela maskinen i stället för att köa.
# Med 1 evakueras den laddade modellen i stället — långsammare, men överlever.
# Det spelar roll så fort mer än en klient pratar med maskinen.
#
# De två KV-inställningarna är samma som xav1 redan hade.
#
# Kör som root:  sudo bash 04-tune-memory.sh

set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Kör med sudo."; exit 1; }

OV=/etc/systemd/system/ollama.service.d/override.conf
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "=== FÖRE ==="; sed 's/^/  /' "$OV"

cp -a "$OV" "$OV.bak-$STAMP"
sed -i '/OLLAMA_FLASH_ATTENTION/d; /OLLAMA_KV_CACHE_TYPE/d; /OLLAMA_MAX_LOADED_MODELS/d' "$OV"
cat >> "$OV" <<'EOF'
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
EOF

echo "=== EFTER ==="; sed 's/^/  /' "$OV"

systemctl daemon-reload
systemctl restart ollama
sleep 15

echo
echo "===== RESULTAT ====="
echo -n "  tjänst: "; systemctl is-active ollama
echo "  inställningar som lästes in:"
journalctl -u ollama --since "1 min ago" --no-pager 2>/dev/null \
  | grep -oE "OLLAMA_FLASH_ATTENTION:[a-z]+|OLLAMA_KV_CACHE_TYPE:[a-z0-9_]*|OLLAMA_MAX_LOADED_MODELS:[0-9]+" | sort -u | sed 's/^/    /'
echo "  minne (inget laddat än):"; free -m | sed -n 2p | sed 's/^/    /'
echo
echo "Backup: $OV.bak-$STAMP"
