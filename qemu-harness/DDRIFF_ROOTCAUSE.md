# t78 ddr_init NULL-pointer deref — 根因分析与补丁

## 现象（t78 boot.log）

| 行 | 内容 |
|---|---|
| 150-153 | `DDR DEBUG: addr=0xd18000 ...`（ddr_get_datatraing_addr 已执行） |
| 154 | `Unable to handle kernel NULL pointer dereference at virtual address 00000008` |
| 161 | `PC is at ddr_init.constprop.15+0x508/0x7dc` |
| 163 | `lr : [<00000000>]` |
| 167 | `r1 : 00000000` `r4 : 00000008` |
| 221-222 | `ddr_init+0x508` ← `rk3288_ddr_init+0x40` ← `do_one_initcall` |

## 根因

`ddr_init+0x508` 对应 `ddr_move_to_Access_state()` 中：

```c
register pDDR_REG_T pDDR_Reg = DATA(ddr_ch[ch]).pDDR_Reg;
...
value = pDDR_Reg->STAT.b.ctl_stat;   /* 读 pDDR_Reg + 0x8 */
```

`pDDR_Reg = pDDR_REG(0) = RK_DDR_VIRT`（内核 `arch/arm/mach-rockchip/ddr_rk32.c:781`）。

`RK_DDR_VIRT = RK_IO_ADDRESS(0x000d0000)`（`include/linux/rockchip/iomap.h:22`）。

在 QEMU 环境下 `RK_DDR_VIRT` 解析为 **0**（`RK_IO_ADDRESS(0x000d0000)` 无有效映射），导致 `pDDR_Reg = 0`，读 `0+0x8` → NULL-pointer deref → panic。

QEMU `rk3288.c` 的 DDR model 注册在 `RK3288_DDR_BASE = 0xff610000`（第 1036 行），而内核期望读 `RK_DDR_VIRT`（物理 `0x000d0000` 附近），两者地址不匹配，且 `0x000d0000` 落在 DRAM 区（读回 0），使 `pDDR_Reg` 指针为 0。

对比 t71（原厂内核 xierong 2018）可跑通 TWRP 主程序，t78（run13/twrp_zImage，runner 2026）在 `ddr_init` 即 panic —— 说明是**内核版本差异导致的 `RK_DDR_VIRT` 映射问题**，QEMU DDR model 未覆盖内核实际访问的地址。

## 补丁

### 补丁 1：QEMU `rk3288.c` —— 让 DDR model 在 `RK_DDR_VIRT` 的物理地址处也可读

在 `rk3288_init()` 中，除现有 `0xff610000` 外，追加在 `0x000d0000`（RK_DDR_VIRT 对应的物理地址）处注册同一套 DDR ops。这样内核读 `RK_DDR_VIRT` 可命中 DDR model，返回合理的 STAT/SCTL/PPCFG 值，避免 `pDDR_Reg` 为 0。

位置：`rk3288_init()` 内，`rk3288_add_io(sysmem, RK3288_DDR_BASE, ...)` 之后（~第 1036 行）。

```c
    /* RK_DDR_VIRT = RK_IO_ADDRESS(0x000d0000) -> 物理 0x000d0000。
     * 内核 ddr_init() 从 RK_DDR_VIRT 读 pDDR_Reg/pPHY_Reg，QEMU 若只在
     * 0xff610000 建 model，RK_DDR_VIRT 读回 0 -> pDDR_Reg 为 NULL ->
     * ddr_init+0x508 读 [0, #8] panic。在此处追加 model，覆盖内核访问地址。 */
    rk3288_add_io(sysmem, 0x000d0000ULL, RK3288_DDR_SIZE, &rk3288_ddr_ops, "rk3288-ddr-virt");
```

### 补丁 2：内核 `ddr_rk32.c` —— `ddr_init` 容错，pDDR_REG 为 0 时回退

在 `ddr_init()` 中，`p_ddr_ch[ch]->pDDR_Reg = pDDR_REG(ch);` 之后，若 `pDDR_REG(ch)` 为 0，回退到 QEMU DDR model 的物理地址 `0xff610000`。作为纵向防御，避免同类映射问题再次导致 panic。

位置：`arch/arm/mach-rockchip/ddr_rk32.c` `ddr_init()` 函数内（~第 4345 行）。

```c
        p_ddr_ch[ch]->pDDR_Reg = pDDR_REG(ch);
        p_ddr_ch[ch]->pPHY_Reg = pPHY_REG(ch);
        p_ddr_ch[ch]->pMSCH_Reg = pMSCH_REG(ch);

        /* QEMU 环境下 RK_DDR_VIRT 可能为 0，回退到 QEMU DDR model 地址 */
        if (!p_ddr_ch[ch]->pDDR_Reg) {
            p_ddr_ch[ch]->pDDR_Reg = (pDDR_REG_T)0xff610000ULL;
            p_ddr_ch[ch]->pPHY_Reg = (pDDRPHY_REG_T)(0xff610000ULL + RK3288_DDR_PCTL_SIZE);
            p_ddr_ch[ch]->pMSCH_Reg = (pMSCH_REG)0xffac0000ULL;
        }
```

## 验证准则（环境恢复后）

1. 重建 CNB 工作空间：`cnb workspace start-workspace --repo lieguch/rkpad --branch main`
2. 重新编译 QEMU（`build_qemu.sh` 修改 meson.build 让 rk3288.c 无条件编入）
3. 跑 t78 等效组合：`run13/zImage` + `twrp_ramdisk.gz`（真 TWRP ramdisk）
4. 预期：`ddr_init` 不再 panic，启动进入 initramfs，出现 `I: LANG: zh_CN` 等 TWRP 主程序日志，进而触发 Route B 的 5.2s ddrfreq DVFS panic（下一阶段攻克目标）。

## 当前状态汇总

- QEMU rk3288 机器：已注册并可启动（t74/t77/t78 均能过早期 boot）
- TWRP ramdisk：可解析并加载（twrp_new.img → twrp_ramdisk.gz）
- 阻塞点：`ddr_init` 在 `RK_DDR_VIRT` 映射为 0 时 panic，TWRP 主程序尚未进入
- 下一步：应用补丁 1 + 补丁 2，重建环境后验证