#!/usr/bin/env bash
# Wi-Fi hotspot with fallback to a known network, using NetworkManager (Raspberry Pi OS Bookworm default).
#
#   sudo ./setup_network.sh [HOTSPOT_PASSWORD]      (password >= 8 characters; asked for if omitted)
#
# How the fallback works: NetworkManager tries saved connections in order of "autoconnect-priority".
# Your home/phone Wi-Fi profiles keep the default priority (0); the hotspot profile gets -100, so it is only
# started when no known network is in range (the usual case in a dark-sky field).  Weak points, stated plainly:
#   * once the hotspot is up, NetworkManager does not go looking for a known network again; reboot the Pi
#     (or `sudo nmcli connection down PolarAlign-AP`) to rejoin home Wi-Fi.
#   * the "shared" mode starts NetworkManager's own dnsmasq (package dnsmasq-base) to hand out addresses.
# UNTESTED on a Pi: written from the NetworkManager documentation.
set -euo pipefail

SSID="${POLARALIGN_SSID:-PolarAlign}"
PASS="${1:-}"
if [[ -z "$PASS" ]]; then read -r -s -p "Hotspot password (>= 8 chars): " PASS; echo; fi
[[ ${#PASS} -ge 8 ]] || { echo "password too short" >&2; exit 1; }
command -v nmcli >/dev/null || { echo "NetworkManager (nmcli) not found" >&2; exit 1; }

# 1. the hotspot profile (idempotent: replaced if it exists)
nmcli connection delete PolarAlign-AP >/dev/null 2>&1 || true
nmcli connection add type wifi ifname wlan0 con-name PolarAlign-AP ssid "$SSID" \
    802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS" \
    ipv4.method shared ipv4.addresses 192.168.4.1/24 ipv6.method ignore \
    connection.autoconnect yes connection.autoconnect-priority -100

# 2. make sure known networks win when they are visible
for c in $(nmcli -t -f NAME,TYPE connection show | awk -F: '$2=="802-11-wireless" && $1!="PolarAlign-AP"{print $1}'); do
    nmcli connection modify "$c" connection.autoconnect-priority 0 connection.autoconnect yes || true
done

# 3. a stable name for the UI (Raspberry Pi OS Lite ships avahi): http://polaralign.local:8080
hostnamectl set-hostname polaralign || true

echo "Hotspot '$SSID' configured. Add known networks with:  sudo nmcli device wifi connect <SSID> password <PW>"
echo "Reboot, then browse to http://192.168.4.1:8080 (hotspot) or http://polaralign.local:8080 (known network)."
