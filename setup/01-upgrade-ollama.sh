#!/bin/bash
# Installera eller uppgradera ollama på en JetPack 5-jetson (L4T R35).
#
# Manuell installation i stället för install.sh: vi byter bara binären och
# CUDA-biblioteken. systemd-unit, ollama-användaren och härdnings-drop-innen
# lämnas orörda.
#
# Kör som root:  sudo bash 01-upgrade-ollama.sh [version]
# Allt laddas ned och verifieras INNAN tjänsten stoppas.

set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Kör med sudo."; exit 1; }

VER="${1:-v0.33.3}"
BASEURL=https://github.com/ollama/ollama/releases/download/$VER
STAMP="$(date +%Y%m%d-%H%M%S)"
BK=/opt/ollama-backup-$STAMP
DL=/tmp/ollama-upgrade-$STAMP

# --- kontrollera att vi är på rätt plattform ---
grep -q R35 /etc/nv_tegra_release || { echo "AVBRYTER: inte en R35/JetPack 5-maskin."; exit 1; }
echo "Nuvarande version: $(/usr/local/bin/ollama --version 2>&1 | tail -1)"

# --- 1. säkerhetskopiera FÖRST ---
mkdir -p "$BK"
cp -a /usr/local/bin/ollama "$BK/ollama.bin"
tar -C /usr/local/lib -cf "$BK/lib-ollama.tar" ollama
cp -a /etc/systemd/system/ollama.service "$BK/" 2>/dev/null || true
cp -a /etc/systemd/system/ollama.service.d "$BK/" 2>/dev/null || true
echo "Säkerhetskopia: $BK  ($(du -sh "$BK" | cut -f1))"

# --- 2. hämta båda artefakterna ---
# Bundlen -jetpack5 innehåller BARA lib/ollama/cuda_jetpack5. Själva binären
# ligger i basbundlen. Båda behövs.
mkdir -p "$DL"; cd "$DL"
echo "Hämtar basbundle (1,5 GB)..."
curl -fL --retry 3 -o base.tar.zst   "$BASEURL/ollama-linux-arm64.tar.zst"
echo "Hämtar jetpack5-bundle (297 MB)..."
curl -fL --retry 3 -o jp5.tar.zst    "$BASEURL/ollama-linux-arm64-jetpack5.tar.zst"

echo "Packar upp..."
mkdir -p stage && cd stage
zstd -dc ../base.tar.zst | tar -x
zstd -dc ../jp5.tar.zst  | tar -x

# --- 3. verifiera det uppackade INNAN tjänsten rörs ---
[ -x bin/ollama ] || { echo "AVBRYTER: bin/ollama saknas i nedladdningen."; exit 1; }
[ -d lib/ollama/cuda_jetpack5 ] || { echo "AVBRYTER: cuda_jetpack5 saknas."; exit 1; }
NEW="$(./bin/ollama --version 2>&1 | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' | tail -1)"
echo "Nedladdad version: $NEW"
[ "$NEW" = "0.33.3" ] || { echo "AVBRYTER: oväntad version $NEW"; exit 1; }

# --- 4. byt ---
echo "Stoppar ollama..."
systemctl stop ollama

install -m 755 bin/ollama /usr/local/bin/ollama
# Ersätt biblioteken helt. Att blanda gamla och nya .so-filer är en säker väg
# till svårfelsökta krascher.
rm -rf /usr/local/lib/ollama
mkdir -p /usr/local/lib
cp -a lib/ollama /usr/local/lib/ollama

systemctl start ollama
sleep 20

# --- 5. verifiera ---
echo
echo "===== RESULTAT ====="
echo "-- version --";       /usr/local/bin/ollama --version 2>&1 | tail -1
echo "-- tjänst --";        systemctl is-active ollama
echo "-- lyssnar på (ska vara tailscale-adressen) --"; ss -ltn | grep 11434 || echo "  INGET på 11434"
echo "-- GPU-detektering --"
journalctl -u ollama --since "2 minutes ago" --no-pager 2>/dev/null \
  | grep -iE "inference compute|library=CUDA|no compatible GPUs|error" | tail -5
echo
echo "===== ÅTERGÅNG om något är fel ====="
echo "  sudo systemctl stop ollama"
echo "  sudo install -m 755 $BK/ollama.bin /usr/local/bin/ollama"
echo "  sudo rm -rf /usr/local/lib/ollama && sudo tar -C /usr/local/lib -xf $BK/lib-ollama.tar"
echo "  sudo systemctl start ollama"
echo
echo "Nedladdningen ligger kvar i $DL — ta bort med: sudo rm -rf $DL"
