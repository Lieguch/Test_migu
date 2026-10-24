#!/bin/bash
# =====================================================================
# Build QEMU v10.0.1 with RK3288 machine model (milestone 2 + patch 1)
# 并在 Codespaces 环境中运行
# =====================================================================
set -euo pipefail

echo "=== [0] env check ==="
whoami
pwd
gcc --version | head -1
ninja --version
python3 --version

echo "=== [1] clone QEMU v10.0.1 ==="
cd /workspace
if [ ! -d qemu-src/.git ]; then
    git clone --depth 1 --branch v10.0.1 https://github.com/qemu/qemu.git qemu-src
fi
cd qemu-src
git log --oneline -1

echo "=== [2] install rk3288 machine model (with patch 1) ==="
cp /workspace/qemu-harness/rk3288.c hw/arm/rk3288.c

grep -q "CONFIG_RK3288" hw/arm/Kconfig || cat >> hw/arm/Kconfig <<'EOF'

config RK3288
    bool
    select A15MPCORE
EOF

python3 - <<'PYEOF'
p = "hw/arm/meson.build"
s = open(p).read()
anchor = "system_ss.add(when: 'CONFIG_VEXPRESS', if_true: files('vexpress.c'))"
assert anchor in s, "meson anchor not found"
if "CONFIG_RK3288" not in s:
    s = s.replace(anchor, anchor + "\n    system_ss.add(if_true: files('rk3288.c'))")
    open(p, "w").write(s)
print("meson.build patched")
PYEOF

echo "=== [3] configure QEMU ==="
./configure \
    --target-list=arm-softmmu \
    --enable-debug \
    --disable-sdl \
    --disable-gtk \
    --disable-vnc \
    --disable-curses \
    --disable-spice \
    --disable-docs

echo "=== [4] build QEMU ==="
CONFIG_RC=0 BUILD2_RC=0 ninja -C build -j$(nproc)

echo "=== [5] verify machine registered ==="
./build/qemu-system-arm -machine help | grep rk3288

echo "=== BUILD OK ==="
