#
# Copyright (C) 2026 — omni-9.0 compatible product definition for urbetter/D817
# Reworked from twrpdtgen output: the generated file inherited
#   vendor/omni/config/common.mk + full_base_telephony and set 16.1-era props
# that do not exist in the Android-9.0 build tree.
#
# Canonical omni twrp-9.0 pattern for a 32-bit device (verified 2026-10-11
# against the TWRP device-tree authoring guide basiotte/Make-A-TWRP-Tree §9
# and the actual TeamWin/android_build@android-9.0 target/product inventory):
# AOSP-9 has NO core_32_bit.mk (that split only exists in Android 10+);
# the 9.0 32-bit product chain is: core.mk -> core_base.mk -> core_minimal.mk
# (zygote32, i.e. 32-bit) -> base.mk -> embedded.mk. The guide's pattern below
# inherits full_base + core_minimal + embedded; base.mk/embedded.mk are also
# reached transitively, so repeating them is unnecessary.
#
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/core_minimal.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/embedded.mk)

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