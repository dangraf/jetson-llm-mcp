#!/bin/bash
# Återställ ollamas standardbeteende utan att öppna LAN-hålet igen.
#
# Före:  OLLAMA_HOST=100.83.67.5 -> LAN stängt, men 127.0.0.1 dog, så
#        "ollama pull" krävde en miljövariabel. Oacceptabelt.
# Efter: OLLAMA_HOST=0.0.0.0     -> allt fungerar som standard,
#        och iptables släpper bara igenom lo + tailscale0 på 11434.
#
# Kör som root:  sudo bash 03-restrict-ollama.sh

set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Kör med sudo."; exit 1; }
STAMP="$(date +%Y%m%d-%H%M%S)"

# --- 1. brandväggsregler som en tjänst, så de överlever reboot ---
cat > /usr/local/sbin/ollama-firewall.sh <<'EOF'
#!/bin/bash
# Endast loopback och tailnet får nå ollama. Allt annat (eth0/LAN) nekas.
set -u
PORT=11434
# Rensa tidigare regler så skriptet kan köras om utan att stapla dubbletter.
while iptables -D INPUT -p tcp --dport $PORT -i lo -j ACCEPT 2>/dev/null; do :; done
while iptables -D INPUT -p tcp --dport $PORT -i tailscale0 -j ACCEPT 2>/dev/null; do :; done
while iptables -D INPUT -p tcp --dport $PORT -j DROP 2>/dev/null; do :; done
# Ordningen är avgörande: tillåt först, neka sist.
iptables -A INPUT -p tcp --dport $PORT -i lo         -j ACCEPT
iptables -A INPUT -p tcp --dport $PORT -i tailscale0 -j ACCEPT
iptables -A INPUT -p tcp --dport $PORT              -j DROP
EOF
chmod 755 /usr/local/sbin/ollama-firewall.sh

cat > /etc/systemd/system/ollama-firewall.service <<'EOF'
[Unit]
Description=Restrict ollama port 11434 to loopback and tailnet
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/ollama-firewall.sh

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now ollama-firewall.service

# --- 2. lämna tillbaka standardadressen till ollama ---
OV=/etc/systemd/system/ollama.service.d/override.conf
mkdir -p "$(dirname "$OV")"
[ -f "$OV" ] || printf '[Service]\n' > "$OV"
cp -a "$OV" "$OV.bak-$STAMP"
grep -q OLLAMA_HOST "$OV" || printf 'Environment="OLLAMA_HOST=0.0.0.0:11434"\n' >> "$OV"
sed -i 's|^Environment="OLLAMA_HOST=.*"|Environment="OLLAMA_HOST=0.0.0.0:11434"|' "$OV"
grep -q 'OLLAMA_HOST=0.0.0.0:11434' "$OV" || { echo "AVBRYTER: kunde inte sätta OLLAMA_HOST"; exit 1; }

systemctl daemon-reload
systemctl restart ollama
sleep 15

echo
echo "===== RESULTAT ====="
echo "-- lyssnar på --";        ss -ltn | grep 11434
echo "-- brandväggsregler --";  iptables -S INPUT | grep 11434
echo "-- lokalt anrop utan variabler (ska ge 200) --"
curl -s -o /dev/null -w "   127.0.0.1 -> HTTP %{http_code}\n" http://127.0.0.1:11434/api/version
echo "-- ollama-klienten utan variabler --"
env -u OLLAMA_HOST /usr/local/bin/ollama list 2>&1 | head -4
