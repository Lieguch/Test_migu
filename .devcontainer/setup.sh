#!/bin/bash
# Codespaces post-create setup: clone QEMU source and prepare build directory
set -euo pipefail

echo "=== Setup: QEMU source ==="
cd /workspace
if [ ! -d qemu-src/.git ]; then
    git clone --depth 1 --branch v10.0.1 https://github.com/qemu/qemu.git qemu-src || true
fi

echo "=== Setup: verify toolchain ==="
gcc --version | head -1
aarch64-linux-gnu-gcc --version | head -1 || true
arm-none-eabi-gcc --version | head -1 || true
qemu-system-arm --version | head -1 || true

echo "=== Setup: QEMU build deps check ==="
ninja --version
python3 --version

echo "=== Setup done ==="
