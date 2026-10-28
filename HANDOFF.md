# rkpad TWRP QEMU — 交接文档（HANDOFF）

> 用途：供接手的 Agent / 大模型快速接手，读完即可继续，无需从头探索。
> 维护：每次重大变更或达到里程碑后更新本文件。

## 0. 当前版本状态

- 仓库：https://github.com/Lieguch/Test_migu，分支 `main`
- 最新提交：`1681a55` Add Codespaces devcontainer + QEMU RK3288 patch 1 (DDRIFF_ROOTCAUSE)
- 远端与本地一致（`git ls-remote origin main` = `1681a55`）
- 环境：CNB 云开发额度已到（不可用），GitHub Codespaces 路线已取消（用户不愿手动操作，且本机无法通过 API 自动创建），Cloudflare Workers 不适合（Serverless 受限运行时，无任意二进制支持）。
- 硬阻塞：缺少可执行编译和验证的环境（无可用云开发环境，本机 WSL 被安全策略阻止，MSYS2 未验证）。

## 1. 已就位交付物（无需环境即可使用）

| 文件 | 内容 | 路径 |
|------|------|------|
| `qemu-harness/rk3288.c` | QEMU v10.0.1 RK3288 机器模型（milestone 2），已应用补丁 1 | `qemu-harness/rk3288.c` |
| `qemu-harness/DDRIFF_ROOTCAUSE.md` | t78 ddr_init NULL-pointer deref 根因分析 + 两个补丁记录 | `qemu-harness/DDRIFF_ROOTCAUSE.md` |
| `qemu-harness/build_qemu_codespace.sh` | 在 Codespaces/CNB 中构建 QEMU v10.0.1 脚本 | `qemu-harness/build_qemu_codespace.sh` |
| `qemu-harness/run_t78_verify.sh` | t78 等效组合验证脚本（run13/zImage + twrp_ramdisk.gz） | `qemu-harness/run_t78_verify.sh` |
| `qemu-harness/patch2_ddr_rk32_contingency.diff` | 补丁 2：内核 ddr_rk32.c ddr_init 容错回退（diff 模板） | `qemu-harness/patch2_ddr_rk32_contingency.diff` |
| `qemu-harness/ROUTE_A_B_SERVICEMAN.md` | Route A（vdd_logic 固定电源）、Route B（DDR PCTL/PHY DLL-lock 建模）、ramdisk servicemanager 添加方案 | `qemu-harness/ROUTE_A_B_SERVICEMAN.md` |
| `.devcontainer/devcontainer.json` + `Dockerfile` + `setup.sh` | Codespaces 环境配置（Ubuntu 22.04，预装 gcc-arm/ninja/QEMU/dtc） | `.devcontainer/` |

## 2. 补丁 1（已应用，待环境验证）

**位置**：`qemu-harness/rk3288.c`

**内容**：
- 定义 `RK3288_DDR_VIRT_BASE 0x000d0000ULL`（RK_DDR_VIRT 对应的物理地址）
- 在 `rk3288_init()` 中，`rk3288_add_io(sysmem, RK3288_DDR_BASE, ...)` 之后，追加：
  ```c
  rk3288_add_io(sysmem, RK3288_DDR_VIRT_BASE, RK3288_DDR_SIZE, &rk3288_ddr_ops, "rk3288-ddr-virt");
  ```

**目的**：让内核 `ddr_init()` 从 `RK_DDR_VIRT` (0x000d0000) 读取 `pDDR_Reg` 时能命中 QEMU DDR model，避免 NULL-pointer deref panic（t78 阻塞点）。

**预期验证结果**：串口输出出现 `I: LANG: zh_CN`，无 `ddr_init` NULL-pointer deref panic。

## 3. 补丁 2（已编写 diff 模板，待环境应用）

**文件**：`qemu-harness/patch2_ddr_rk32_contingency.diff`

**目标**：`arch/arm/mach-rockchip/ddr_rk32.c`，函数 `ddr_init()`

**内容**：`pDDR_REG(ch)` 为 0 时，回退 `pDDR_Reg` 到 `0xff610000`（QEMU DDR model 地址），`pPHY_Reg` 回退到 `0xff620000`，`pMSCH_Reg` 回退到 `0xffac0000`。

**注意**：GitHub 被 FastGithub TLS 拦截，无法获取内核源码实际行号。接手后需在环境中按实际文件调整 diff 行号。

## 4. Route A：vdd_logic 固定电源（显示上电）

**文件**：`qemu-harness/ROUTE_A_B_SERVICEMAN.md` §Route A

**问题**：act8846 PMU 在 QEMU 中未建模，vdd_logic 读取失败，显示保持黑屏。

**方案 A1（推荐）**：添加 act8846 dummy 驱动，固定返回 vdd_logic = 600mV～1200mV，不操作真实硬件。

**方案 A2**：启用 act8846 驱动但不启用 ddrfreq，内核启动参数加 `clk_ignore_unused cpufreq=disabled`。

**预期**：显示电源上电，LCDC0 正常输出，TWRP UI 可见。

## 5. Route B：DDR PCTL/PHY STAT/DLL-lock 位建模（解除 5.2s ddrfreq panic）

**文件**：`qemu-harness/ROUTE_A_B_SERVICEMAN.md` §Route B

**问题**：t78 boot 在 5.2s 后因 ddrfreq 导致 panic halt。内核访问 DDR PCTL(0xff610000)/PHY(0xff620000) 的 STAT/DLL-lock 位，QEMU DDR model DLL-lock 位未就绪导致死等。

**方案 B1**：QEMU `rk3288.c` `rk3288_ddr_read` 中，对 PHY PUBL0 PGSR @ 0x004 返回 `PGSR_DLDONE`（已锁定），对 DXGSR @ 0x100 返回 0（无训练错误）。

**方案 B2**：内核 `ddr_move_to_Access_state` 中增加 DLL-lock 超时容错，不再无限等待。

**预期**：5.2s 后不再 panic halt，内核继续启动，进入 TWRP 主程序。

## 6. ramdisk servicemanager 添加（消除 binder 噪声）

**文件**：`qemu-harness/ROUTE_A_B_SERVICEMAN.md` §ramdisk servicemanager

**问题**：ramdisk 缺失 servicemanager 二进制，binder 通信失败，反复输出 "binder: transaction failed 29189"。

**方案**：
1. 从 Android 4.4/5.1 源码树提取 servicemanager 二进制（arm32）
2. 使用 `patch_ramdisk4.py` 将 servicemanager 添加到 ramdisk `/system/bin/` 或 `/sbin/`
3. `init.recovery.service.rc` 追加 `service servicemanager /system/bin/servicemanager`

## 7. 下一步（接手后）

### 优先级 1：获取可用环境（硬阻塞）

以下三种路线任一即可继续：

1. **本地 MSYS2 安装编译工具链**：安装 `gcc-arm-none-eabi`、`ninja-build`、`qemu-system-arm`，在 Windows 本地编译 QEMU v10.0.1（不开服务、不开端口，仅编译验证）。
2. **其他云开发环境**：Replit、CodeSandbox、StackBlitz、腾讯云 Cloud Studio 等，需支持任意二进制编译和持久化 Linux 环境。
3. **CNB 额度恢复**：若 CNB 云开发额度重置，可直接使用已就位的 `build_qemu_codespace.sh`。

### 优先级 2：环境就绪后执行

1. 在环境中运行 `bash qemu-harness/build_qemu_codespace.sh` 构建 QEMU v10.0.1
2. 验证 `./build/qemu-system-arm -machine help | grep rk3288` 显示机器已注册
3. 放置 `zImage`（run13 版本）、`twrp_ramdisk.gz`、`p817.dtb` 到工作区
4. 运行 `bash qemu-harness/run_t78_verify.sh`，预期看到 `I: LANG: zh_CN`
5. 应用补丁 2（内核 ddr_rk32.c 容错回退）
6. 推进 Route A、Route B、servicemanager 添加
7. 更新 HANDOFF.md 并推送 GitHub，完成跨 agent 交接

## 8. 关键文件职责

| 文件 | 职责 |
|------|------|
| `qemu-harness/rk3288.c` | QEMU RK3288 机器模型（补丁 1 已应用） |
| `qemu-harness/build_qemu_codespace.sh` | QEMU 构建脚本 |
| `qemu-harness/run_t78_verify.sh` | t78 等效验证脚本 |
| `qemu-harness/patch_ramdisk4.py` | ramdisk cpio newc 改写工具（--set/--add） |
| `qemu-harness/init.recovery.service.rc` | recovery 服务配置（含 console 选项） |
| `qemu-harness/sbin_modprobe` | 18 字节 dummy modprobe 脚本 |
| `qemu-harness/DDRIFF_ROOTCAUSE.md` | 根因分析 + 两个补丁记录 |
| `qemu-harness/patch2_ddr_rk32_contingency.diff` | 补丁 2 diff 模板 |
| `qemu-harness/ROUTE_A_B_SERVICEMAN.md` | Route A/B + servicemanager 方案 |

## 9. 铁律（不可违反）

1. 原厂 `icube` / `rkgame` / `driver.so` / 原厂 `cores/` / `autorun` / SD 其余原厂文件**一律不动**，只覆盖**我们自己构建的同名文件**。
2. 改原厂文件前必须先说「改什么 / 怎么改 / 如何回退」。
3. 构建产物（`.o`）**不入库**；编译够便宜就不要缓存。
4. 每次代码提交必须附带更新版 HANDOFF.md 并推送 GitHub，完成跨 agent 交接。

---

## 10. 2026-10-28 实测更新（InstaBox 云机）：t78 已能跑到 userspace init

### 可用环境（替代已耗尽的 CNB）
- InstaBox 机器 `m_agqychrdvyurnyynpkspkaam6q`（4vCPU/8GiB/Debian 13，免密 sudo）
- 凭据与 helper 见 `~/.workbuddy/user-*/INSTABOX.md` 与 `bin/ibx.sh`
- 机器上：`/data/workspace/rk3288/qemu-src/build/qemu-system-arm`（QEMU v10.0.1 + rk3288 机器，已构建）
- 输入：`/data/workspace/t78_stage/{zImage_run13,twrp_ramdisk.gz,stock_*,p817.dtb}`

### ★ 可跑配方（关键，别丢 bootargs）
```bash
./rk3288/qemu-src/build/qemu-system-arm -M rk3288 -smp 1 -m 2048 \
  -kernel t78_stage/zImage_run13 -initrd t78_stage/twrp_ramdisk.gz \
  -append "console=ttyS2,115200 vmalloc=496M mem=2048M clk_ignore_unused cpufreq=disabled loglevel=7" \
  -display none -serial file:logs/t78.log -monitor none -no-reboot -dtb p817_run.dtb
```
`-append` 会**整段替换** DTB 的 `/chosen/bootargs`（原值 `vmalloc=496M`），漏掉 `vmalloc=`/`mem=` 时
内核在 `early_alloc_aligned()` 就踩未映射线性区（`DFAR=0xee7ff000`），串口 0 字节。

### 实测结果（logs/t78_ok.log，90 756 B / 1 345 行）
- ✅ `DDR DEBUG: init success` ×2、`Freeing initrd` ×2 —— **`ddr_init` NULL 解引用不再出现**
- ✅ `init: init first stage started!` / `First stage mount skipped (recovery mode)` —— TWRP 的 init 已执行
- ❌ 5.44–5.49 s：`ddrfreqd` oops（`regulator_get_voltage` ← `rockchip_cpufreq_reboot_limit_freq` ← `ddrfreq_work`）
  根因链：`act8846 gpios` 引用 gpio0（`0xb2`），而 pinctrl 只建了 gpio1..8/15 → probe 失败 →
  `vdd_logic/vdd_arm/vdd_gpu` 缺失 → `DVFS ERR: can't get regulator` ×10 → ERR_PTR 被当指针解引用。

### 补丁 1 的最终裁定
- `0x000d0000` 注册 DDR model **不可用**：zImage 装在 `0x00010000`，自解压映像覆盖到 `0x00d165xx`，
  该地址在映像内，挖 16 KiB 后自解压器死在 `0xd13af8 b .`。
- 代码里已改为默认关闭（`#ifdef RK3288_DDR_VIRT_REGION`），并在注释中记录实测。

### 下一步
1. 补 QEMU 的 `gpio0`（bank0 的 `mux/pull/drv` 附加 reg 读回）→ act8846 probe 通过 → regulator 出现。
2. 或改 DTB `act8846/gpios` 全用已存在的 gpio7 两个 pin，并验证 `vdd_logic` 是否注册。
3. 兜底：内核源码重建，在 `rockchip_cpufreq_reboot_limit_freq()` 里 `IS_ERR()` 直接返回。
4. 之后才是 Route A（显示上电）与 servicemanager。

### 复现用仪器（机器上）
- `qmp_pc.py` / `qmp_mem.py`：QMP 取寄存器/内存
- `vmlinux-to-elf kimg.bin vmlinux.elf`：从 `pmemsave` dump 恢复 71 336 个符号（已验证可用）
- `-d int,guest_errors -D logs/int.log`：抓首次异常（DFAR/IFAR）
- `-d in_asm -D logs/inasm.log`：看最后执行的翻译块

---

## 11. 2026-10-28 三次实测：三条根因全解，stock recovery 已跑起来

| # | 阻塞 | 根因 | 解法（已固化） |
|---|---|---|---|
| ① | 串口 0 字节、早期 `DFAR=0xee7ff000` | `-append` 整段替换 DTB `/chosen/bootargs`，丢了 `vmalloc=` | 命令行补 `vmalloc=496M mem=2048M` |
| ② | 5.44–5.49 s `ddrfreqd` oops（`regulator_get_voltage` 解引用 `ERR_PTR`） | DDR 变频在跑，而 PMIC/regulator 缺失 | **官方文档解法**：`/dvfs/vd_logic/pd_ddr/clk_ddr` 置 `disabled`（= kernel 3.10 的 `clk_ddr_dvfs_table`） |
| ③ | init 加载 sepolicy 失败 → reboot bootloader | `twrp_new.img` 的 ramdisk 是 **android-9 TWRP 3.3.1**（policy v30），内核只支持 ≤28 | 属 **artefact 选错**：应换 omni-4.4 / TWRP 2.8.7 的 ramdisk |

**里程碑**：`stock 4.4 zImage + stock ramdisk + 上述配方` → `# Starting recovery on ... 1970`，
recovery 解析 fstab、`SetSdcardRootPath`、报 `/cache` 挂载失败、`failed to read font`；
之后稳定跑 `>>>> pwrsw pin = 0,2`（内核电源键轮询）**100 s 无 oops / 无 panic / 无 reboot**。

**新增脚本**：`qemu-harness/mk_p817_run_dtb.sh` —— 一键生成 QEMU 用 DTB（含上述关键 dvfs 关闭）。

**下一步**：拿到/构建 TWRP 2.8.7(omni-4.4) ramdisk → 同配方跑；随后 Route A（显示上电）。
