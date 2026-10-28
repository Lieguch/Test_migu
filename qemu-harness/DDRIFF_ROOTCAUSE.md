# t78 ddr_init NULL-pointer deref — 根因分析与补丁

## 现象（t78 boot.log）

| 行 | 内容 |
|---|---|
| 150-153 | `DDR DEBUG: addr=0xd18000 ...`（ddr_get_datatraing_addr 已执行） |
| 154 | `Unable to handle kernel NULL pointer dereference at virtual address 00000008` |
| 161 | `PC is at ddr_init.constprop.15+0x508/0x7dc` |
| 163 | `lr : [<00000000>]` |
| 167 | `r1 : 00000000` `r4 : 00000008` |
| 221-222 | `ddr_init+0x508` ← `rk3288_ddr_init+0x40` ← `do_one_initcall` |

## 根因

`ddr_init+0x508` 对应 `ddr_move_to_Access_state()` 中：

```c
register pDDR_REG_T pDDR_Reg = DATA(ddr_ch[ch]).pDDR_Reg;
...
value = pDDR_Reg->STAT.b.ctl_stat;   /* 读 pDDR_Reg + 0x8 */
```

`pDDR_Reg = pDDR_REG(0) = RK_DDR_VIRT`（内核 `arch/arm/mach-rockchip/ddr_rk32.c:781`）。

`RK_DDR_VIRT = RK_IO_ADDRESS(0x000d0000)`（`include/linux/rockchip/iomap.h:22`）。

在 QEMU 环境下 `RK_DDR_VIRT` 解析为 **0**（`RK_IO_ADDRESS(0x000d0000)` 无有效映射），导致 `pDDR_Reg = 0`，读 `0+0x8` → NULL-pointer deref → panic。

QEMU `rk3288.c` 的 DDR model 注册在 `RK3288_DDR_BASE = 0xff610000`（第 1036 行），而内核期望读 `RK_DDR_VIRT`（物理 `0x000d0000` 附近），两者地址不匹配，且 `0x000d0000` 落在 DRAM 区（读回 0），使 `pDDR_Reg` 指针为 0。

对比 t71（原厂内核 xierong 2018）可跑通 TWRP 主程序，t78（run13/twrp_zImage，runner 2026）在 `ddr_init` 即 panic —— 说明是**内核版本差异导致的 `RK_DDR_VIRT` 映射问题**，QEMU DDR model 未覆盖内核实际访问的地址。

## 补丁

### 补丁 1：QEMU `rk3288.c` —— 让 DDR model 在 `RK_DDR_VIRT` 的物理地址处也可读

在 `rk3288_init()` 中，除现有 `0xff610000` 外，追加在 `0x000d0000`（RK_DDR_VIRT 对应的物理地址）处注册同一套 DDR ops。这样内核读 `RK_DDR_VIRT` 可命中 DDR model，返回合理的 STAT/SCTL/PPCFG 值，避免 `pDDR_Reg` 为 0。

位置：`rk3288_init()` 内，`rk3288_add_io(sysmem, RK3288_DDR_BASE, ...)` 之后（~第 1036 行）。

```c
    /* RK_DDR_VIRT = RK_IO_ADDRESS(0x000d0000) -> 物理 0x000d0000。
     * 内核 ddr_init() 从 RK_DDR_VIRT 读 pDDR_Reg/pPHY_Reg，QEMU 若只在
     * 0xff610000 建 model，RK_DDR_VIRT 读回 0 -> pDDR_Reg 为 NULL ->
     * ddr_init+0x508 读 [0, #8] panic。在此处追加 model，覆盖内核访问地址。 */
    rk3288_add_io(sysmem, 0x000d0000ULL, RK3288_DDR_SIZE, &rk3288_ddr_ops, "rk3288-ddr-virt");
```

### 补丁 2：内核 `ddr_rk32.c` —— `ddr_init` 容错，pDDR_REG 为 0 时回退

在 `ddr_init()` 中，`p_ddr_ch[ch]->pDDR_Reg = pDDR_REG(ch);` 之后，若 `pDDR_REG(ch)` 为 0，回退到 QEMU DDR model 的物理地址 `0xff610000`。作为纵向防御，避免同类映射问题再次导致 panic。

位置：`arch/arm/mach-rockchip/ddr_rk32.c` `ddr_init()` 函数内（~第 4345 行）。

```c
        p_ddr_ch[ch]->pDDR_Reg = pDDR_REG(ch);
        p_ddr_ch[ch]->pPHY_Reg = pPHY_REG(ch);
        p_ddr_ch[ch]->pMSCH_Reg = pMSCH_REG(ch);

        /* QEMU 环境下 RK_DDR_VIRT 可能为 0，回退到 QEMU DDR model 地址 */
        if (!p_ddr_ch[ch]->pDDR_Reg) {
            p_ddr_ch[ch]->pDDR_Reg = (pDDR_REG_T)0xff610000ULL;
            p_ddr_ch[ch]->pPHY_Reg = (pDDRPHY_REG_T)(0xff610000ULL + RK3288_DDR_PCTL_SIZE);
            p_ddr_ch[ch]->pMSCH_Reg = (pMSCH_REG)0xffac0000ULL;
        }
```

## 验证准则（环境恢复后）

1. 重建 CNB 工作空间：`cnb workspace start-workspace --repo lieguch/rkpad --branch main`
2. 重新编译 QEMU（`build_qemu.sh` 修改 meson.build 让 rk3288.c 无条件编入）
3. 跑 t78 等效组合：`run13/zImage` + `twrp_ramdisk.gz`（真 TWRP ramdisk）
4. 预期：`ddr_init` 不再 panic，启动进入 initramfs，出现 `I: LANG: zh_CN` 等 TWRP 主程序日志，进而触发 Route B 的 5.2s ddrfreq DVFS panic（下一阶段攻克目标）。

## 当前状态汇总

- QEMU rk3288 机器：已注册并可启动（t74/t77/t78 均能过早期 boot）
- TWRP ramdisk：可解析并加载（twrp_new.img → twrp_ramdisk.gz）
- 阻塞点：`ddr_init` 在 `RK_DDR_VIRT` 映射为 0 时 panic，TWRP 主程序尚未进入
- 下一步：应用补丁 1 + 补丁 2，重建环境后验证
---

## 2026-10-28 实测（InstaBox 云机，QEMU v10.0.1 新构建）— 补丁 1 的致命副作用

### 环境
- InstaBox 机器 `m_agqychrdvyurnyynpkspkaam6q`（4vCPU/8GiB，Debian 13，gcc 14.2.0）
- QEMU v10.0.1 + `rk3288.c`（默认 `loader_start`），`arm-softmmu` 单目标，构建通过
- 输入：`run13/zImage`(6 155 760 B) + `twrp_ramdisk.gz`(14 891 918 B, gzip) + `p817-run.dtb`

### 结论 1：补丁 1（在 0x000d0000 注册 DDR model）会破坏 zImage 自身
| 观测 | 证据 |
|---|---|
| 串口 0 字节，QEMU 跑满超时 | `logs/t78*.log` bytes=0 |
| 死点 | `R15=R14=0xd13af8`，该地址指令 `feffffea` = `b .`（自跳） |
| 死点前 3 次带字符串调用 | `ldr r0,=..; add r0,pc,r0; bl 0xd13ac0` ×3 |
| 字符串区 | 0xd16585 `LZO`，0xd16595 ` -- System halted`，0xd165c0 `Uncompressing Linux` |
| DDR 读日志 | 4096 个不同偏移（正好 0x4000 窗口全部字）各被读一次 |

⇒ 运行在 `0xd13xxx` 的是 **zImage 自解压器**（不是内核）。默认 `loader_start` 把它装在
`0x00008000`，自解压映像实测覆盖到 `0x00d165xx`（约 13 MB），**正好包含 `0x000d0000`**；
补丁 1 在该地址挖掉 16 KiB ⇒ 自解压器自身代码/数据被替换 ⇒ 走错误分支 → `b .`。

### 结论 2：抬高装载地址不可行
| 变体 | 结果 |
|---|---|
| `loader_start = 0x02080000`（RK 真实装载地址） | 死在 `0xffff000c`（高向量 prefetch abort 自循环），PSR=svc32 |
| `loader_start = 0x00100000` | 串口仍 0 字节 |

⇒ 该 zImage 内置 TEXTADDR 与实际装载地址不匹配时无法自恢复。

### 结论 3：本环境下 t78 基线也复现不出来（关键）
禁用 DDR-virt 区域（回到补丁 1 之前）后，用 `-d int` 抓到**首次异常**：

```
Exception return from AArch32 hyp to svc PC 0x20084 / 0x2127c / 0xd143dc   (HVC ×3)
AArch32 mode switch svc→irq→abt→und→svc PC 0xc0010400   (内核向量已就位)
Taking exception 4 [Data Abort] EL1→EL1  DFSR 0x805  DFAR 0xee7ff000
Taking exception 3 [Prefetch Abort]     IFSR 0x5   IFAR 0xffff0010  → 无限循环
```

- 首次故障是 **数据访问 VA 0xee7ff000**（section translation fault），发生在 console 注册之前；
- 高向量页 0xffff0000 尚未映射 ⇒ 向量自身 prefetch abort → 死循环；
- UART THR 写入计数 = **0**（插桩 `[uartN] THR xx` 实测），⇒ 内核从未 printk；
- 对照：原厂 stock 内核（`recovery_p6.img`，sha256 `e38ae4c4…`，与 twrp_new 内核同一个）
  同样 0 字节；`-m 512/768/896/1024`、裸 DTB、无 DTB、`-smp 4`、`earlyprintk` 全部 0 字节。

⇒ 文档里 t78 的「6.08 s 在 ddr_init+0x508 panic」在本环境**不可复现**：崩点比它早得多，
且与补丁 1 无关（禁用后依旧）。CNB 旧环境与本次新构建之间存在尚未定位的差异。

### 因此的下一步（按优先级）
1. **放弃补丁 1，改走内核侧补丁 2**（`ddr_rk32.c` 里 `pDDR_REG(ch)==0` 时回退 `0xff610000`）——
   不占任何物理地址，不会与 zImage 映像冲突；代价是要拿到内核源码树重建 zImage。
2. 先解决「内核早期数据 abort 0xee7ff000」这个更前置的阻塞：它挡在所有 TWRP 进展之前。
   候选方向：内核 lowmem/VMSPLIT 与 2 GB RAM 的边界、`/memory` 与 DTB 的 `device_type`、
   或该 zImage 期望的 `TEXTADDR` 与 QEMU 装载点不一致。
3. 若要继续用 QEMU 侧方案，唯一安全区间是 **≥ 0x00100000 且避开 zImage 映像与 TEXTADDR** 的地址，
   并需先用「首次异常」仪器验证内核能到 console。

### 复现命令（机器上 `/data/workspace`）
```bash
# 构建（一次）
bash /data/workspace/build_qemu.sh
# 运行
./rk3288/qemu-src/build/qemu-system-arm -M rk3288 -smp 1 -m 2048 \
  -kernel t78_stage/zImage_run13 -initrd t78_stage/twrp_ramdisk.gz \
  -append "console=ttyFIQ0 console=ttyS2,115200 loglevel=7 clk_ignore_unused cpufreq=disabled" \
  -display none -serial file:logs/out.log -monitor none -no-reboot -dtb p817_run.dtb
# 首次异常（关键仪器）
... -serial null -d int,guest_errors -D logs/int.log
```

---

## 2026-10-28 二次实测（关键突破）：真因是 bootargs 被 `-append` 覆盖

### 结论 0（最高价值）：加上 `vmalloc=496M mem=2048M` 内核才真正启动
| 组合 | 串口字节 | 结果 |
|---|---|---|
| `console=ttyFIQ0 console=ttyS2,115200 loglevel=7 clk_ignore_unused cpufreq=disabled` | **0** | 早期 data abort（见上节） |
| `console=ttyS2,115200 vmalloc=496M loglevel=7` | **0** | 同上 |
| **`console=ttyS2,115200 vmalloc=496M mem=2048M clk_ignore_unused cpufreq=disabled loglevel=7`** | **90 756** | **内核启动到 userspace** |

DTB 的 `/chosen/bootargs` 原本只有 `vmalloc=496M`；QEMU `-append` 会整段替换它 ⇒ 丢掉 `vmalloc=` 后
早期 `early_alloc_aligned()` 的 `__va(memblock_alloc())` 落到未映射线性区 → `DFAR=0xee7ff000` 死循环。
（符号由 `vmlinux-to-elf` 从内存 dump 恢复，71 336 个符号；`0xc0a27458 = early_alloc_aligned`。）

### 结论 1：TWRP 的 Android init 已经跑起来了（本次首次达成）
```
[5.404] init: init first stage started!
[5.406] init: First stage mount skipped (recovery mode)
[5.410] init: Using Android DT directory /proc/device-tree/firmware/android/
```
`DDR DEBUG: init success` ×2、`Freeing initrd` ×2 均命中 ⇒ 之前 t78 的 `ddr_init` NULL 解引用**不再出现**。

### 结论 2：新崩点 = PMIC/regulator 缺失 → ddrfreqd oops（5.44–5.49 s）
```
[0.585] act8846_i2c_probe,line=898
[0.587] act8846_parse_dt,line=746
[0.588] invalid gpio: -2  ×4 ; WARNING at drivers/gpio/gpiolib.c:126 gpio_to_desc
[0.589] act8846 0-005a: Failed to request gpio -2 with ret:-22
[4.35 ] DVFS ERR: clk_enable_dvfs: vd(vd_logic) can't get regulator(vdd_logic)!   (×10)
[5.49 ] Unable to handle kernel paging request at virtual address fffffe2b
        PC is at regulator_get_voltage+0x8/0x34
        LR is at rockchip_cpufreq_reboot_limit_freq+0x44/0x68
        ← ddrfreq_work+0x4c/0x368 ← ddrfreq_task+0x40/0x1c8 ← kthread
```
- `fffffe2b` = 把 `ERR_PTR` 当指针解引用（`ldr r0,[r0,#0x30]`，`Code: ... (e5900030)`）。
- act8846 的 `gpios = <0xb3 1 1 0xb2 0xa 0>`：`0xb3`=gpio7@ff7e0000（存在）、`0xb2`=**gpio0@ff750000**
  （pinctrl 日志只建了 gpio1..gpio8/gpio15，**没有 gpio0**，其 reg 含 `mux_bank0@ff730084` 属 PMU 区）
  ⇒ `of_get_named_gpio` 对 gpio0 返回 -2 ⇒ probe 失败 ⇒ 无 `vdd_logic/vdd_arm/vdd_gpu`。

### 已试过的 DTB 变体（都仍 oops，但缩小了范围）
| 变体 | 结果 |
|---|---|
| 删 `act8846@5a/gpios` | probe 仍失败（driver 仍读 "gpios"，取到 -2） |
| `act8846@5a status=disabled` | act8846 行消失，但 oops 仍在 ⇒ 崩溃不依赖该 PMIC 注册成功 |
| `/dvfs status=disabled` | oops 仍在 ⇒ ddrfreqd 线程不受 /dvfs 状态控制 |
| `gpios` 两处都改 `0xb3`(gpio7) | `act8846_pmic_hold=0`、`parse_dt` 通过前半，仍 `Failed to request gpio` |

### 下一步（按性价比）
1. **补 gpio0 模型**（QEMU）：`gpio0@ff750000` 的 bank0 需要 `mux_bank0/pull_bank0/drv_bank0` 三个附加 reg
   可读；让 pinctrl 建出 gpio0 ⇒ act8846 probe 通过 ⇒ 稳压器注册 ⇒ DVFS/ddrfreq 正常。
2. 或让 act8846 完全跳过 gpio（改 `gpios` 为合法 gpio7 两个 pin + 补 `pull/drv` 读回），再验 `vdd_logic` 是否出现。
3. 内核侧兜底（需源码重建）：`rockchip_cpufreq_reboot_limit_freq()` 里对 `IS_ERR(regulator)` 直接返回。
```
