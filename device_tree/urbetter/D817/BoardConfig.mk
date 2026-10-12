#
# Copyright (C) 2026 — Stage-2 adaptation for urbetter/D817 (P817, RK3288W)
# Base: twrpdtgen 3.0.0 output (Stage-1), reworked for omni twrp-9.0 build (TWRP 3.3.1).
#
# Evidence base (all measured locally from stock images, 2026-10-11):
#   * stock recovery.img: 4MB zero page + ANDROID! header @0x400000 (legacy RK layout)
#     header v0: kernel_addr 0x60408000, ramdisk_addr 0x62000000, tags 0x60088000,
#     page 16384, no separate dt section (kernel blob = zImage@0x24 + appended DTB,
#     total 6791568 bytes — sha256 identical to prebuilt/kernel).
#   * ro.sf.lcd_density=240 on device — matches TARGET_SCREEN_DENSITY 240 + portrait_hdpi.
#   * BOARD_RAMDISK_OFFSET 0x01c00000 reproduces stock ramdisk_addr (base+offset match).
#   * BOARD_KERNEL_TAGS_OFFSET must be NEGATIVE: stock tags_addr 0x60088000 < base
#     0x60400000, i.e. tags_addr - base = -0x378000. AIK's unpackbootimg.c prints that
#     as 0xffc88000 via C printf("%08x", negative_int); writing that literal into
#     BOARD_KERNEL_TAGS_OFFSET makes mkbootimg (python, bignum) compute
#     0x60400000 + 0xffc88000 = 0x160088000 > 0xFFFFFFFF -> struct.error at boot.img
#     build (observed in CI run 3411, 2026-10-11). Fixed by writing -0x378000 directly.
#   * Build alignment: omni twrp-9.0 emits mkbootimg header v0 (same as stock bootROM
#     expects). twrp-12.1 emits header v4 — REJECTED for this device (see report).
#
# Java: omni-9.0 builds with OpenJDK 8 (AOSP 9 default). python2.7 required —
# NOT shipped by ubuntu-22.04 apt; workflow builds 2.7.18 from source (gcc-10, pinned SHA).
#

DEVICE_PATH := device/urbetter/D817

# For building with minimal manifest
ALLOW_MISSING_DEPENDENCIES := true

# Architecture (32-bit armv7; stock kernel/ramdisk are 32-bit)
TARGET_ARCH := arm
TARGET_ARCH_VARIANT := armv7-a-neon
TARGET_CPU_ABI := armeabi-v7a
TARGET_CPU_ABI2 := armeabi
TARGET_CPU_VARIANT := generic
TARGET_CPU_VARIANT_RUNTIME := generic

# Bootloader
TARGET_BOOTLOADER_BOARD_NAME := rk3288
TARGET_NO_BOOTLOADER := true

# Display (matches stock ro.sf.lcd_density)
TARGET_SCREEN_DENSITY := 240

# Kernel — measured contract above; MUST NOT drift:
BOARD_KERNEL_BASE := 0x60400000
BOARD_KERNEL_PAGESIZE := 16384
BOARD_RAMDISK_OFFSET := 0x01c00000          # -> 0x62000000 == stock ramdisk_addr
BOARD_KERNEL_TAGS_OFFSET := -0x378000          # NEGATIVE offset: base 0x60400000 + (-0x378000) = 0x60088000 == stock tags_addr
# NOTE 1 (value): AIK's unpackbootimg.c prints tags_off as C printf("%08x", -0x378000) => 0xffc88000
#       (32-bit two's complement). Writing that literal makes mkbootimg (python bignum) compute
#       base + 0xffc88000 = 0x160088000 > uint32 -> struct.error: 'I' format requires 0 <= number <= 4294967295
#       (CI run 38113353914). Fixed by writing the negative value directly.
# NOTE 2 (argparse, 仅适用 9.0 链): AOSP-9 mkbootimg uses argparse, whose negative-number heuristic
#       (^-\d+$|^-\d*\.\d+$) does NOT match '-0x378000' (no decimal digits after '-'),
#       so '--tags_offset -0x378000' is rejected: 'argument --tags_offset: expected one
#       argument' (CI run 38125924872). Using the '=' form (--tags_offset=-0x378000) bypasses
#       the heuristic entirely. BOARD_MKBOOTIMG_ARGS is expanded verbatim by build/make/core/Makefile:782.
#       ⚠️ 纠错（2026-10-12 run#6/#7 实证）：本文件的 = 形式**只对 9.0 成立**。omni-4.4 树的
#       mkbootimg 是 C 程序（TeamWin/android_system_core android-4.4 mkbootimg/mkbootimg.c），
#       只认空格分隔形式；等号形式落入 else -> usage() 退出 -> boot.img/recovery.img Error 1。
#       且**不能**在 omni_D817_44.mk 里覆盖（产品 mk 先于本文件被读取，见下方修复段）；
#       4.4 链的修法是本文件下方按 TARGET_PRODUCT 分支输出空格形式。
BOARD_KERNEL_IMAGE_NAME := Image            # cosmetic; prebuilt kernel is forced
BOARD_MKBOOTIMG_ARGS += --ramdisk_offset $(BOARD_RAMDISK_OFFSET)
# ★ run#6/#7 双败根因与修复（2026-10-12，日志+上游源码实证）：
# 1. omni-4.4 的 mkbootimg 是 C 程序（TeamWin/android_system_core android-4.4
#    mkbootimg/mkbootimg.c），空格分隔 strcmp 链解析；`--tags_offset` 选项存在
#    （mkbootimg.c:153，usage 字符串漏印），只认空格形式。等号形式整体作为一个
#    arg 不匹配任何 strcmp → else 分支 usage() 退出 → boot.img Error 1。
# 2. 修复**必须在本文件做**，不能放产品 mk：AOSP 4.4 读取顺序为
#    build/core/envsetup.mk:115 product_config.mk（产品 mk）**先于**本文件
#    （config.mk:155）。产品 mk 里 `:=` 覆盖时 BOARD_*_OFFSET 尚为空，且本文件
#    的 += 之后还会把值追加进去（run#6 等号形式未识别 / run#7 空格+空值+等号
#    三重错位，两次 usage 退出同一根因）。
# 3. 本文件被读时 TARGET_PRODUCT 已由 product_config.mk 设置，可按产品分支：
#    - omni_D817_44（4.4/C mkbootimg）：空格形式
#    - omni_D817（9.0/python argparse）：= 形式（argparse negative-number
#      heuristic 要求，见下方 NOTE 2）
# 负值安全性（已核算）：strtoul("-0x378000",0,16) → 32 位 unsigned 0xFFC88000；
# hdr.tags_addr = 0x60400000 + 0xFFC88000 mod 2^32 = 0x60088000 = 设备实测契约。
ifneq ($(filter omni_D817_44,$(TARGET_PRODUCT)),)
BOARD_MKBOOTIMG_ARGS += --tags_offset $(BOARD_KERNEL_TAGS_OFFSET)
else
BOARD_MKBOOTIMG_ARGS += --tags_offset=$(BOARD_KERNEL_TAGS_OFFSET)
endif

# Kernel — prebuilt (do NOT compile; TARGET_FORCE_PREBUILT_KERNEL wipes kernel source deps)
TARGET_FORCE_PREBUILT_KERNEL := true
ifeq ($(TARGET_FORCE_PREBUILT_KERNEL),true)
TARGET_PREBUILT_KERNEL := $(DEVICE_PATH)/prebuilt/kernel
endif

# Recovery fstab — explicit, so both omni-9.0 and future flows see it
TARGET_RECOVERY_FSTAB := $(DEVICE_PATH)/recovery.fstab

# Partitions
BOARD_FLASH_BLOCK_SIZE := 1048576 # (BOARD_KERNEL_PAGESIZE * 64)
BOARD_BOOTIMAGE_PARTITION_SIZE := 33554432
BOARD_RECOVERYIMAGE_PARTITION_SIZE := 33554432
BOARD_HAS_LARGE_FILESYSTEM := true
BOARD_HAS_NO_MISC_PARTITION := false
BOARD_USES_MMCUTILS := true
BOARD_HAS_NO_SELECT_BUTTON := true

# Platform
TARGET_BOARD_PLATFORM := rk3288

# Recovery filesystems
TARGET_USERIMAGES_USE_EXT4 := true
TARGET_USERIMAGES_USE_F2FS := true

# TWRP Configuration (features valid in TWRP 3.3.1 / omni-9.0)
TW_THEME := portrait_hdpi
TW_EXTRA_LANGUAGES := true
TW_SCREEN_BLANK_ON_BOOT := true
TW_USE_TOOLBOX := true
TW_EXCLUDE_SUPERSU := true
TW_DEFAULT_LANGUAGE := zh_CN
TW_NO_LEGACY_PROPS := false

# ---------------------------------------------------------------------------
# 2026-10-12 根因修复 v1：omni twrp-4.4 / TWRP 2.8.7.x 兼容层
# 主根因：TWRP 3.3.1 的 sepolicy 版本=30 超出本机内核上限 28（实测
# /sys/fs/selinux/policyvers=28），内核 security_load_policy() 返回 -EINVAL
# → init 早期卡死 → 卡 LOGO。Android-4.4 基础的 TWRP 2.8.7.x 的 sepolicy
# 版本为 26-27 ≤ 28，可被内核接受。以下变量只在 4.4/2.8.7 构建中生效，
# 在 9.0/3.3.1 构建中为未使用变量（忽略），两条链互不影响。
# ---------------------------------------------------------------------------
# TWRP 2.8.7 用 DEVICE_RESOLUTION 而非 TW_THEME（后者 3.x 才有）
DEVICE_RESOLUTION := 1920x1200
# omni-4.4 用 RECOVERY_VARIANT 指定编译 TWRP（而非 CM/AOSP recovery）
RECOVERY_VARIANT := twrp
# 2.8.7 时代的兼容项
TW_INCLUDE_BUSYBOX := true
TW_NO_BATT_PERCENT := false