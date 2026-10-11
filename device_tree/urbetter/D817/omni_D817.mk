#
# Copyright (C) 2026 The Android Open Source Project
# Copyright (C) 2026 SebaUbuntu's TWRP device tree generator
#
# SPDX-License-Identifier: Apache-2.0
#

# Inherit from those products. Most specific first.
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base_telephony.mk)

# Inherit some common Omni stuff.
$(call inherit-product, vendor/omni/config/common.mk)

# Inherit from D817 device
$(call inherit-product, device/urbetter/D817/device.mk)

PRODUCT_DEVICE := D817
PRODUCT_NAME := omni_D817
PRODUCT_BRAND := urbetter
PRODUCT_MODEL := P817
PRODUCT_MANUFACTURER := urbetter

PRODUCT_GMS_CLIENTID_BASE := android-urbetter

PRODUCT_BUILD_PROP_OVERRIDES += \
    PRIVATE_BUILD_DESC="rk3288-userdebug 4.4.4 KTU84Q eng.xierong.20180307.164546 test-keys"

BUILD_FINGERPRINT := urbetter/rk3288/rk3288:4.4.4/KTU84Q/eng.xierong.20180307.164546:userdebug/test-keys
