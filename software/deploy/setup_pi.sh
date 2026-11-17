#!/usr/bin/env bash
# One-shot install on Raspberry Pi OS Lite 64-bit (Bookworm).  Run as the normal user (it uses sudo for apt only).
#
#   cd /opt/polaralign/software && ./deploy/setup_pi.sh
#
# Strategy: take the heavy / hardware-bound packages from apt (numpy, scipy, Pillow, picamera2, lgpio),
# create the venv with --system-site-packages so they are visible, and pip-install only the pure-Python rest.
# That avoids building anything on a 512 MB machine and avoids mixing a pip numpy with libcamera's apt stack.
# UNTESTED on a Pi: written from the Raspberry Pi OS package names; read it before running it.
set -euo pipefail
cd "$(dirname "$0")/.."

sudo apt-get update
sudo apt-get install -y python3-venv python3-numpy python3-scipy python3-pil python3-picamera2 python3-lgpio \
    python3-serial i2c-tools network-manager dnsmasq-base --no-install-recommends

python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
# cedar-solve 0.5.1 declares Pillow<9 and numpy<2, but only uses PIL.Image/ImageDraw and plain numpy/scipy; the apt
# versions (Pillow 9.4, numpy 1.24, scipy 1.10) are fine, and Pillow<9 has no Python 3.11 wheels (it would be compiled).
# So install it without its pinned dependencies.
.venv/bin/pip install --no-deps cedar-solve
# the other pip-only dependencies, then polaralign itself without re-resolving cedar-solve's pins
.venv/bin/pip install fastapi uvicorn smbus2 pyserial
.venv/bin/pip install --no-deps -e .

sudo usermod -aG gpio,i2c,dialout,video "$USER"
mkdir -p "$HOME/.local/share/polaralign"
[[ -f data/polaralign_db.npz ]] || .venv/bin/polaralign build-db --out data/polaralign_db.npz

cat <<EOF

Next steps (see README.md):
  1. add deploy/boot-config.txt.snippet to /boot/firmware/config.txt, disable the serial console, reboot
  2. .venv/bin/polaralign selftest            # checks GPIO, TMC2209 UART, camera, I2C; moves nothing
  3. sudo ./deploy/setup_network.sh           # hotspot with fallback to known Wi-Fi
  4. sudo cp deploy/polaralign.service /etc/systemd/system/ && sudo systemctl enable --now polaralign
EOF
