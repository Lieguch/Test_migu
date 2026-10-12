#
# Copyright (C) 2026 — omni twrp-4.4 (Android 4.4) product definition for
# urbetter/D817 (P817, RK3288W).
#
# ★ 2026-10-12 根因修复 v1：omni-9.0 产品链继承的 core_minimal.mk / embedded.mk
#   在 Android-4.4 树中不存在 → 4.4 构建会 fail。本文件只继承 4.4 时代存在的
#   full_base.mk + vendor/omni/config/common.mk，两条产品链（9.0 / 4.4）共存于
#   同一设备树，互不影响。
#
# 产物 = TWRP 2.8.7.x（android-4.4 分支），sepolicy 版本 26-27 ≤ 内核上限 28。
#

# Android 4.4 产品链：full_base -> core.mk（4.4 存在；core_minimal/embedded 不存在）
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base.mk)

# Omni (TWRP) 通用配置（omni android-4.4 分支存在）
$(call inherit-product, vendor/omni/config/common.mk)

# 继承设备定义
$(call inherit-product, device/urbetter/D817/device.mk)

PRODUCT_DEVICE := D817
PRODUCT_NAME := omni_D817_44
PRODUCT_BRAND := urbetter
PRODUCT_MODEL := P817
PRODUCT_MANUFACTURER := urbetter

# Android 4.4 时代属性
PRODUCT_PROPERTY_OVERRIDES += \
    ro.product.name=D817 \
    ro.build.characteristics=tablet

# ★ run#6 真因修复（2026-10-12，全部有上游源码 + 日志实证）：
# omni-4.4 的 mkbootimg 是 **C 程序**（TeamWin/android_system_core
# android-4.4 分支 mkbootimg/mkbootimg.c），参数解析为空格分隔的 strcmp 链：
#   while(argc>0){ arg=argv[0]; val=argv[1]; argc-=2; argv+=2;
#     ... else if(!strcmp(arg,"--tags_offset")) tags_offset=strtoul(val,0,16);
#     else return usage(); }
# 等号形式 `--tags_offset=-0x378000` 整体作为一个 arg，不匹配任何 strcmp
# → else 分支 → usage() 退出 → make Error 1（run#6 死在 boot.img；
# build/core/Makefile:809 的 recovery.img 规则同样传 BOARD_MKBOOTIMG_ARGS，
# 一样会死，recovery.img 全程未被构建）。
# BoardConfig.mk 的 = 形式是给 9.0 链（python argparse，negative-number
# heuristic 要求 = 形式）用的；本产品覆盖为空格形式。
# 负值安全性（已核算）：strtoul("-0x378000",0,16) → 32 位 unsigned 0xFFC88000；
# hdr.tags_addr = 0x60400000 + 0xFFC88000 mod 2^32 = 0x60088000 = 设备实测契约。
BOARD_MKBOOTIMG_ARGS := \
    --ramdisk_offset $(BOARD_RAMDISK_OFFSET) \
    --tags_offset $(BOARD_KERNEL_TAGS_OFFSET)
