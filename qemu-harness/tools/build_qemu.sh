#!/bin/bash
set -euo pipefail
W=/data/workspace
cd $W
if [ ! -d repo/.git ]; then git clone --depth 1 https://github.com/Lieguch/Test_migu.git repo; else cd repo && git fetch --depth 1 origin main && git reset --hard FETCH_HEAD && cd $W; fi
cd $W/rk3288/qemu-src
cp $W/repo/qemu-harness/rk3288.c hw/arm/rk3288.c
grep -q CONFIG_RK3288 hw/arm/Kconfig || printf "\nconfig RK3288\n    bool\n    select A15MPCORE\n" >> hw/arm/Kconfig
python3 - <<PYEOF
p="hw/arm/meson.build"; s=open(p).read()
a="system_ss.add(when: 'CONFIG_VEXPRESS', if_true: files('vexpress.c'))"
assert a in s, "anchor missing"
if "rk3288.c" not in s:
    s=s.replace(a, a+"\n    system_ss.add(if_true: files('rk3288.c'))")
    open(p,"w").write(s)
    print("meson patched")
else:
    print("meson already has rk3288")
PYEOF
grep -q CONFIG_RK3288 configs/devices/arm-softmmu/default.mak || echo CONFIG_RK3288=y >> configs/devices/arm-softmmu/default.mak
./configure --target-list=arm-softmmu --disable-tools --disable-docs --disable-werror
ninja -C build -j4
./build/qemu-system-arm -machine help | grep -i rk3288
echo BUILD_DONE_OK
