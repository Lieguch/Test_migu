# P817 / urbetter D817 —— Stage-2 TWRP 构建选型报告（2026-10-11）

> 目标：在手里只有「原厂 recovery.img（RK3288W, Android 4.4.4）」与
> 「Stage-1 twrpdtgen 设备树」的条件下，产出**可刷写、可触屏**的 TWRP recovery。
> 环境纪律：构建走 GitHub Actions（Test_migu 为 **public** 仓 → 标准托管 runner
> 4 vCPU / 16G RAM / 14G SSD / 单 job 6 小时上限 / **免费无限分钟**，无 2000 分钟月定额——
> 该月定额只适用于 private 仓）；本机 Windows **零构建零上传**；云开发只做判据诊断。

**上一轮遗留问题与纠正**：曾尝试 OFRP 11.0 分支与 CNB CI——OFRP 官方 sync 脚本
v031（2026-09-28）已**删除 11.0 manifest 支持**（现仅 16.0/14.1/12.1），该路线判死；
CNB 侧 `create-repo` 404 且 CNB CI 构建资源不足以承载 AOSP 同步（与既定
「GitHub 构建、CNB 判据」口径冲突），弃。

---

## 一、路线裁决（基于官方源 + 本地字节取证）

| 候选 | 结论 | 决定性证据 |
|---|---|---|
| OFRP (gitlab sync 11.0) | 判死 | sync/README：`v018 - the 11.0 manifest is no longer supported`（现仅 16.0/14.1/12.1） |
| twrp-**12.1** (aosp minimal) | 判死 | 产物 BOOT_HEADER_VERSION=4（bootloader 只认 v0）+ arm32 需 Vendor_arm_arm_biarch fork 分叉 / boot-hal 门禁；**TARGET_USES_64_BIT_BINDER:=true + Android-11 预编译 kill_arg → cache/recovery stderr 报 `update_engine_sideload: Killed`**（RIL/vold 被 SIGKILL，RK32 4.4 设备无此堆栈） |
| twrp-**9.0** (omni minimal, TWRP 3.3.1) | **√ 选定** | `remove-minimal.xml` 尾部 `include twrp-extras.xml`：**TeamWin `android_bootable_recovery@android-9.0`** 注入已证实；`vendor/omni`@omnirom live；**mkbootimg 产出 classic v0 头**；经典 `init=` ramdisk 集成（与原厂一致） |
| `rk3288/action_build_twrp_device_tree`（旧记忆） | 作废 | GitHub 该仓库已删（API 404），再加 wiki 流程本身不可自动化、产物还依赖 TF fork（12.1）→ 两者都死 |

---

## 二、设备字节契约（本地实测，构建必须逐一复现）

| 项 | 实测值 | 对应 BoardConfig |
|---|---|---|
| 原厂 recovery.img | 4MB 零页 + `ANDROID!`@0x400000（RK 旧布局） | 工作流校验 offset |
| boot 头版本 | **v0** | omni-9.0 原生产出 v0 |
| kernel_addr | 0x60408000 | BOARD_KERNEL_BASE=0x60400000 |
| ramdisk_addr | 0x62000000 | BOARD_RAMDISK_OFFSET=0x01c00000（base+offset 一致） |
| tags_addr | 0x60088000 | BOARD_KERNEL_TAGS_OFFSET=0xffc88000 |
| page | 16384 | BOARD_KERNEL_PAGESIZE=16384 |
| 内核 blob | zImage@0x24 + **追加 DTB**，共 6791568B | `prebuilt/kernel` sha256 == 原厂内嵌内核（实测一致） |
| 屏密度 | 240（实机 ro.sf.lcd_density） | TARGET_SCREEN_DENSITY=240 + TW_THEME=portrait_hdpi |

分区名核对：实机 cmdline 为 rknand 命名（`rknand_system` 等）＋mtdparts `rk29xxnand`
（eMMC 走 rk29xxnand 驱动）；twrpdtgen 生成的 fstab 分区名已与之一致。

---

## 三、为什么 12.1 判死（详细）

1. **boot 头代差**：AOSP 12 默认 `BOARD_BOOTIMG_HEADER_VERSION=4`，`mkbootimg --ramdisk`
   不再适用 → 生成的镜像带 v4 头 + `BOOT_IMAGE_HEADER_VERSION` 语义，2017 年的
   RK 旧 bootloader rk_load_image_from_storage 只认 v0（本机原厂分区就是 v0 实证）。
2. **32 位 gating**：twrp-12.1 要求 boot-hal / 64-bit binder（`TARGET_USES_64_BIT_BINDER`）；
   官方 TeamWin 32 位模板（samsung klte 等）**全部停在 android-6.0 分支**——无人做过
   arm32 × twrp-12.1 官方树。
3. **SIGKILL 地雷**：Android 11 起 prebuilt 最小 `kill_arg` 组合会 kill 掉
   update_engine/vold 守护进程 → RK 4.4 设备刷后 recovery stderr 常量
   `Killed` 日志，风险不可控。
4. **FDE 不支持**：README 明文 `FDE decryption is not presently supported in this branch`。
5. **Java/盘占用**：12.1 需 Java 11 + ~110k 行 manifest（移除清单 828 项）；产物
   vendor_boot/recovery 组合不适合本机 A-only recovery 语法。

## 四、twrp-9.0 的独特难点与解法

1. **python2.7 硬依赖**（源码构建唯一真障碍）：
   - omni-9.0 build 全线是 python2 脚本；ubuntu-22.04 apt 已无 python2；
     deadsnakes PPA **没有** jammy 的 python2.7 二进制（Launchpad API 实测 0 条）。
   - 解法：runner 内用 `gcc-10` 源码编译 CPython 2.7.18，SHA-256 锚定官方
     tarball：`da3080e…9a814`（本地已实测该 sha 一次，本地副本已删、不入库）。
2. **OpenJDK 8**：omni-9.0（AOSP-9）默认 JDK8；`setup-java zulu8` + `default:true`。
3. **设备树失配修正**（twrpdtgen 产物是 16.1 时代语法，放进 9.0 会炸）：
   - 删 `vendor/omni/config/common.mk` 之外不存在的 `full_base_telephony`、
     16.x prop（PLATFORM_VERSION 16.1.0 等）→ 换 `core_32_bit.mk + base.mk`；
   - `TARGET_USES_64_BIT_BINDER`、APEX 等 16.x 变量已从 BoardConfig 移除；
   - 显式 `TARGET_RECOVERY_FSTAB`（9.0 语义）；`BOARD_NO_SELECT_BUTTON=true`
     （应对电源键失效：TWRP 依赖触摸）。
4. **盘空间**：14G SSD，minimal manifest 只 sync 必需项（`repo sync -c`，浅克隆）；
   构建后仅 recovery ramdisk（含 adbd），系统镜像不产——已控制 `mka adbd recoveryimage`
   目标，避免整包生产。

## 五、交付与回退纪律（§9.5 红线不变）

- 产物：`TWRP 3.3.1` `recovery.img`，Release 挂 tag `stage2-<run_id>`，
  附 sha256 校验值。
- 刷写：仍是**用户现场动作**。本机 `dd` 只写 `recovery` 分区；先确认
  `work/backup/recovery.img` 备份可读。严禁动 uboot/parameter/boot/resource。
- 若构建失败：**只允许按日志根因修设备树/工作流**，不降低届控（不换 gitlab
  镜像捷径、不关 python2、不降 Java 断言）。

## 六、本轮实际落盘内容

1. `device_tree/urbetter/D817/BoardConfig.mk` —— 重写为 omni-9.0 兼容 + 字节契约锚定。
2. `device_tree/urbetter/D817/omni_D817.mk` —— core_32_bit + base + vendor/omni common 规范式。
3. `device_tree/urbetter/D817/device.mk` —— 移除 16.x 项，纯净恢复树无 vendor blobs。
4. `.github/workflows/build_twrp_stage2.yml` —— 选型化 Stage-2 构建流水线
   （sudo 环境、JDK8、自编译 py2.7、OFRP 风格 env 依赖最小化、repo sync 重试、
   copy 设备树、lunch omni_D817-eng + mka adbd recoveryimage、字节契约自校验、
   rel-upload、12G swap）。