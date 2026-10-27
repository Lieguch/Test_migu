# Route A: vdd_logic backfill (act8846 dummy/固定电源)
# 目标：让显示上电，绕过 act8846 真实电源 IC 不可用导致的显示不上电问题

## 问题
TWRP 主程序进入后，LCDC0 显示控制需要 vdd_logic 电源上电。
act8846 PMU 在 QEMU 中未建模，vdd_logic 读取失败，导致显示保持黑屏。
t71 可跑通 TWRP 主程序，说明原厂内核对 act8846 有适配；t78 使用新内核，电源 IC 模型不匹配。

## 方案 A1：act8846 dummy 驱动（推荐）
在内核中添加一个 dummy act8846 驱动，固定返回 vdd_logic = 600mV（或 1200mV），不实际操作硬件。

位置：drivers/power/act8846.c 或 drivers/regulator/

关键代码：
```c
/* act8846 dummy regulator for QEMU */
static int act8846_dummy_get_voltage(struct regulator_dev *rdev)
{
    return 600000;  /* 固定 600mV */
}

static int act8846_dummy_set_voltage(struct regulator_dev *rdev, int min_uV, int max_uV, unsigned *selector)
{
    return 0;  /* 总是成功 */
}

static const struct regulator_ops act8846_dummy_ops = {
    .get_voltage = act8846_dummy_get_voltage,
    .set_voltage = act8846_dummy_set_voltage,
    .list_voltage = NULL,
};
```

注册一个固定的 regulator 节点 "vdd_logic"，电压固定为 600mV～1200mV 范围内任意值。

## 方案 A2：启用 act8846 但不启用 ddrfreq
在内核 defconfig 中启用 act8846 驱动，但不启用 DDR 变频（ddrfreq），避免 DDR PCTL 寄存器访问。

位置：arch/arm/configs/rk3288_defconfig 或对应设备树 dts

关键修改：
- CONFIG_REGULATOR_ACT8846=y
- 设备树中保留 act8846 节点，但移除 ddrfreq 相关节点
- 内核启动参数加入 `clk_ignore_unused cpufreq=disabled`

## 预期结果
显示电源上电，LCDC0 正常输出，TWRP UI 可见。

---

# Route B: DDR PCTL/PHY STAT/DLL-lock 位建模
# 目标：解除 5.2s ddrfreq panic halt

## 问题
t78 boot 在 5.2s 后因 ddrfreq 导致 panic halt。
内核 ddr_freq.c 走 CLK 框架 dvfs_clk_set_rate 改 DPLL/GPLL，随后访问 DDR PCTL(0xff610000)/PHY(0xff620000) 的 STAT/DLL-lock 位。
QEMU DDR model 仅模拟了部分寄存器，DLL-lock 位未就绪导致内核死等，最终 panic。

## 方案 B1：QEMU DDR model 增加 DLL-lock 位模拟
在 rk3288.c 的 rk3288_ddr_read 中，对 PHY 寄存器的 DLLSRST/DLLBYP/DLLLOCK 位返回“已就绪”值。

关键寄存器偏移（基于 rk32_rk32.c 上游源码）：
- PHY PUBL0 PGSR @ 0x004 (PGSR_DLDONE bit)
- PHY PUBL0 DXGSR @ 0x100 (DXGSR_DTERR/DXGSR_RVERR)

代码：
```c
/* PHY PUBL0 PGSR @ 0x004 */
if (offset == 0x004) {
    /* PGSR_DLDONE = bit 0，返回已锁定 */
    return PGSR_DLDONE;  /* 内核看到 DLL 已锁定，继续执行 */
}

/* PHY PUBL0 DXGSR @ 0x100 */
if (offset == 0x100) {
    return 0;  /* 无训练错误 */
}
```

## 方案 B2：内核 ddr_freq 容错
在 ddr_move_to_Access_state 或 ddr_freq 变频路径中，增加对 DLL-lock 的超时容错，不再等待无限循环。

位置：arch/arm/mach-rockchip/ddr_rk32.c ddr_move_to_Access_state()

## 预期结果
5.2s 后不再 panic halt，内核继续启动，进入 TWRP 主程序。

---

# ramdisk servicemanager 添加方案
# 目标：消除 binder transaction failed 29189 噪声

## 问题
ramdisk 缺失 servicemanager 二进制，binder 通信失败，反复输出 "binder: transaction failed 29189" 噪声。

## 方案
1. 从 Android 4.4/5.1 源码树提取 servicemanager 二进制（arm32 静态编译或动态链接版本）
2. 使用 patch_ramdisk4.py 将 servicemanager 添加到 ramdisk 的 /system/bin/ 或 /sbin/
3. 确保 init.recovery.service.rc 中有 servicemanager 启动服务

代码：
```bash
# patch_ramdisk4.py --add servicemanager /system/bin/servicemanager 0755
# init.recovery.service.rc 追加：
service servicemanager /system/bin/servicemanager
    class main
    user system
    group system
```

## 预期结果
binder 噪声消失，TWRP 内部 binder 通信正常。
