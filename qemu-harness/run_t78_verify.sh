#!/bin/bash
# =====================================================================
# 验证 t78 等效组合：run13/zImage + twrp_ramdisk.gz
# 需在 Codespaces 中先构建 QEMU（build_qemu_codespace.sh），再运行此脚本
# =====================================================================
set -euo pipefail

cd /workspace

QEMU=./qemu-src/build/qemu-system-arm
ZIMAGE=/workspace/zImage        # 需提前放入工作区：run13/zImage
RAMDISK=/workspace/twrp_ramdisk.gz  # 需提前放入工作区：twrp_ramdisk.gz
DTB=/workspace/p817.dtb         # 需提前放入工作区

echo "=== 验证输入文件 ==="
ls -la "$ZIMAGE" "$RAMDISK" "$DTB" 2>&1 || {
    echo "错误：缺少输入文件，请将 zImage、twrp_ramdisk.gz、p817.dtb 放入 /workspace"
    exit 1
}

echo "=== 启动 QEMU（RK3288 机型）==="
"$QEMU" \
    -M rk3288 \
    -m 256M \
    -kernel "$ZIMAGE" \
    -ramdisk "$RAMDISK" \
    -dtb "$DTB" \
    -append "console=ttyAMA0 androidboot.hardware=rk30board" \
    -serial stdio \
    -no-reboot \
    -d guest_errors \
    -D /workspace/qemu.log

echo "=== QEMU 退出，检查日志 ==="
grep -i "LANG\|ddr_init\|panic\|NULL\|Unable to handle" /workspace/qemu.log || true
