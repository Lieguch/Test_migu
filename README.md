# P817 触屏 TWRP Recovery 适配（RK3288W）

> 缘起：P817 安卓 4.4 平板的**电源键硬件失效**，原厂 recovery 菜单需「音量键导航 + 电源键确认」，
> 电源键死 → 菜单内无法确认。改用 **TWRP**（全触屏 UI）绕开死电源键，复用原厂内核已有的
> Goodix GT9xx 触屏驱动，无需额外驱动。

## 仓库内容
- `recovery.img` —— P817 原厂 recovery（32MB，已取证：内核 built-in Goodix 触屏驱动）。
- `.github/workflows/build_twrp_dt.yml` —— GitHub Actions 工作流，从 `recovery.img` 生成 TWRP 设备树。

## 构建（Stage 1：设备树）
推送到 `main` 或手动 `workflow_dispatch` 即触发。工作流会：
1. 从 Rockchip `rkimage` 中抽取内嵌的标准 Android boot 镜像（`ANDROID!` 魔数定位）；
2. 用 `twrpdtgen` 生成 TWRP 设备树；
3. 打包 `DeviceTree.zip` 作为 artifact / Release 产出。

产出在仓库 [Releases](../../releases) 与 Actions artifact 下载。

## 重要说明（两阶段）
- **本仓库产出的是 Stage-1 设备树**，不是可直接 `dd` 刷入的 TWRP recovery.img。
- **Stage-2** 仍需：用本设备树 + 预编译内核/dtb（取自原厂 recovery）编译 TWRP 源码，
  产出真正可刷的 `twrp.img`。该步为重构建（需 TWRP/OmniROM 源码 + 预编译内核），待排期。

## 刷写与回退红线
- 只动 `recovery` 分区（`dd` 写）；严禁动 uboot / parameter / boot / resource。
- 保留原厂 `recovery.img` 备份，任何 TWRP 刷入前确认备份可读，便于回退。
- 设备无 USB 数据口 → 线刷/救砖不可用，刷写只能本机 root + `dd`。
