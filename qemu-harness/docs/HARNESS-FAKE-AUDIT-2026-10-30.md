# P817 QEMU harness —— 假实现 / 假代码 / 假桩 代码级审计

审计时间：2026-10-30　审计对象：`hw/arm/rk3288.c`（QEMU 10.0.1，machine `rk3288`）

| 项 | 值 |
|---|---|
| 被审文件（实际参与构建） | `/data/workspace/qemu-src/hw/arm/rk3288.c` |
| 大小 / 行数 | 66,472 B / 1,546 行 |
| sha256 | `8e9f3116a04ec82123955d759a67c219bb591205aa7c93c49a14b72a0f5cb4da` |
| 对应二进制 | `/data/workspace/qemu-src/build/qemu-system-arm`（2026-10-29 08:14，93,879,880 B） |
| 本地留档 | `D:/output/pad/work/cnb_harness/rk3288_active_20261030.c`（同 sha256） |
| 交叉证据 | `boot_v1.log`(43,071 B) / `boot_v2.log`(75,318 B) / `boot_v2dbg.log`(191,729 B) / `spin_v2.info`(10-30 10:53) |

---

## 0. 一句话结论

**这份 harness 不是"硬件模型"，是"让内核走到下一屏的通行证"**：14 个建模块里有 9 个的返回值是
**为了让某个轮询循环退出而挑选的常量或回声**，其中 1 个（PMU `PWRDN_ST`）**已经把当前 boot 卡死**，
另有 3 个（CRU/GRF 全 1、catch-all 全 0、常数量簇）会让"某驱动 probe 失败"这类结论**系统性地不可信**。
代码注释本身很诚实（多数写明"make the wait complete"），但**没有任何一处把"这是假的"写进判据**。

分级计数：**S0 阻塞 1 项 · S1 系统性假值 3 类 · S2 臆造/魔法/死代码 6 项 · 治理缺陷 3 项**。

---

## 1. S0 —— 假模型直接造成当前 boot 阻塞（已定位到寄存器级）

### 1.1 事实链

| 环节 | 证据 |
|---|---|
| 现象 | `boot_v1.log` 停在 **0.637 s**（`checking hw id 0` 之后）；`boot_v2.log` 停在 **3.258 s**（`calling clk_disable_unused` 之后）。两者尾部**同一条 PMU 序列**：`+0x10 → +0x14 → +0x08`，然后 timeout |
| 卡点寄存器 | `spin_v2.info`：PC 两次采样恒定 `0xc001db78`，`R0=9` `R1=0` `R2=0x400` `R12=0xfed20fff` |
| 反汇编（dump base `0xc001da78`，PC 在 +0x100） | `ldr r3,[ip,#-4083]` → `[0xfed2000c]`；`and r3,r3,r2`；`cmp r3,r1`；`beq 0x100` ⇒ **轮询 `(PWRDN_ST & 0x400) == 0` 永不成立** |
| 地址解码 | `RK_IO_ADDRESS(x)=0xFED00000+x`（`include/linux/rockchip/iomap.h:8`），PMU=`+0x00020000` ⇒ `0xfed20000`；`+0x0c` = `RK3288_PMU_PWRDN_ST`（`pmu.h:31`） |
| 参数解码 | `R0=9` = `PD_HEVC`（`enum pmu_power_domain` 第 9 项）；`R1=0` = `on=false`（断电）；`R2=0x400` = `BIT(10)` = `pmu_st_map[PD_HEVC]`（`rk3288.c:184`） |
| 内核写法 | `rk3288_do_pmu_set_power_domain()`：**写 `PWRDN_CON` 的 `pmu_pd_map[PD_HEVC]=14` 位，轮询 `PWRDN_ST` 的 `pmu_st_map[PD_HEVC]=10` 位**（`arch/arm/mach-rockchip/rk3288.c:234-262`） |
| 模型写法 | `case 0x0c: v = rk3288_pmu_pwrdn_con;`（本文件 **1092 行**）—— **ST 逐位回显 CON** |

### 1.2 根因（一句话）

**`PWRDN_CON` 与 `PWRDN_ST` 的位号并非一一对应**：除 HEVC 外所有域两者同位
（VIO 7/7、VIDEO 8/8、GPU 9/9、SCU 11/11、CPU0-3、BUS 5、PERI 6），
**只有 HEVC 是 CON bit14 → ST bit10**。回显模型写 bit14，ST 的 bit10 永远为 0 ⇒ 断电等待死循环。

模型注释自称"Measured 2026-10-22 (t65)：写 `PWRDN_CON=0x80` 轮询同一位" ——
**那条实测只在 PD_VIO 上做过，恰好是两表同位的域**，于是把"同位"当成了通例。
这是**用单点样本外推全表**，属于"假绿"的典型形态。

### 1.3 修复（P0，待执行）

```c
case 0x0c: {   /* PWRDN_ST: 逐域把 CON 位映射到 ST 位（HEVC: 14→10，其余同位） */
    uint32_t con = rk3288_pmu_pwrdn_con;
    uint32_t st  = con & ~(1u << 10);
    if (con & (1u << 14)) st |= (1u << 10);
    v = st;
    break;
}
```
连带修正：`rk3288_pmu_power_domain_is_on()` 读的也是 ST bit10，回显模型下它**恒为"上电"**，
所以 `set_power_domain(PD_HEVC, true)` 永远走 `is_on==on → goto out`（断电请求也因此从未被 CON 记录）。
修 ST 映射后两个方向同时自洽。

---

## 2. S1 —— 系统性假值（会让"驱动失败/驱动正常"这类结论失真）

| # | 位置 | 做法 | 为什么是假 | 后果 |
|---|---|---|---|---|
| **A** | 269-302、1316-1317 | **CRU 4 KiB + GRF 4 KiB 全部读 `0xFFFFFFFF`**，写丢弃 | 本意只想让 `pll_wait_lock()` 的锁定位=1；实际把**时钟门控状态、复位状态、pinctrl mux/pull/drv、所有 GRF 状态位**一起伪造成"全 1" | 任何"读回判断"的驱动都拿到假状态：`clk_disable_unused`（当前卡点所在）逐门判断、`rockchip_set_mux:warning ignore bank num 15`、复位轮询……**"时钟/引脚正常"无法由本 harness 证明** |
| **B** | 223-255 | 0xff000000–0xffffffff 整窗 catch-all：读 0、写丢弃 | 覆盖了 VPU/HEVC/RGA/ISP/GPU/VOP/eDP/HDMI/eMMC/SDIO/USB/crypto/efuse/pinctrl 等**全部未建模块** | `boot_v1` 里 `checking hw id 0` 的 **0 就是这个桩返回的**；"某驱动 probe 失败"极可能只是桩，不是内核/硬件事实。**这是本项目最大的错误结论来源** |
| **C** | 378-380、932、1031、1193-1216 | 常数量簇：`PMU_SYS2=0x3AA01AA0`、`stride=13`、`ddrconf=3`、`TSADC DATA1=3728`（0 ℃）、`SARADC DATA=0x3ff`、DDR PHY（PGSR/DCR/DXGSR/ZQ0SR） | 前 3 个有真机 `last_kmsg` 打印值做推导（**可接受**，但已冻结）；后 3 个是**为了让某循环退出而选的值**（TSADC 注释原文："keeps dvfs_temp_limit_work_func inside its debounce"） | **温度/ADC/DDR 训练三条路径永不产生变化** ⇒ 热保护、DVFS 温度限制、耳机检测、DDR 训练质量**均不可测**；任何"TWRP 里温度/电量正常"的结论都是假的 |

---

## 3. S2 —— 臆造设备 / 魔法常量 / 死代码

| # | 位置 | 问题 | 判定 |
|---|---|---|---|
| 1 | 1418-1427 | **gpio0 / gpio8 / gpio15 三个 bank 全部复用 `rk3288_gpio7_ops`**，且状态是**全局变量**（`gpio7_dr/ddr/int_*`） | **跨 bank 串台**：触摸 IRQ 的 `INT_STATUS bit6` 会同时出现在 gpio0 上；写 gpio0 的 DR 等于写 gpio7。**"act8846 需要 gpio0"因此只是"能 probe"，不代表 gpio0 行为对** |
| 2 | 1426-1427 | `gpio15 @ 0xff7f2000` | **RK3288 只有 GPIO0–8**（`iomap.h:66-74`、`p817.dts:39-130`）。**这是臆造设备**，无任何 DTB/TRM 依据 |
| 3 | 610、630、632 | GTP 魔法常量：`gtp_cfg[0]=0x43`（config version）、`0x41E4=0xBE`（固件校验）、`0x814A=0`（sensor_id） | 三个值都是**为通过驱动校验而挑的**（注释自认"驱动要求 ==0xBE / <6"），**不是真机 GT911 dump**。⇒ "触摸驱动 probe 成功"= 校验被绕开，不等于触摸 IC 行为对 |
| 4 | 595-605 | SYR827/828 复位：**256 个寄存器全填 `0x40`**，仅 `0x00=0x20` | **纯猜**（无 datasheet 依据）。§9.74 记录 ID 读仍 `-110`，说明这个桩**连"让 probe 过"都没做到** |
| 5 | 978-1001 | LCDC0 "帧"模型：`INTR_CTRL0 bit2` 每 **256 次读**翻转一次 | **时间无关的假帧**（无像素时钟、无 vblank、无分辨率推导，256 无出处）。只能让 `rk_fb_poll_wait_frame_complete` 退出，**不能验证任何显示/时序**；LCDC 无 framebuffer、无扫描输出 |
| 6 | 763-766、1322 vs 1431 | `rk3288_i2c_do_tx` 尾部 `for (i=2;...)` **不可达**（前面各分支全部 return）；**PMU 在 1322 与 1431 注册两次**（同址同 ops） | **死代码 + 重复注册**。重复注册当前无害（后者覆盖前者、ops 相同），但属"两份真相"，改动时必踩 |

另有 3 处**注释与代码相反**（会误导后续会话）：

| 位置 | 注释说 | 代码实际 |
|---|---|---|
| 1286-1292 | "按真机映射：DRAM 基址 0x60000000" | `memory_region_add_subregion(sysmem, 0, machine->ram)` —— **仍在 0**，注释末句"回退"与正文自相矛盾 |
| 453-458 | GTP"当前仅实现静态应答" | 已实现点数据/中断/注入 FIFO（注释过期） |
| 860-870 | STOPIPD 两段互相否定的历史注释并存 | 实际行为以 t72 为准，但读者无法判断哪条有效 |

---

## 4. 治理缺陷（比代码缺陷更危险）

| # | 事实 | 风险 |
|---|---|---|
| **G1** | **三份分叉的 `rk3288.c`**：<br>① 实际构建 `/data/workspace/qemu-src/...` 66,472 B（本次审计对象）<br>② `/data/workspace/rk3288/qemu-src/...` 66,457 B（差 2 处：变量改名 + `RK3288_PMU_SIZE`）<br>③ GitHub `Lieguch/Test_migu` `qemu-harness/rk3288.c` **49,221 B（落后 17 KB）** | **`build_qemu.sh` 会把 ③ 拷进 ①** ⇒ 照文档跑一次构建，**syr82x / GTP 触摸 / gpio0-8-15 / PMU 修正全部消失**，回到 10-22 状态。这是"构建脚本产出的不是你以为的那份代码" |
| **G2** | 10-28 之后的全部工作（syr82x、GTP、gpio15、boot_v1/v2 实验）**只存在于云端单机未跟踪文件**；Test_migu `main` 仍停在 `1681a55`（2026-10-24） | 单点故障 + 无法交接。本地快照 `work/cnb_harness/rk3288.c`（10-22）同样缺这些特性（已核：SYR827/GTP/gpio15 计数均为 0） |
| **G3** | `PROJECT-MEMORY.md` 停在 **§9.74（10-28）**；10-29 的自建内核（`zImage` 6,155,760 B，CI 构建 `3.10.0+ #1 SMP Mon Oct 19`）、10-30 的 v1/v2 DTB、三次 boot、spin dump **全部无记录** | 新会话无法复现今天的状态；与 GAP 16.56「陈旧对象」同族 |

---

## 5. 修复顺序（建议）

| 序 | 项 | 动作 | 判据 |
|---|---|---|---|
| P0 | PMU `PWRDN_ST` 位映射 | 按 §1.3 改 1 处 + 注释写死两表差异 | 重跑 `boot_v2`：**越过 3.258 s**，`clk_disable_unused` 返回 |
| P1 | CRU/GRF 全 1 | 改为"只让 PLL lock 位=1，其余 0"（按 `pll_wait_lock` 的 `status_offset/status_shift` 精确置位） | 同样能过 `pll_wait_lock`，但 pinctrl/时钟门控读到 0；若因此新增卡点，**说明该卡点是真缺陷，不是桩** |
| P1 | 结论标注纪律 | 凡"驱动失败/正常"结论，必须标 `桩因 / 真因`；catch-all 命中地址必须进报告 | 报告里不得出现未标注的"某驱动不行" |
| P2 | 三份分叉 | 以 66,472 B 为基线**推回 Test_migu**，`build_qemu.sh` 改为"校验 sha256 后才构建" | `build_qemu.sh` 输出源文件 sha256 与审计对象一致 |
| P2 | 臆造/死代码 | 删 `gpio15`；gpio0/8 拆独立状态；删 763-766；去 PMU 重复注册；修 3 处过期注释 | 编译零 warning，grep 无重复注册 |
| P3 | 常数量簇标注 | TSADC/SARADC/DDR PHY 在报告与 `ACCEPTANCE` 中标注"不可测" | 验收表显式列出"harness 不能证明的 6 件事" |

---

## 6. 附：本 harness 能证明 / 不能证明什么（给验收用）

| 能证明 | 不能证明 |
|---|---|
| 内核启动链走到哪一步、卡在哪个函数/寄存器 | 任何依赖真实时序的效果（帧率、音频、DDR 训练、温度） |
| 某驱动是否 **被桩值** 挡住（需人工区分） | 某驱动在真机上是否可用 |
| 触摸 I2C→input 事件链路（GTP 模型 + gpio7 EINT 已实测 128 B 事件） | TWRP UI 是否响应触摸（minui 能力位问题仍未解） |
| DDR/PMU 常量能否满足内核解析（等价于"能过 ddr_init"） | 真实 DDR 几何/容量/时序 |
| — | 任何块设备（无 eMMC/SD 模型）⇒ **TWRP 的刷写/备份/恢复完全不可测** |
| — | 显示（无 VOP/eDP/HDMI/LCDC 扫描输出）、GPU、VPU/HEVC 解码、WiFi/BT、USB |

---

## 7. P0 修复与单变量验证（2026-10-30 15:06 已完成）

**改动**：仅 `rk3288_pmu_read()` 的 `case 0x0c` 一处（CON→ST 位映射）+ 删除其上方那条已被证伪的
"Echo con directly" 注释。备份 `/data/workspace/qemu-src/hw/arm/rk3288.c.bak_20261030`。
**diff 范围自证**：`-6 / +18` 行，共 24 行；CRLF 行尾保持（首版脚本曾把全文 CRLF→LF，
已用 `fix_line_endings.py` 还原并逐行比对，见下）。

| 项 | 修前 | 修后 |
|---|---|---|
| 源文件 sha256 | `8e9f3116a04ec821…`（66,472 B / 1,545 行，全 CRLF） | `3f5b6184c36c0f29…`（66,853 B / 1,557 行，全 CRLF） |
| 变更行数 | — | `-6 / +18`（仅 PMU 一处；无其他语义改动） |
| QEMU 二进制 | 93,879,880 B（10-29 08:14） | 93,880,024 B（10-30 15:14，+144 B） |
| 同一命令行 | `boot_v2.log`：3.194 s 后 `[rk3288-ca] read 0xffaf0008` + `pmu +0x10/+0x14/+0x08` → **死等 timeout** | `boot_v3b.log`：**同样四行出现在 2035-2038 行**，随后 3.531 s `es8323 probe`、**4.070 s userspace init、`msh up`** |
| 命令行（严格对照） | `-m 512 -append "console=ttyFIQ0 earlycon=uart,mmio,0xff1a0000 init=/init rdinit=/init panic=1"` | 同上，**逐字相同**（`Kernel command line` / `Memory: 512MB` 两行亦相同） |
| 复跑 | — | `boot_v3c.log`（CRLF 还原后重建）：同样进 `msh`（7.49 s，含宿主负载抖动） |

**⇒ 单变量结论**：同一命令行、同一 kernel/DTB/initrd，只换二进制，卡死点消失。
PD_HEVC 断电轮询由"永不成立"变为"立即成立"。§1 的根因判定成立。

**副产物（真缺陷，未修，已登记）**：
`boot_v3` 新暴露出两条此前被卡点掩盖的真实失败 ——
`rk_iommu ff9c0440.hevc_mmu: iommu_reset failed → probe -2`、
`es8323 probe of 2-0010 failed with error -11`（音频 codec，i2c 0x10 无模型，NAK 路径）。
两者都是 **catch-all/缺模型** 所致，属 §2-B 类，须按"桩因"标注，不得当作内核缺陷。

**遗留**：`boot_v3` 的 `rockchip_ion_cma: Fail to allocate(1b00000)`（framebuffer 内存分配失败）
说明 512 MB 内存图下 LCDC 起不来；改用 `-m 2048`（`boot_v3.log`）同样报此错 ——
与 `memory_region_add_subregion(sysmem, 0, ram)`（RAM 仍在 0，见 §3-注释矛盾）相关，**待查**。
