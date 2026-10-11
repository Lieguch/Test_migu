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
# NOTE: AIK/unpackbootimg.c prints this as 0xffc88000 (32-bit two's-complement of -0x378000),
#       but mkbootimg (python, arbitrary precision) treats 0xffc88000 as a POSITIVE int,
#       giving base+offset = 0x160088000 > uint32 -> struct.error: 'I' format requires 0 <= number <= 4294967295.
#       mkbootimg's parse_int() does accept the '-0x...' literal, so write the offset as a negative number.
BOARD_KERNEL_IMAGE_NAME := Image            # cosmetic; prebuilt kernel is forced
BOARD_MKBOOTIMG_ARGS += --ramdisk_offset $(BOARD_RAMDISK_OFFSET)
BOARD_MKBOOTIMG_ARGS += --tags_offset $(BOARD_KERNEL_TAGS_OFFSET)

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