#!/bin/bash
# =====================================================================
# t78 等效验证（2026-10-28 实测可跑通版）
# 关键：-append 会整段替换 DTB 的 /chosen/bootargs，必须补回 vmalloc= 与 mem=
#       否则早期 early_alloc_aligned() 的 __va() 落到未映射线性区 → 串口 0 字节
# 已验证：串口 90 756 字节，内核跑到 `init: init first stage started!`
# 当前崩点：5.44–5.49 s ddrfreqd oops（regulator 缺失，见 DDRIFF_ROOTCAUSE.md）
# =====================================================================
set -uo pipefail

W=${W:-/data/workspace}
Q=${Q:-$W/rk3288/qemu-src/build/qemu-system-arm}
STAGE=${STAGE:-$W/t78_stage}
LOG=${LOG:-$W/logs/t78_verify.log}
TMO=${TMO:-120}

APP="console=ttyS2,115200 vmalloc=496M mem=2048M clk_ignore_unused cpufreq=disabled loglevel=7"

mkdir -p "$(dirname "$LOG")"
echo "=== qemu: $Q ==="
"$Q" -machine help 2>/dev/null | grep -i rk3288 || { echo "FATAL: rk3288 machine missing"; exit 1; }

echo "=== run (${TMO}s) ==="
timeout "$TMO" "$Q" -M rk3288 -smp 1 -m 2048 \
  -kernel "$STAGE/zImage_run13" -initrd "$STAGE/twrp_ramdisk.gz" \
  -append "$APP" -display none -serial "file:$LOG" -monitor none -no-reboot \
  -dtb "$W/p817_run.dtb" >/dev/null 2>&1
rc=$?

echo "rc=$rc bytes=$(wc -c < "$LOG" 2>/dev/null || echo 0) lines=$(wc -l < "$LOG" 2>/dev/null || echo 0)"
echo "--- key hits ---"
for p in "DDR DEBUG: init success" "Freeing initrd" "init first stage started" \
         "First stage mount skipped" "Run /init" "TWRP" "I: LANG" \
         "can't get regulator" "Internal error" "Unable to handle" "Kernel panic"; do
  n=$(grep -ac "$p" "$LOG" 2>/dev/null || true)
  [ "${n:-0}" -gt 0 ] && echo "  HIT  $p ($n)"
done
echo "--- tail 12 ---"; tail -12 "$LOG"
