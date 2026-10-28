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

---

## 2026-10-28 三次实测：三条根因逐个解除，**stock recovery 已在 QEMU 跑起来**

### ① bootargs 被 `-append` 覆盖（已修，见上节）
`-append "console=ttyS2,115200 vmalloc=496M mem=2048M clk_ignore_unused cpufreq=disabled loglevel=7"`

### ② DDR 变频导致 `ddrfreqd` oops（已修）
- 现象：`regulator_get_voltage+0x8` 解引用 `ERR_PTR 0xfffffe2b`，调用链
  `rockchip_cpufreq_reboot_limit_freq ← ddrfreq_work ← ddrfreq_task`，@5.44–5.49 s。
- **官方解法**（《Rockchip DDR 开发指南》kernel 3.10 章节）：把 DTS 里最终的
  `clk_ddr_dvfs_table` 节点置 `status="disabled"`。本 DTB 对应路径：
  `/dvfs/vd_logic/pd_ddr/clk_ddr`。
- 实测：`fdtput -t s d5.dtb /dvfs/vd_logic/pd_ddr/clk_ddr status disabled`
  → `logs/d5.log`：**oops=0、ddrfreqd=0、regfail 10→6**。

### ③ sepolicy v30 > 内核上限 28（已定性：这是**artefact 选错**，不是 harness 问题）
```
SELinux:  policydb version 30 does not match my version range 15-28
selinux:  Could not load policy:  Invalid argument
init: Failed to load monolithic SELinux policy: Invalid argument
init: Reboot start, reason: reboot, rebootTarget: bootloader      → System halted
```
- `twrp_new.img` 里的 ramdisk 是 **android-9 的 TWRP 3.3.1**（init 打印
  `init first stage started` / `Skipped setting INIT_AVB_VERSION` 是 8/9 代特征）。
- 换 stock 的 v26 策略后策略能加载，但继续失败：
  `Could not set context for /init: Operation not supported on transport endpoint`
  （rootfs 无 xattr）→ 仍 reboot。
- 去掉 `/sepolicy` 更糟：`Could not open /sepolicy` → `Unable to load SELinux policy` → reboot。
- ⇒ **该 ramdisk 与本内核（3.10 / policy ≤28）根本不配套**，与项目 §9.20 的结论一致：
  应该用 **omni-4.4 / TWRP 2.8.7** 的 ramdisk。

### ④ 里程碑：stock 4.4 内核 + stock ramdisk → recovery 二进制在跑
`logs/stock_ok.log`（75 554 B / 1 079 行，100 s 不崩）：
```
[24.85] init: property 'ro.serialno' doesn't exist ...
# Starting recovery on Thu Jan  1 00:00:24 1970
cmdline=console=ttyS2,115200 vmalloc=496M mem=2048M clk_ignore_unused cpufreq=disabled loglevel=7
bootmode = unknown
recovery filesystem table
  0 /mnt/internal_sd vfat /dev/block/rknand_user 0
  1 /mnt/external_sd vfat /dev/block/mmcblk0p1 0
  ...
 17 /tmp ramdisk ramdisk 0
I/ bootable/recovery/recovery.cpp:1589 SetSdcardRootPath; InternalSD_ROOT: /mnt/internal_sd
W/ roots.cpp:149 ensure_path_mounted; failed to mount /dev/block/rknand_cache at /cache
E:Can't mount /cache/recovery/last_locale
failed to read font: res=-1
```
之后稳定打印 `>>>> pwrsw pin = 0,2`（内核电源键轮询，§9.59-E 已判为内核侧），
**无 oops / 无 panic / 无 reboot**。

### 结论与下一步
- harness 已证明可跑到 userspace recovery；剩余阻塞是 **TWRP 2.8.7(omni-4.4) ramdisk 未就位**。
- 下一步：①取/构建 2.8.7 ramdisk（repo 的 `build_twrp_44.yml` 产物即为此）；
  ②用同一配方 + `d5.dtb` 跑它；③再做 Route A（显示上电：act8846/gpio0 或固定 vdd_logic）。
- 复现：
```bash
Q=./rk3288/qemu-src/build/qemu-system-arm
$Q -M rk3288 -smp 1 -m 2048 -kernel t78_stage/stock_zImage -initrd t78_stage/stock_ramdisk.gz \
  -append "console=ttyS2,115200 vmalloc=496M mem=2048M clk_ignore_unused cpufreq=disabled loglevel=7" \
  -display none -serial file:logs/stock_ok.log -monitor none -no-reboot -dtb d5.dtb
```

---

## 2026-10-28 四次实测：TWRP 2.8.7 ramdisk 进环，卡在 userspace on boot 未触发

### 素材（本地已就位，无需构建/CI）
`D:/output/pad/work/hybrid/twrp287_idfix_recovery.img`（12 877 824 B，与 GitHub Release
`stage2-44-*` 同尺寸）。解出：kernel = **stock 同一个**（sha `e38ae4c4…`），ramdisk 6 061 616 B。
ramdisk 属性实测：`sepolicy` **version 26**（≤28 ✓）、4.4 代 init、`/sbin/recovery` 447 988 B、
`sbin/recovery` 内含 `Starting TWRP %s-%s`。

### 逐项结果
| 变体 | 关键观测 |
|---|---|
| 原 ramdisk + v26 策略 + d5.dtb | `SELinux: Loaded policy from /sepolicy` ✓，但
`init: cannot setexeccon('u:r:recovery:s0'): Invalid argument`；无 `Starting TWRP`；100 s 不崩 |
| 去 sepolicy + `androidboot.selinux=disabled` | setexeccon 消失；仍无 `Starting TWRP`；100 s 不崩 |
| 补 `console`/`class core`、`on boot: start recovery` | 同上，仍无输出 |
| 用 `/sbin/sh -c "/sbin/recovery; echo RECOVERY_RC=$?"` 包一层 | **连 shell 输出都没有** |

⇒ 结论：**`on boot` 触发器根本没走到**（若走到，包一层的 shell 至少会回显）。
早前 stock 4.4 ramdisk 能打印 `# Starting recovery on ...`，说明同一内核 + 同一 harness 下
userspace 通路是通的，差异在 TWRP ramdisk 的 init 启动路径（触发条件/依赖设备节点）。

### 已排除
- 不是 SELinux（去掉策略后仍无输出，且无 setexeccon 报错）
- 不是内核崩（100 s 无 oops/panic；`fb0` 已注册：`graphics fb0: rockchip framebuffer registerd:fb0`）
- 不是缺 `/sbin/recovery`（存在且可执行）
- 不是 kernel/DTB 配置（stock ramdisk 同配方可跑 recovery）

### 下一步（最有信息量）
1. 在 TWRP ramdisk 的 `init.rc` 的 `on early-init` / `on init` / `on boot` 各插一行
   `write /dev/kmsg "MARK <阶段>"`，确认 init 究竟停在哪一步（大概率
   `wait_for_coldboot_done()` 或 `property_service` 初始化）。
2. 对照 stock init.rc：stock 把 `service recovery` 直接写在**主 init.rc**（第 57 行）且
   `on boot` 块简单；TWRP 依赖 `import /init.recovery.service.rc`。若 import 失败/顺序问题，
   可把 service 定义直接搬进主 init.rc 验证。
3. 拿到触发点后再看 TWRP 自身的 minui/fb 依赖（Route A 显示相关）。

---

## 2026-10-28 五次实测 ★ TWRP 主程序在 QEMU 中跑通（3.1.1 / zh_CN / UI 主题加载完成）

### 结论
**TWRP 已经在 QEMU(rk3288) 里跑起来**，`logs/m6.log`（123 681 B）关键行：
```
Starting TWRP 3.1.1-0-c75c8a2e on Thu Jan  1 00:00:23 1970   (pid 112)
I:=> hardware id from cpuinfo: 'Rockchip RK3288 (Flattened Devi'
I:LANG: zh_CN
Starting the UI...
Skipping adf graphics -- not present in build tree
Skipping drm graphics -- not present in build tree
fb0 reports (possibly inaccurate):
  vi.bits_per_pixel = 16   red 11/5  green 5/6  blue 0/5
setting GGL_PIXEL_FORMAT_RGB_565 ; double buffered
framebuffer: 3 (1920 x 1200)
Using fbdev graphics.
I:Loading package: splash (/twres/splash.xml)
I:Scaling theme width 1.777778x and height 0.625000x
I:Loading resources... variables... mouse cursor... pages...
I:Processing '/data' '/boot' '/recovery' '/backup' ...
I:Using automatic handling for /data/media emulated storage device.
I:Backup folder set to '/data/media/TWRP/BACKUPS/0000000000000000'
Updating partition details...
Failed to mount '/data' / '/cache' / '/system' (Invalid argument)   ← 无真实块设备，预期
```

### ★ 之前「看不到输出」的真相（重要纠错）
TWRP 的 stdout **不接控制台**，它只写 `/tmp/recovery.log`。
先前用 `grep "Starting TWRP" 串口日志` 得到 0 命中，被我误判成「init 没触发 / 服务没起」。
真正判定方法：在 ramdisk 里加一个探针服务，逐行 `echo "$line" > /dev/kmsg` 把
`/tmp/recovery.log` 倒出来（`cat > /dev/kmsg` 会因单次写入过大报 EINVAL）。

### 三个必须项（缺任一即失败）
1. `-append` 必须含 `vmalloc=496M mem=2048M`（否则早期 `early_alloc_aligned()` 踩未映射线性区）。
2. DTB 必须关 DDR 变频：`/dvfs/vd_logic/pd_ddr/clk_ddr status=disabled`（否则 5.4 s `ddrfreqd` oops）。
3. ramdisk 去掉 `/sepolicy` + `androidboot.selinux=disabled`
   （v26 策略能加载，但 `init: cannot setexeccon('u:r:recovery:s0')` EINVAL）。

### 素材与事实修正
- 文件名叫 `twrp287_idfix_recovery.img`，但镜像内 TWRP 自报 **3.1.1-0-c75c8a2e**（不是 2.8.7）。
- kernel 与 stock 同一个 sha `e38ae4c4…`（6 791 568 B）；ramdisk 6 061 616 B。
- 脚本：`qemu-harness/run_twrp_qemu.sh`（本配方一键复跑）。

### 下一步
- 显示验证：QEMU 加 `-display vnc=:0` 或 `-device VGA` 截屏，确认 splash/主菜单实际画面。
- 交互验证：给 QEMU 接 evdev/鼠标，验证触摸映射（真实目的是绕开坏电源键）。
- 收尾：把本配方回灌 `HANDOFF.md` 与 build 流程，作为「TWRP 可跑」的验收基线。

### ★ 画面验证（同日）：帧缓冲 dump 出真实 TWRP 界面
`fb0.bmp` / `evidence/twrp_ui_2026-10-28.png`（1920x1200，RGB565→24bpp）内容：
- 顶部状态栏：左 `3.1.1-0`，中 `7:00 PM`
- 标题：**未修改的 System 分区**（TWRP logo）
- 正文：**是否保持系统分区为只读？** + 中文说明段
- 复选框：**下次启动时不再显示此界面**
- 按钮：**保持只读** / **选择语言**
- 底部滑块：**滑动按钮允许修改**
- 底部：Android 三键导航（返回/主页/最近）

**取证方法**（QEMU 无显示设备时唯一可行路径）：
```bash
# 1) 后台跑 TWRP，开 QMP
$Q ... -display none -qmp unix:/data/workspace/mon.sock,server,nowait &
sleep 45
# 2) 帧缓冲在 ION CMA 起始处：base=0x40000000，双缓冲 2×1920×1200×2 = 0x8CA000
pmemsave 0x40000000 0x008CA000 "/data/workspace/fb.raw"
# 3) RGB565 → BMP/PNG（脚本 /data/workspace/fbdump.py，仓库同源）
```
> ION CMA 基址来自内核日志：`ion heap(cma): base(40000000) size(28000000)`；
> 分辨率来自 TWRP 日志：`framebuffer: 3 (1920 x 1200)`、`vi.bits_per_pixel = 16`。

---

## 2026-10-28 六次实测：触摸屏建模（Goodix GTP）—— 设备已注册，事件注入待做

### 前提（用户明确）
**设备没有任何输入设备，只有触摸屏**。所以 harness 必须建模触摸 IC，否则 TWRP UI 无法被驱动。

### 硬件事实（DTB 实测）
```
goodix_ts@5d { compatible = "goodix,gt9xx"; reg = <0x5d>;
               goodix,rst-gpio  = <&gpio7 5 GPIO_ACTIVE_LOW>;
               goodix,irq-gpio  = <&gpio7 6 IRQ_TYPE_LEVEL_LOW>;
               goodix,cfg-group0 = [43 b0 04 ... b3 01];   /* 186 字节 */ };
```

### 已做：QEMU 侧新增 GTP I2C 从设备（16 位寄存器寻址）
- `rk3288.c`：新增 `GTP_ADDR 0x5d` + `gtp_cfg[192]` 寄存器文件 + `gtp_read_reg()`；
  `rk3288_i2c_do_tx/do_rx` 增加 GTP 分支（tx[1..2]=16 位寄存器号，数据写入 0x8047 起的配置区）；
  提供 product id `911`、firmware、分辨率 0x04B0=1200、`0x814E` 状态=0。
- **效果**（`logs/gtp.log`）：
```
<<-GTP-INFO->> IC Version:    _0000
<<-GTP-ERROR->> Firmware error, no config sent!
<<-GTP-ERROR->> GTP init panel failed.
input: goodix-ts as /devices/virtual/input/input1      ← ★ 触摸 input 设备已注册
<<-GTP-INFO->> GTP works in interrupt mode.
```
（对比：加模型前是 `I2C Read: 0x8047 failed errcode -11` ×3 然后放弃，根本没有 input 设备。）

### 仍未完成（按依赖顺序）
1. **配置交换**：驱动报 `Firmware error, no config sent!` ⇒ 需要正确响应 0x8047 配置区的
   "版本 + 长度" 语义（或让驱动把 DT 的 186 字节 cfg 写下来后回读一致）。
2. **gpio7 EINT**：`goodix,irq-gpio = <&gpio7 6 LEVEL_LOW>`；DT `gpio7 interrupts = <0 0x58 4>`
   ⇒ 需要在 QEMU 里实现 gpio7 bank 的 INT_STATUS/INT_EN 寄存器并连到 GIC SPI 0x58，
   触摸时拉低该脚。当前 pinctrl 只读 catch-all（全 0），无法产生中断。
3. **事件注入**：IRQ 打通后，在 0x814E 置 buffer-ready 并在 0x8150.. 填坐标，
   由驱动上报 `input1` 的 `ABS_MT_POSITION_X/Y`，即可在 QEMU 里"点"TWRP。
4. TWRP 侧确认：当前 `/tmp/recovery.log` 未见触摸设备相关行（minui 不打印），
   需在第 3 步后用 `input1` 事件验证 UI 是否响应。

### ★ 触摸建模第二步（同日）：GTP 初始化全通 —— 修掉 3 个真实缺陷

| # | 缺陷 | 证据 | 修法 |
|---|---|---|---|
| 1 | I2C TX/RX FIFO 窗口只有 `0x100-0x140`（16 字 = 64 B） | 240 B 配置写被截断 | 窗口扩到 `0x100-0x200` / `0x200-0x300`，`txw/rxw[64]`，`n<=256` |
| 2 | GTP 寄存器号来自 **MRXRADDR**，不是 TX | 打点：`RX addr=5d mode=1 mrxraddr=0300e441`（=0x41E4） | `base16 = ((mrxraddr & 0xff) << 8) \| ((mrxraddr>>8) & 0xff)` |
| 3 | 长写被控制器**分块**，后续块不含地址字节 | `I2C Write: 0x8047, 240 bytes failed -11` ×5 | 增加 `cur_addr` 状态：首字节等于 `0xb4/0xba` 才当地址，否则视为续传数据 |

另补两个驱动硬性要求的寄存器：
- `0x41E4` 必须 = `0xBE`（否则 `Firmware error, no config sent!` 直接 return -1）
- `0x814A` = sensor_id，必须 `< 6`

**结果**（`logs/gtp9.log`）：
```
<<-GTP-INFO->> IC Version: 911_0402
<<-GTP-INFO->> Sensor_ID: 0
<<-GTP-INFO->> Config group0 used,length: 186
<<-GTP-INFO->> Driver send config.
<<-GTP-INFO->> X_MAX: 1200, Y_MAX: 1920, TRIGGER: 0x01
input: goodix-ts as /devices/virtual/input/input1
<<-GTP-INFO->> GTP works in interrupt mode.
```
注意：`X_MAX=1200 / Y_MAX=1920` 与屏幕 1920x1200 **是转置的**，注入坐标时要交换。

### 还差最后一步：gpio7 EINT
驱动已进入 interrupt 模式，但 `goodix,irq-gpio = <&gpio7 6 LEVEL_LOW>` 要真实拉低才能触发。
需要在 QEMU 实现 gpio7 bank（`0xff7e0000`）的 `INT_EN(0x30)/INT_MASK(0x34)/INT_STATUS(0x40)/EXT_PORT(0x50)`
并连到 GIC SPI `0x58`；随后在 `0x814E` 置 buffer-ready、`0x8150..` 填坐标即可产生真实触摸事件。

### ★ 触摸建模第三步（同日）：gpio7 EINT 打通，中断已能送达驱动

**实现**（`rk3288.c`）：
- gpio7 bank 模型（`0xff7e0000`，0x100）：`DR 0x00 / DDR 0x08 / INT_EN 0x30 / INT_MASK 0x34 /
  INT_STATUS 0x40 / EXT_PORT 0x50`，写 1 清中断；`EXT_PORT` 在触摸时把 pin6 拉低（LEVEL_LOW）。
- 中断线：`gpio7_irq_line = pic[0x58]`（DT `gpio7 interrupts = <0 0x58 4>` → GIC SPI 0x58）。
- 注入通道：环境变量 `RK3288_TOUCH_FIFO` 指向 FIFO，命令 `tap X Y` / `down X Y` / `up`；
  tap 150 ms 后自动抬起（QEMUTimer）。
- GTP 数据：`0x814E` 返回 `0x81`（ready + 1 点）；`0x8150..0x8155` 返回 id/x/y/size；
  驱动写 `0x814E=0` 时清状态。

**踩到的坑（已修）**：`INT_MASK` 初值我写成 `0xffffffff`（全屏蔽），而驱动只写 `INT_EN`
不会解 `INT_MASK` ⇒ 中断永远不触发。改为复位全 0（1=masked 语义）。

**实测结果**（`logs/g8_err.log`）：
- `INT_EN` 被驱动写成 `0x40 / 0x80 / 0xc0`（pin6 使能）✓
- 注入 `tap 1010 300` 后，出现 **1 次 `0x814E` 读**（`mrxraddr=03004e81`）——此前为 0 次 ✓
- 但**没有**后续 `0x8150` 坐标读 ⇒ 驱动读完状态位后未取点。

**下一步**：查驱动为何不读 `0x8150`。候选：
① `gtp_i2c_read_dbl_check` 需要连读两次一致，我们只被读 1 次（可能第二次读被判定失败）；
② 驱动读的是 `0x8150` 起 `1+8*count` 字节，而我们的 `0x8155 size` 或 count 语义不符；
③ 需要在中断后保持 `EXT_PORT` 低电平直到驱动写 `0x814E=0`（我们现在只在 tap 的 150 ms 内保持）。

#### 对照实验（决定性）：中断确实送达
| 场景 | `0x814E` 读次数 | 说明 |
|---|---|---|
| **不注入**（`logs/noinj_err.log`） | **0** | 基线：驱动不会自己读状态 |
| **注入 `tap 1010 300`**（`logs/g8_err.log`） | **1** | 中断送达 → 驱动读 buffer status ✓ |

⇒ gpio7 EINT → GIC SPI 0x58 的连线**已生效**；剩余问题只在"读到 ready 之后为何不取坐标"。

### ★ 触摸建模第四步（同日）：确认驱动读取方式与设备能力

**关键实测（修正了我上一轮的判断）**
- 驱动不是"读状态再读坐标"，而是**一次读 10 字节**：
  `[i2c] RX addr=5d n=10 mode=1 mrxraddr=03004e81`（从 `0x814E` 起 10 字节）
  ⇒ 状态 + 点数据在同一传输里，我们的寄存器布局（0x8150 id / 0x8151-52 x / 0x8153-54 y / 0x8155 size）**是对的**。
- 之后紧跟 `[i2c] TX addr=5d n=4 b0=ba`（驱动写 `0x814E=0` 清 buffer）⇒ 一轮完整触摸握手走完了。

**设备能力（`/proc/bus/input/devices`，`logs/dev.log`）**
```
N: Name="goodix-ts"
H: Handlers=event1 cpufreq
B: EV=b            (EV_SYN|EV_KEY|EV_ABS)
B: ABS=2650000 0
```
⇒ 触摸设备已注册为 `event1`，具备 ABS 能力。

**代码改动**
- tap 不再 150 ms 自动抬起：**保持按下直到驱动写 `0x814E=0`**（2 s 兜底），因为驱动 workqueue 可能晚到；
- 坐标**锁存**（`gtp_coord_valid`），释放后仍可读，避免驱动取点时已被清空。

**仍未闭环**
注入 `tap 187 1616`（按 `screen_x=gtp_x*1.6 / screen_y=gtp_y*0.625` 换算，瞄准「保持只读」）后，
帧缓冲前后仍 `SAME`。下一步要判断"驱动是否真的把事件写进了 event1"：
- 试过在 ramdisk 里 `timeout 8 cat /dev/input/event1 > /tmp/ev.bin` 再报字节数，
  但脚本里 `cat` 立即失败（`EV_BYTES=` 为空，20 ms 就返回）⇒ **这是探针工具问题，不能当成"无事件"的证据**。
- 改进方向：用 `dd if=/dev/input/event1 bs=16 count=N` + 显式 stderr 重定向，先确认 `ls /dev/input/` 可见，
  再判断事件流；或直接在 TWRP 侧开 `TW_DEBUG_INPUT`（若有）看 minui 是否收到 EV_ABS。

### ★ 触摸建模第五步（同日）：纠正两个误判 + 定位真正剩余点

**误判 1 纠正：`/dev/input/` 节点是存在的**
```
$ ls -l /dev/input
crw-rw---- root input 13, 64 event0
crw-rw---- root input 13, 65 event1     ← goodix-ts
crw-rw---- root input 13, 66 event2
```
（上一轮"`ls` 无输出"是我探针写法问题：`ls | while read` 在某些 busybox 下不产出，不是节点缺失。）

**误判 2 纠正：驱动一次读 10 字节**（`RX n=10 mrxraddr=03004e81`），状态与坐标同一传输，
随后写 `0x814E=0` 清 buffer —— 一轮完整握手已走完。所以"驱动没取坐标"的结论作废。

**真正可疑点：ABS 能力位里没有 `ABS_MT_POSITION_X/Y`**
```
N: Name="goodix-ts"
H: Handlers=event1 cpufreq
B: EV=b            (SYN|KEY|ABS)
B: ABS=2650000 0   ← 置位的是 bit16/18/21/22/25
```
`ABS_MT_POSITION_X = 0x35(53)`、`ABS_MT_POSITION_Y = 0x36(54)`、`ABS_MT_SLOT = 0x2f(47)`
都在**高 32 位**（第二组数字），而它是 **0**；`ABS_X=0 / ABS_Y=1` 也没置位。
⇒ 该驱动注册的轴集合不含 TWRP minui 需要的触摸轴 ⇒ TWRP 不会把 event1 当触摸设备。

**下一步（明确）**
1. 用 `vmlinux.elf` 里的符号 + 反汇编确认 gt9xx 的 `input_set_abs_params` 究竟注册了哪些码
   （或直接看驱动源码 `goodix_ts_probe`）。
2. 若驱动只注册了 `ABS_MT_*` 的旧编号，需在 QEMU 侧/驱动侧补齐；若注册正常，
   则问题在 TWRP minui 的设备筛选条件（`TW_` 宏 / `ABS_MT_POSITION_X` 判定）。
3. 验证手段：`dd if=/dev/input/event1 bs=16 count=64` 在注入期间抓原始事件，
   确认 `type/code/value` 序列（此前 dd 探针因脚本问题未取到，节点已确认可读）。

### ★ 触摸建模第六步（同日）：事件终于进了 input 层，但 TWRP 仍不响应

**突破：GT911 点数据从 `0x814F` 开始（不是 `0x8150`）**
| 布局 | 结果 |
|---|---|
| 错位版（id@0x8150） | `ev.bin` = **0 字节**，驱动算出的 y 是垃圾值 |
| 修正版（id@0x814F，x@0x8150-51，y@0x8152-53，size@0x8154） | `ev.bin` = **128 字节**（8 个 input_event）|

**踩坑：在驱动写 buffer 的当口清状态会丢数据**
- 加「驱动写 `0x814E` 时清 active + 立即补中断」→ `ev.bin` 从 128 B 掉到 **0 B**；
- 改成延迟 100 ms 补中断 → 仍 **0 B**；
- 结论：驱动在此刻重入读 `status=0`，丢掉刚取到的点。**已回退**为不提前清，
  由 2 s 定时器统一释放并补中断（等价"长按 2 s 后抬起"），保证按下事件稳定产出。

**当前状态（可核对）**
| 项 | 值 |
|---|---|
| GTP 初始化 | `IC 911_0402 / Sensor_ID 0 / config 186B / X_MAX 1200 Y_MAX 1920` ✓ |
| 中断 | 注入后 `0x814E` 读 1 次（无注入 0 次）✓ |
| input 事件 | `ev.bin` 128 B ✓ |
| TWRP 反应 | 帧缓冲前后 `SAME` ✗ |

**剩余假设（按可能性）**
1. TWRP minui 用 **type B**（`ABS_MT_SLOT`+`ABS_MT_TRACKING_ID`）协议，驱动走的是 type A；
   只有按下没有抬起 ⇒ 不构成点击。
2. 坐标换算仍需校准（`screen_x=gtp_x*1.6`、`screen_y=gtp_y*0.625` 是推断，未经画面验证）。
3. TWRP 打开了另一个 event 节点。

**下一步**：用 `dd` 抓到的 128 B 原始事件解出 `type/code/value` 序列（需在 ramdisk 里补 `od`，
或把 `ev.bin` 通过 kmsg 分段打印），据此判断是 type A/B 还是坐标问题。
