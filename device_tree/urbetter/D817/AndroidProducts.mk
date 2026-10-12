#
# Copyright (C) 2026 The Android Open Source Project
# Copyright (C) 2026 SebaUbuntu's TWRP device tree generator
#
# SPDX-License-Identifier: Apache-2.0
#
# 双产品链共存（2026-10-12 根因修复 v1）：
#   omni_D817      → omni twrp-9.0 / TWRP 3.3.1（sepolicy v30，本机内核不接受，留作基线）
#   omni_D817_44   → omni twrp-4.4 / TWRP 2.8.7.x（sepolicy v26-27 ≤ 内核上限 28 ★修复路线）
#

PRODUCT_MAKEFILES := \
    $(LOCAL_DIR)/omni_D817.mk \
    $(LOCAL_DIR)/omni_D817_44.mk

COMMON_LUNCH_CHOICES := \
    omni_D817-user \
    omni_D817-userdebug \
    omni_D817-eng \
    omni_D817_44-user \
    omni_D817_44-userdebug \
    omni_D817_44-eng
