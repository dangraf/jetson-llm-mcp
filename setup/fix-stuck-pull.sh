#!/bin/bash
# Laga en nedladdning som fastnat med "Error: EOF" vid "pulling manifest".
#
# Startas ollama om mitt i en `ollama pull` lämnas nollbytes-tillståndsfiler
# efter sig (blobs/sha256-<digest>-partial-N, normalt ~60 byte JSON). Nästa
# pull läser dem, får EOF på under en sekund och avbryter innan nedladdningen
# börjar. Symptomet ser ut som ett nätverksfel men är helt lokalt.
#
# Delar två taggar samma blob drabbas båda.
#
# Diagnos först: går en ANNAN ny modell att hämta? Gör den det är nätverket
# och brandväggen oskyldiga, och det här skriptet är rätt åtgärd.
#
# Kör som root:  sudo bash fix-stuck-pull.sh <digest-prefix>
# Exempel:       sudo bash fix-stuck-pull.sh d372de8e9348

set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Kör med sudo."; exit 1; }

BLOBS=${OLLAMA_MODELS:-/usr/share/ollama/.ollama/models}/blobs
PREFIX="${1:-}"

if [ -z "$PREFIX" ]; then
    echo "Ange ett digest-prefix. Ofullständiga nedladdningar just nu:"
    ls "$BLOBS"/*-partial 2>/dev/null | sed 's|.*/sha256-|  |; s|-partial||' || echo "  (inga)"
    echo
    echo "Tomma tillståndsfiler (0 byte = trasiga):"
    find "$BLOBS" -name "*-partial-*" -size 0 2>/dev/null | sed 's|.*/|  |' || echo "  (inga)"
    exit 1
fi

MATCHES=$(ls "$BLOBS"/sha256-"$PREFIX"*-partial* 2>/dev/null | wc -l)
[ "$MATCHES" -gt 0 ] || { echo "Inga partial-filer matchar $PREFIX"; exit 1; }

echo "=== FÖRE ($MATCHES filer) ==="
ls -l "$BLOBS"/sha256-"$PREFIX"*-partial* | awk '{print "  ", $5, "byte", $9}' | head -5

# Bara den här blobens partial-filer. Kompletta blobar och andra pågående
# nedladdningar lämnas orörda.
rm -f "$BLOBS"/sha256-"$PREFIX"*-partial*

echo "=== EFTER ==="
ls "$BLOBS"/sha256-"$PREFIX"*-partial* 2>/dev/null || echo "  (borta)"
echo
echo "Kör om din 'ollama pull'. Nedladdningen börjar från noll."
echo "ollama behöver INTE startas om — och gör du det mitt i nästa pull"
echo "hamnar du här igen."
