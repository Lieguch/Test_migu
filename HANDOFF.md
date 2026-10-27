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
