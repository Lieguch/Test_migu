#
# Copyright (C) 2026 The Android Open Source Project
# Copyright (C) 2026 SebaUbuntu's TWRP device tree generator
#
# SPDX-License-Identifier: Apache-2.0
#
# urbetter/D817 — device makefile (TWRP 3.3.1 / omni-9.0).
# No proprietary blobs are needed for recovery: everything TWRP needs
# comes from the source tree + the prebuilt stock kernel (Goodix touch,
# ACT8846 PMIC drivers are built into that kernel).
#
LOCAL_PATH := device/urbetter/D817

# Recovery needs no vendor blobs on this device (touch/display via kernel in-tree
# drivers; wifi/camera/video not used by recovery).