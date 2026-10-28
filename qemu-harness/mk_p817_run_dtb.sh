#!/bin/bash
# =====================================================================
# 生成 QEMU 用的 p817 DTB（实测配方，2026-10-28）
# 用法: ./mk_p817_run_dtb.sh <src.dtb> <out.dtb>
#
# 四个关键改动，缺一不可：
#  1) /memory            = <0 0x80000000>          —— 与 -m 2048 一致
#  2) /serial@ff690000   status=okay               —— UART2 是控制台
#  3) 视频/多媒体节点 disabled                     —— 避免驱动在缺失模型上死等
#  4) /dvfs/vd_logic/pd_ddr/clk_ddr status=disabled
#     ★ 官方《Rockchip DDR 开发指南》kernel 3.10 章节：关闭 DDR 变频就是把这个
#       最终 clk_ddr_dvfs_table 节点置 disabled。不关 → ddrfreqd 在 5.4 s
#       解引用 ERR_PTR（regulator_get_voltage），整机 halt。
# =====================================================================
set -euo pipefail

SRC=${1:?用法: $0 <src.dtb> <out.dtb>}
OUT=${2:?用法: $0 <src.dtb> <out.dtb>}

cp "$SRC" "$OUT"

fdtput -t s "$OUT" /serial@ff690000 status okay
fdtput -t x "$OUT" /memory reg 0 0x80000000

for n in /vpu_service@ff9a0000 /hevc_service@ff9c0000 /iep@ff900000 /isp@ff910000 /gpu \
         /vpu_mmu /hevc_mmu /isp_mmu /iep_mmu /vopb_mmu /vopl_mmu \
         /hdmi@ff980000 /mipi@ff960000 /mipi@ff964000 /lvds@ff96c000 /edp@ff970000 \
         /rga@ff920000; do
    fdtput -t s "$OUT" "$n" status disabled 2>/dev/null || true
done

# ★ 关键：关闭 DDR 变频（否则 5.4 s ddrfreqd oops）
fdtput -t s "$OUT" /dvfs/vd_logic/pd_ddr/clk_ddr status disabled

echo "== $OUT =="
echo -n "  serial@ff690000: "; fdtget -t s "$OUT" /serial@ff690000 status
echo -n "  memory:          "; fdtget -t x "$OUT" /memory reg
echo -n "  clk_ddr dvfs:    "; fdtget -t s "$OUT" /dvfs/vd_logic/pd_ddr/clk_ddr status
