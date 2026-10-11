#
# Copyright (C) 2026 — omni-9.0 compatible product definition for urbetter/D817
# Reworked from twrpdtgen output: the generated file inherited
#   vendor/omni/config/common.mk + full_base_telephony and set 16.1-era props
# that do not exist in the Android-9.0 build tree. This version follows the
# canonical omni twrp-9.0 pattern: core_32_bit + base + vendor/omni common + device.
#

# Inherit from those products. Most specific first.
$(call inherit-product, $(SRC_TARGET_DIR)/product/core_32_bit.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/base.mk)

# Inherit some common Omni (TWRP) stuff.
$(call inherit-product, vendor/omni/config/common.mk)

# Inherit from D817 device
$(call inherit-product, device/urbetter/D817/device.mk)

PRODUCT_DEVICE := D817
PRODUCT_NAME := omni_D817
PRODUCT_BRAND := urbetter
PRODUCT_MODEL := P817
PRODUCT_MANUFACTURER := urbetter

# Android 9-era props only (no 16.x inventables like PLATFORM_VERSION)
PRODUCT_PROPERTY_OVERRIDES += \
    ro.product.name=D817 \
    ro.build.characteristics=tablet