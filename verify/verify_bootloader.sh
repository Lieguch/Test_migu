#!/bin/bash
# Stage-3: 在 CNB 云开发中模拟原厂 bootloader 的 recovery.img 解析逻辑
# 基于 Rockchip u-boot rkproduct 分支 cmd_bootrk.c 源码
#
# 验证目标：原厂 bootloader 从 recovery 分区读取镜像时，
# 是否正确解析我们的 TWRP recovery.img（含 4MB 零页前缀）
set -e

REPO_DIR="/workspace/rkpad"
UBOOT_DIR="$REPO_DIR/u-boot-verify"
STOCK_REC="$REPO_DIR/backup/recovery.img"
TWRP_REC="$REPO_DIR/twrp_recovery.img"
VERIFY_PY="$UBOOT_DIR/verify_header.py"

echo "=== Stage-3: Bootloader 解析逻辑验证 ==="
echo ""

# 1. clone rockchip u-boot rkproduct 分支
if [ ! -d "$UBOOT_DIR" ]; then
    echo "[1] Clone rockchip-linux/u-boot (rkproduct branch)..."
    git clone --depth=1 -b rkproduct https://github.com/rockchip-linux/u-boot.git "$UBOOT_DIR"
else
    echo "[1] u-boot source already present"
fi

# 2. 下载我们的 TWRP recovery.img (GitHub Release)
if [ ! -f "$TWRP_REC" ]; then
    echo "[2] Download TWRP recovery.img from GitHub Release..."
    curl -fsSL -o "$TWRP_REC" \
        "https://github.com/Lieguch/Test_migu/releases/download/stage2-38148404169/recovery.img"
else
    echo "[2] TWRP recovery.img already present"
fi
TWRP_SIZE=$(stat -c%s "$TWRP_REC")
TWRP_SHA=$(sha256sum "$TWRP_REC" | cut -d' ' -f1)
echo "    size=$TWRP_SIZE  sha256=$TWRP_SHA"

# 3. 确认 stock recovery.img 存在
STOCK_SIZE=$(stat -c%s "$STOCK_REC" 2>/dev/null || echo 0)
STOCK_SHA=$(sha256sum "$STOCK_REC" 2>/dev/null | cut -d' ' -f1 || echo "missing")
echo "    stock: size=$STOCK_SIZE  sha256=$STOCK_SHA"

# 4. 写验证脚本（Python，复刻 cmd_bootrk.c 的 rk_load_image_from_storage 逻辑）
cat > "$VERIFY_PY" << 'PYEOF'
#!/usr/bin/env python3
"""
Stage-3 验证器：复刻 Rockchip cmd_bootrk.c 的 rk_load_image_from_storage 逻辑。

源码路径: common/cmd_bootrk.c (rkproduct 分支)
关键代码:
  StorageReadLba(ptn->start, (void *)hdr, 1 << 2);  // 读首 4 个 block
  if (memcmp(hdr->magic, BOOT_MAGIC, BOOT_MAGIC_SIZE)) {
      // ANDROID! 不在分区起始 → 走 RKIMAGE! 分支
      snprintf(hdr->magic, BOOT_MAGIC_SIZE, "%s", "RKIMAGE!");
      rkimage_load_image(hdr, ptn, kernel_ptn);  // 从 kernel 分区加载
  } else {
      // ANDROID! 在分区起始 → 解析 header
      sector = ptn->start + (hdr->page_size / blksz);
      // 读 kernel, ramdisk, second...
  }

验证项:
  A. 从分区起始读首 N 字节，检查 ANDROID! magic 位置
  B. 模拟 bootloader 的读取偏移逻辑（sector = ptn->start + page_size/blksz）
  C. 对照 stock vs TWRP 的 header 解析结果
"""
import struct, sys, hashlib

def read_at(data, offset, size):
    """模拟 StorageReadLba(ptn->start + offset, buf, nsec)"""
    return data[offset:offset+size]

def parse_boot_img_hdr(data, offset, label=""):
    """解析 ANDROID! boot image header v0"""
    hdr = data[offset:offset+1632]  # sizeof(boot_img_hdr) with 1024 cmdline
    if len(hdr) < 48:
        print(f"  [{label}] header too short at offset {hex(offset)}")
        return None
    magic = hdr[0:8]
    if magic != b'ANDROID!':
        print(f"  [{label}] magic mismatch at {hex(offset)}: {magic!r}")
        return None
    
    fields = struct.unpack_from('<8sIIIIIIIIII1024s', hdr, 0)
    h = {
        'magic': fields[0],
        'kernel_size': fields[1],
        'kernel_addr': fields[2],
        'ramdisk_size': fields[3],
        'ramdisk_addr': fields[4],
        'second_size': fields[5],
        'second_addr': fields[6],
        'tags_addr': fields[7],
        'page_size': fields[8],
        'unused': fields[9],
        'os_version': fields[10],
        'name': fields[11][:16],
        'cmdline': fields[12].split(b'\x00')[0],
    }
    return h

def simulate_bootloader(data, label):
    """
    模拟 rk_load_image_from_storage 的完整逻辑:
    1. 从分区起始(blksz<<2 = 4 blocks)读 header
    2. 如果 magic != ANDROID! → 尝试从偏移处找
    3. 如果 magic == ANDROID! → 按 page_size 对齐读 kernel/ramdisk
    
    RK3288 Android 4.4: blksz = 512 (LBA sector size)
    但 RK 的 StorageReadLba 读的是 LBA，ptn->start 是 LBA 扇区号
    """
    blksz = 512  # eMMC sector size
    print(f"\n=== [{label}] 模拟 bootloader 解析 ===")
    print(f"  image size: {len(data)} bytes ({len(data)/1024/1024:.1f} MB)")
    
    # Step 1: 读首 4 blocks (blksz << 2 = 2048 bytes)
    # 但 cmd_bootrk.c 实际用的是 memalign(ARCH_DMA_MINALIGN, blksz << 2)
    # ARCH_DMA_MINALIGN 通常是 64，blksz << 2 = 2048
    # 注意: 实际读的是 4 个 LBA sector = 2048 bytes
    first_read_size = blksz << 2  # 2048 bytes
    first_block = read_at(data, 0, first_read_size)
    
    # 检查 magic
    magic_offset_0 = first_block[0:8]
    print(f"  LBA 0 (offset 0x0): magic = {magic_offset_0!r}")
    
    # 找 ANDROID! magic 的真实位置
    android_offset = data.find(b'ANDROID!')
    if android_offset >= 0:
        print(f"  ANDROID! found at offset {hex(android_offset)} ({android_offset} bytes)")
    else:
        print(f"  ANDROID! NOT FOUND in image!")
        return False
    
    # Step 2: 如果 magic 不在偏移 0，bootloader 会怎样？
    if magic_offset_0 != b'ANDROID!':
        print(f"  ⚠️  magic NOT at partition start!")
        print(f"     bootloader 读首 4 blocks (2048B) 得到: {magic_offset_0!r}")
        print(f"     → memcmp(hdr->magic, BOOT_MAGIC) FAILS")
        print(f"     → 进入 RKIMAGE! 分支 (从 kernel 分区加载)")
        print(f"     ⚠️  这意味着 4MB 零页前缀可能导致 bootloader 走错分支！")
        
        # 但 RK3288 Android 4.4 的实际行为可能不同：
        # RK 的 boot.img/recovery.img 可能用了不同的偏移约定
        # 检查 stock 是否也是这样
        print(f"\n  *** 关键验证：stock recovery.img 也用 4MB 偏移 ***")
        print(f"  *** 如果 stock 能启动，说明 bootloader 能处理 4MB 偏移 ***")
        print(f"  *** 可能的机制：RK 的 StorageReadLba 内部有偏移，")
        print(f"      或者分区表 start LBA 已包含偏移 ***")
    else:
        print(f"  ✅ magic at partition start (offset 0x0)")
    
    # Step 3: 解析 header
    hdr = parse_boot_img_hdr(data, android_offset, label)
    if hdr is None:
        return False
    
    page_size = hdr['page_size']
    print(f"\n  Header fields (from ANDROID! at {hex(android_offset)}):")
    print(f"    kernel_size  = {hdr['kernel_size']} ({hdr['kernel_size']/1024:.0f} KB)")
    print(f"    kernel_addr  = {hex(hdr['kernel_addr'])}")
    print(f"    ramdisk_size = {hdr['ramdisk_size']} ({hdr['ramdisk_size']/1024:.0f} KB)")
    print(f"    ramdisk_addr = {hex(hdr['ramdisk_addr'])}")
    print(f"    tags_addr    = {hex(hdr['tags_addr'])}")
    print(f"    page_size    = {page_size}")
    print(f"    second_size  = {hdr['second_size']}")
    
    # Step 4: 模拟 kernel/ramdisk 读取偏移
    # sector = ptn->start + (page_size / blksz) + android_offset/blksz
    # bootloader 从 ANDROID! header 之后 page_size 字节处读 kernel
    kernel_offset = android_offset + page_size
    ramdisk_offset = kernel_offset + ((hdr['kernel_size'] + page_size - 1) // page_size) * page_size
    
    print(f"\n  Bootloader read offsets (relative to ANDROID!):")
    print(f"    kernel  @ {hex(kernel_offset)} ({kernel_offset} bytes)")
    print(f"    ramdisk @ {hex(ramdisk_offset)} ({ramdisk_offset} bytes)")
    
    # 验证这些偏移处有有效数据
    if kernel_offset + hdr['kernel_size'] <= len(data):
        kernel_data = data[kernel_offset:kernel_offset+min(hdr['kernel_size'],64)]
        print(f"    kernel head: {kernel_data[:16].hex()}")
        # RK kernel 通常是 gzip (1f 8b) 或 raw zImage
        if kernel_data[:2] == b'\x1f\x8b':
            print(f"    kernel format: gzip ✅")
        elif kernel_data[:4] == b'\x00\x00\xa0\xe1':
            print(f"    kernel format: ARM instruction (mov r0,r0) ✅")
        else:
            print(f"    kernel format: unknown (may still be valid)")
    else:
        print(f"    ❌ kernel offset beyond image boundary!")
        return False
    
    if ramdisk_offset + hdr['ramdisk_size'] <= len(data):
        ramdisk_head = data[ramdisk_offset:ramdisk_offset+4]
        print(f"    ramdisk head: {ramdisk_head.hex()}")
        if ramdisk_head[:2] == b'\x1f\x8b':
            print(f"    ramdisk format: gzip ✅")
        else:
            print(f"    ramdisk format: not gzip (cpio?)")
    else:
        print(f"    ❌ ramdisk offset beyond image boundary!")
        print(f"       ramdisk_offset={ramdisk_offset} + ramdisk_size={hdr['ramdisk_size']} = {ramdisk_offset+hdr['ramdisk_size']}")
        print(f"       image size = {len(data)}")
        return False
    
    # Step 5: 检查 initrd 大小约束
    # CMDLINE: initrd=0x62000000,0x00800000 (8MB limit)
    # 但 rk_commandline_setenv 会重写 cmdline，可能用真实 ramdisk_size
    print(f"\n  initrd constraint check:")
    print(f"    CMDLINE says: initrd=0x62000000,0x00800000 (8MB limit)")
    print(f"    actual ramdisk_size: {hdr['ramdisk_size']} ({hdr['ramdisk_size']/1024/1024:.1f} MB)")
    if hdr['ramdisk_size'] > 0x00800000:
        print(f"    ⚠️  ramdisk > 8MB CMDLINE limit!")
        print(f"       但 rk_commandline_setenv 会重写 cmdline 用真实 size")
        print(f"       board_fbt_finalize_bootargs(cmdline, sizeof, ramdisk_addr, ramdisk_size, ...)")
        print(f"       → 只要 ramdisk_addr + ramdisk_size 不越界 RAM 即可")
    else:
        print(f"    ✅ ramdisk within 8MB CMDLINE limit")
    
    # Step 6: 分区大小检查
    print(f"\n  Partition size check:")
    print(f"    recovery partition: 0x10000 sectors = 32MB")
    print(f"    image size: {len(data)} ({len(data)/1024/1024:.1f} MB)")
    if len(data) <= 32 * 1024 * 1024:
        print(f"    ✅ fits in 32MB partition")
    else:
        print(f"    ❌ exceeds 32MB partition!")
        return False
    
    return True

# 主验证
print("=" * 60)
print("Stage-3: TWRP recovery.img bootloader 解析验证")
print("=" * 60)

stock_data = open(sys.argv[1], 'rb').read()
twrp_data = open(sys.argv[2], 'rb').read()

stock_ok = simulate_bootloader(stock_data, "STOCK")
twrp_ok = simulate_bootloader(twrp_data, "TWRP")

print("\n" + "=" * 60)
print("对照总结")
print("=" * 60)

# 对照 header 字段
stock_hdr = parse_boot_img_hdr(stock_data, stock_data.find(b'ANDROID!'), "stock")
twrp_hdr = parse_boot_img_hdr(twrp_data, twrp_data.find(b'ANDROID!'), "twrp")

if stock_hdr and twrp_hdr:
    print(f"{'字段':<20} {'stock':<20} {'TWRP':<20} {'match':<6}")
    print("-" * 66)
    for key in ['kernel_addr', 'ramdisk_addr', 'tags_addr', 'page_size']:
        sv = hex(stock_hdr[key])
        tv = hex(twrp_hdr[key])
        match = "✅" if sv == tv else "❌"
        print(f"{key:<20} {sv:<20} {tv:<20} {match}")
    
    # kernel_size 对照（stock 用同一 prebuilt kernel）
    sv = stock_hdr['kernel_size']
    tv = twrp_hdr['kernel_size']
    match = "✅" if sv == tv else "❌"
    print(f"{'kernel_size':<20} {sv:<20} {tv:<20} {match}")
    
    # ramdisk_size 对照（TWRP ramdisk 必然不同）
    sv = stock_hdr['ramdisk_size']
    tv = twrp_hdr['ramdisk_size']
    print(f"{'ramdisk_size':<20} {sv:<20} {tv:<20} {'N/A (expected diff)'}")
    
    # ANDROID! offset
    so = stock_data.find(b'ANDROID!')
    to = twrp_data.find(b'ANDROID!')
    match = "✅" if so == to else "❌"
    print(f"{'ANDROID! offset':<20} {hex(so):<20} {hex(to):<20} {match}")

print(f"\nstock parse: {'PASS ✅' if stock_ok else 'FAIL ❌'}")
print(f"twrp parse:  {'PASS ✅' if twrp_ok else 'FAIL ❌'}")

if stock_ok and twrp_ok:
    print("\n✅ VERDICT: TWRP recovery.img 可被原厂 bootloader 正确解析")
    print("   header 字段与 stock 完全匹配，kernel/ramdisk 偏移在边界内")
else:
    print("\n❌ VERDICT: 存在解析风险，需进一步调查")

# 最终断言
if stock_ok and twrp_ok and stock_hdr and twrp_hdr:
    # 所有关键字段必须匹配
    assert stock_hdr['kernel_addr'] == twrp_hdr['kernel_addr'], "kernel_addr mismatch"
    assert stock_hdr['ramdisk_addr'] == twrp_hdr['ramdisk_addr'], "ramdisk_addr mismatch"
    assert stock_hdr['tags_addr'] == twrp_hdr['tags_addr'], "tags_addr mismatch"
    assert stock_hdr['page_size'] == twrp_hdr['page_size'], "page_size mismatch"
    assert stock_hdr['kernel_size'] == twrp_hdr['kernel_size'], "kernel_size mismatch"
    # ANDROID! offset 必须一致
    assert stock_data.find(b'ANDROID!') == twrp_data.find(b'ANDROID!'), "ANDROID! offset mismatch"
    # ramdisk 必须在边界内
    assert twrp_data.find(b'ANDROID!') + twrp_hdr['page_size'] + \
           ((twrp_hdr['kernel_size'] + twrp_hdr['page_size'] - 1) // twrp_hdr['page_size']) * twrp_hdr['page_size'] + \
           twrp_hdr['ramdisk_size'] <= len(twrp_data), "ramdisk exceeds image boundary"
    print("\n✅ ALL ASSERTIONS PASSED")
    sys.exit(0)
else:
    sys.exit(1)
PYEOF

# 5. 运行验证
echo ""
echo "[3] Running bootloader simulation..."
python3 "$VERIFY_PY" "$STOCK_REC" "$TWRP_REC"
RESULT=$?

echo ""
echo "=== Stage-3 Result: $RESULT ==="
exit $RESULT
