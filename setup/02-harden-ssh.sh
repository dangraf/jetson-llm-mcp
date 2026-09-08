#!/bin/bash
# Stäng av lösenordsinloggning på jetsonen.
#
# Jetsons levereras med lösenordsinloggning påslagen och sshd på 0.0.0.0:22.
# Så länge kontonamnet är känt är det bara ett lösenord som står emellan.
# Kör detta EFTER att din nyckel är på plats — skriptet vägrar annars.
#
# Kör som root:  sudo bash 02-harden-ssh.sh [användare]

set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Kör med sudo."; exit 1; }

USER_NAME="${1:-${SUDO_USER:-$(logname 2>/dev/null || echo root)}}"
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"
KEYS="$HOME_DIR/.ssh/authorized_keys"

# Att stänga av lösenord utan fungerande nyckel låser ute dig permanent.
if [ ! -s "$KEYS" ]; then
    echo "AVBRYTER: $KEYS saknas eller är tom."
    echo "Kör först, från din egen dator:  ssh-copy-id $USER_NAME@<jetson>"
    exit 1
fi
echo "Nycklar för $USER_NAME: $(grep -c . "$KEYS") st — säkert att fortsätta"

# Ubuntu 20.04 har Include-raden nära toppen av sshd_config, så en drop-in
# vinner. Saknas den gör drop-innen ingenting — kolla hellre än att anta.
if ! grep -q "^Include /etc/ssh/sshd_config.d" /etc/ssh/sshd_config; then
    echo "AVBRYTER: sshd_config saknar Include-rad; en drop-in skulle ignoreras"
    echo "och du skulle tro att maskinen var härdad utan att den var det."
    exit 1
fi

mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/10-hardening.conf <<'EOF'
# Nycklar fungerar redan; lösenord är kvar bara som brute force-yta.
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitRootLogin prohibit-password
EOF

# Validera INNAN omladdning — en trasig config som laddas låser ute dig.
if ! sshd -t; then
    echo "AVBRYTER: sshd -t underkände konfigurationen. Tar bort den igen."
    rm -f /etc/ssh/sshd_config.d/10-hardening.conf
    exit 1
fi

# reload, inte restart: befintliga sessioner överlever.
systemctl reload ssh

echo
echo "===== RESULTAT ====="
sshd -T | grep -iE "^passwordauthentication|^permitrootlogin|^pubkeyauthentication" | sed 's/^/  /'
echo
echo "Stäng INTE denna session förrän du verifierat en ny inloggning"
echo "från ett annat fönster."
