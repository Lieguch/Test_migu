# qemu-harness — P817 (RK3288W) QEMU 板级模型

**唯一权威文件：`rk3288.c`**（QEMU 10.0.1 `hw/arm/rk3288.c`）
sha256 `3f5b6184c36c0f29a652018c3421c84dba222cc0c8a7d156c9e42fc610d3fa40`（66,853 B / 1,557 行，CRLF）
> 这是**实际参与构建、并且通过了 boot 验证**的那一份（2026-10-30 15:14 二进制 93,880,024 B）。
> 改动前请先 `sha256sum rk3288.c` 对齐 `MANIFEST.sha256`；不一致就说明拿到的是旧版。

## 目录

| 路径 | 内容 |
|---|---|
| `rk3288.c` | 机器模型（UART / catch-all 窗口 / CRU·GRF / PMU / SGRF / MSCH / DDR / SRAM / I2C+ACT8846+SYR827·828+GT911 / GPIO / TSADC / LCDC0 / SARADC / GIC） |
| `tools/build_qemu.sh` | 从本仓库取 `rk3288.c` 打补丁并编译（**注意：会覆盖**目标树的 `hw/arm/rk3288.c`） |
| `tools/qmon*.py` | QMP 采样器（寄存器 / 内存 dump / spin 现场取证），`qmon5.py` 为最新 |
| `tools/fbdump.py` `fbq.py` | ION CMA 帧缓冲 → PNG |
| `tools/make_dtbs.py` `dtb_scan.py` | DTB 变体生成（关 vpu/hevc/iep）/ 地址扫描 |
| `tools/build_ramdisk.py` `cpio_lib.py` `make_initramfs.py` | ramdisk / initramfs 打包 |
| `tools/fix_pmu_pwrdn_st.py` `clean_pmu_comment.py` `fix_line_endings.py` | 2026-10-30 P0 修复的原子补丁脚本（含备份与自证） |
| `docs/HARNESS-FAKE-AUDIT-2026-10-30.md` | **假实现/假桩审计**：逐项行号、证据、修复顺序；含 P0 单变量验证 |
| `evidence/spin_v2.info` | P0 卡点的现场寄存器（PC/R0=PD_HEVC/R2=BIT10） |

## 构建

```sh
# 目标树：QEMU 10.0.1，--target-list=arm-softmmu
sh tools/build_qemu.sh          # 内部会 clone 本仓库并覆盖 hw/arm/rk3288.c
```

## 历史文件（milestone 1/2，保留作证据，不再维护）

`run.sh` `run_rk3288_boot.sh` `qboot.sh` `blocks_before.py` `who_faulted.py`
`resolve_addr.py` `p817.dtb` `evidence-*.log` `evidence/evidence-boot-rk3288-machine.log`

## 判据提醒

这份 harness 是**启动通路模型**，不是硬件模型：
- 能让内核走到某一步 ≠ 该步在真机上正确；
- 0xff000000–0xffffffff 未建模块统一读 0 / 写丢弃 ⇒ **"某驱动 probe 失败"可能只是桩**；
- CRU/GRF 读全 1、TSADC/SARADC 常量、PMU 回声握手 ⇒ 时钟/温度/ADC/电源域**不可测**。

详见 `docs/HARNESS-FAKE-AUDIT-2026-10-30.md` §6「能证明 / 不能证明」。
