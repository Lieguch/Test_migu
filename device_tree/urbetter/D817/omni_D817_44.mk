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
