#!/bin/bash
# =====================================================================
# 在 QEMU(rk3288) 里跑 TWRP 主程序（2026-10-28 实测通过）
#
# 实测结果（logs/m6.log，123 681 B）：
#   Starting TWRP 3.1.1-0-c75c8a2e on ...
#   I:LANG: zh_CN
#   Starting the UI...
#   Using fbdev graphics.   framebuffer: 3 (1920 x 1200)   RGB_565
#   I:Loading package: splash (/twres/splash.xml)
#   I:Scaling theme width 1.777778x and height 0.625000x
#   Updating partition details... / Failed to mount '/data' ...
#
# 三个必须项（缺一就看不到任何输出或直接崩）：
#   1) -append 必须带 vmalloc=496M mem=2048M（否则 early_alloc_aligned 踩未映射区）
#   2) DTB 必须关掉 DDR 变频（clk_ddr dvfs disabled，否则 5.4 s ddrfreqd oops）
#   3) ramdisk 去掉 /sepolicy + androidboot.selinux=disabled
#      （该镜像 sepolicy v26 可加载，但 init 的 setexeccon('u:r:recovery:s0') 会 EINVAL）
#
# 注意：TWRP 的输出默认只写 /tmp/recovery.log，控制台看不到。
#       想直接看，用本脚本的 ramdisk（init.recovery.service.rc 里带 console）。
# =====================================================================
set -uo pipefail

W=${W:-/data/workspace}
Q=${Q:-$W/rk3288/qemu-src/build/qemu-system-arm}
IMG=${IMG:-$W/t78_stage/twrp287_idfix_recovery.img}   # ANDROID! 镜像（TWRP 3.1.1）
RD=${RD:-$W/t78_stage/twrp_ok.gz}                     # 去 sepolicy + service 带 console
DTB=${DTB:-$W/d5.dtb}                                 # mk_p817_run_dtb.sh 产物
LOG=${LOG:-$W/logs/twrp_run.log}
TMO=${TMO:-120}

APP="console=ttyS2,115200 vmalloc=496M mem=2048M clk_ignore_unused cpufreq=disabled loglevel=7 androidboot.hardware=rk30board androidboot.selinux=disabled"

# 从镜像里抽 kernel（若没有单独文件）
if [ ! -f "$W/t78_stage/twrp287_zImage" ] && [ -f "$IMG" ]; then
  python3 - "$IMG" "$W/t78_stage" <<'PY'
import struct,sys,os
d=open(sys.argv[1],'rb').read(); i=d.find(b'ANDROID!')
u=lambda o: struct.unpack_from('<I',d,i+o)[0]
ks,rs,page=u(8),u(16),u(36)
koff=i+page; roff=koff+((ks+page-1)//page)*page
open(os.path.join(sys.argv[2],'twrp287_zImage'),'wb').write(d[koff:koff+ks])
open(os.path.join(sys.argv[2],'twrp287_ramdisk.gz'),'wb').write(d[roff:roff+rs])
print("extracted kernel/ramdisk")
PY
fi

mkdir -p "$(dirname "$LOG")"
timeout "$TMO" "$Q" -M rk3288 -smp 1 -m 2048 \
  -kernel "$W/t78_stage/twrp287_zImage" -initrd "$RD" \
  -append "$APP" -display none -serial "file:$LOG" -monitor none -no-reboot \
  -dtb "$DTB" >/dev/null 2>&1
rc=$?

echo "rc=$rc bytes=$(wc -c < "$LOG" 2>/dev/null || echo 0)"
for p in "Starting TWRP" "I:LANG" "Starting the UI" "Using fbdev graphics" \
         "Loading package: splash" "Updating partition details" \
         "Internal error" "Kernel panic" "System halted"; do
  n=$(grep -ac "$p" "$LOG" 2>/dev/null || true)
  [ "${n:-0}" -gt 0 ] && echo "  HIT  $p ($n)"
done
