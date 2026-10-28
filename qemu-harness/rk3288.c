/*
 * hw/arm/rk3288.c — minimal Rockchip RK3288 machine model (P817 milestone 2)
 * =============================================================================
 * Purpose: make the P817 board-level boot path observable WITH LOGS.
 * (The real device produces none: console=ttyFIQ0, no UART access.)
 *
 * EVERY address below is MEASURED from the P817 DTB (resource.img → p817.dts)
 * or from QEMU v10.0.1 source — never from memory:
 *
 *   CPUs   : 4x "arm,cortex-a15"                     (p817.dts cpus node)
 *   CBAR   : 0xffc00000  → a15mpcore_priv puts the GIC distributor at
 *                          +0x1000 = 0xffc01000 and the GIC CPU interface at
 *                          +0x2000 = 0xffc02000, which is EXACTLY the DTB's
 *                          interrupt-controller@ffc01000
 *                          reg = <0xffc01000 0x1000 0xffc02000 0x1000>
 *                          (layout confirmed in hw/cpu/a15mpcore.c:125-136)
 *   Timer  : arm,armv7-timer, clock-frequency 24000000 (DTB timer node)
 *   UARTs  : 0xff180000 / 0xff190000 / 0xff690000 / 0xff1b0000 / 0xff1c0000,
 *            each reg 0x100, reg-shift=2, reg-io-width=4, clock 24MHz
 *            (DTB serial nodes; serial2 = ff690000 is the device's real
 *             console port — fiq-debugger rockchip,serial-id = 2)
 *   DRAM   : base 0x00000000 (P817 evidence: logo buffer at 0xfbc00000)
 *
 * Deliberately NOT modelled (unassigned reads return 0, writes are dropped):
 *   CRU / PMU / GRF / pinctrl / emmc / sdio / lcdc / hdmi / i2c / spi /
 *   saradc / gpu / vpu / ...
 *   The kernel probes them and reports failures in the boot log — that IS the
 *   experiment: we want to see how far the board boot gets and where it stops.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "hw/sysbus.h"
#include "hw/irq.h"
#include "hw/arm/boot.h"
#include "hw/boards.h"
#include "hw/cpu/a15mpcore.h"
#include "hw/loader.h"
#include "hw/qdev-properties-system.h"
#include "hw/qdev-properties.h"
#include "chardev/char-fe.h"
#include "hw/misc/unimp.h"
#include "qemu/error-report.h"
#include "system/system.h"

/* ------------------------------------------------------------------------- */
/* Minimal RK UART: DW-apb-uart register file, 4-byte stride (DTB reg-shift 2).*/
/* Only the three registers the two in-tree console producers actually poll   */
/* are given non-zero answers; everything else reads 0 and writes are dropped */
/* (except THR, which is the one that emits console bytes):                    */
/*   USR @ +0x7c -> 0x02   (rk_fiq_debugger.c:115 TFNF, rk_serial.c:355 BUSY) */
/*   LSR @ +0x14 -> 0x60   (THRE|TEMT, both "transmitter ready" waits)        */
/*   TFL @ +0x80 -> 0      (rk_serial.c:914 "transmit FIFO level")            */
/*   THR @ +0x00 <- write  => forwarded to the chardev (this is the console)  */
/* IRQs are wired but never raised: both producers poll, so no interrupt-     */
/* driven path is needed to get a boot log.                                   */
/* ------------------------------------------------------------------------- */

#define TYPE_RK3288_UART "rk3288-uart"
OBJECT_DECLARE_SIMPLE_TYPE(RK3288UartState, RK3288_UART)

struct RK3288UartState {
    SysBusDevice parent_obj;
    MemoryRegion iomem;
    qemu_irq irq;
    uint8_t dll, dlm;   /* divisor latch (DLAB = 1) */
    uint8_t ier;
    uint8_t lcr;
    uint8_t fcr;
    uint8_t scr;
    CharBackend chr;
};

static uint64_t rk3288_uart_read(void *opaque, hwaddr off, unsigned size)
{
    RK3288UartState *s = RK3288_UART(opaque);
    unsigned reg = off >> 2;   /* reg-shift = 2, measured from the DTB */

    switch (reg) {
    case 0:  /* RBR (no RX data) or DLL */
        return (s->lcr & 0x80) ? s->dll : 0;
    case 1:  /* IER or DLM */
        return (s->lcr & 0x80) ? s->dlm : s->ier;
    case 2:  /* IIR: no interrupt pending (TX path is polled via LSR) */
        return 0x01;
    case 3:  /* LCR */
        return s->lcr;
    case 4:  /* MCR */
        return 0;
    case 5:  /* LSR: THRE | TEMT always set => transmitter always ready */
        return 0x60;
    case 6:  /* MSR */
        return 0;
    case 7:  /* SCR */
        return s->scr;
    case 0x1F:
        /* USR (DesignWare "UART Status Register"), phys offset 0x7c.
         *
         * MEASURED from THIS tree, not from memory:
         *   arch/arm/mach-rockchip/rk_fiq_debugger.c:111-117
         *     debug_putc(): while (!(rk_fiq_read(t, 0x1F) & 0x02)) cpu_relax();
         *   rk_fiq_read(t, off) == __raw_readl(base + off*4)  => phys +0x7c
         *   bit1 = TFNF (transmit FIFO not full) — the wait condition.
         *   drivers/tty/serial/rk_serial.c:81-82
         *     #define UART_USR 0x1F ; #define UART_USR_BUSY (1)
         *   and :355 / :375
         *     while (serial_in(up, UART_USR) & UART_USR_BUSY) timeout 15000
         *   => bit0 must read 0 ("not busy"), bit1 must read 1 ("fifo not full").
         *
         * Run#5 (2026-10-19) measured the guest spinning at 0xc0023e6c..7c
         * (tst r0,#2 / b -24) with 0 bytes of serial output: this register
         * read back 0 and the console path could never make progress.
         * 0x02 = TFNF set, BUSY/RFNE clear (no RX data available). */
        return 0x02;
    case 0x20:
        /* TFL (transmit FIFO level), phys offset 0x80.
         * rk_serial.c:914  count = up->port.fifosize - serial_in(up, 0x20);
         * 0 => "FIFO empty" => the whole fifosize is free. */
        return 0;
    default:
        return 0;
    }
}

static void rk3288_uart_write(void *opaque, hwaddr off, uint64_t val,
                              unsigned size)
{
    RK3288UartState *s = RK3288_UART(opaque);
    unsigned reg = off >> 2;

    switch (reg) {
    case 0:  /* THR or DLL */
        if (s->lcr & 0x80) {
            s->dll = val;
        } else {
            uint8_t c = val;
            qemu_chr_fe_write_all(&s->chr, &c, 1);
        }
        break;
    case 1:  /* IER or DLM */
        if (s->lcr & 0x80) {
            s->dlm = val;
        } else {
            s->ier = val;
        }
        break;
    case 2:  /* FCR */
        s->fcr = val;
        break;
    case 3:  /* LCR */
        s->lcr = val;
        break;
    case 7:  /* SCR */
        s->scr = val;
        break;
    default:
        break;
    }
}

static const MemoryRegionOps rk3288_uart_ops = {
    .read = rk3288_uart_read,
    .write = rk3288_uart_write,
    .valid.min_access_size = 1,
    .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

static void rk3288_uart_realize(DeviceState *dev, Error **errp)
{
    RK3288UartState *s = RK3288_UART(dev);

    memory_region_init_io(&s->iomem, OBJECT(dev), &rk3288_uart_ops, s,
                          "rk3288-uart", 0x100);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->iomem);
    sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->irq);
}

static const Property rk3288_uart_properties[] = {
    DEFINE_PROP_CHR("chardev", RK3288UartState, chr),
};

static void rk3288_uart_class_init(ObjectClass *oc, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);

    dc->realize = rk3288_uart_realize;
    device_class_set_props(dc, rk3288_uart_properties);
}

static const TypeInfo rk3288_uart_info = {
    .name          = TYPE_RK3288_UART,
    .parent        = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(RK3288UartState),
    .class_init    = rk3288_uart_class_init,
};


/* -------------------------------------------------------------------------
 * RK3288 peripheral window: ONE catch-all region, not an enumerated table.
 *
 * WHY (measured, 2026-10-20, rk3288_board_boot.log):
 *   A guest that touches a physical range with NO backing MemoryRegion does
 *   not read 0 — QEMU raises an *external data abort*.  So every driver that
 *   probes a block we do not model oopses.  Worse, the oops handler's
 *   show_data() re-reads the faulting address to dump it, faults again, and
 *   recurses: one missing block produced 12 cascading "Internal error" dumps
 *   (log lines 131..878), first fault
 *       PC is at rockchip_pinctrl_probe+0x6c8/0xbd0   at 0xf0112030
 *   Enumerating ranges one abort at a time is a patch stack, not a fix.
 *
 * ROOT FIX: back the whole 0xff000000-0xffffffff RK peripheral window once,
 * at priority -1000, with read-0 / write-drop.  Blocks we model for real
 * (GIC/mpcore, the 5 UARTs, CRU, GRF) are added at the default priority 0
 * and shadow it, so specificity still wins.  Nothing can abort afterwards.
 *
 * Each 4K page is logged once on first touch: that list IS the audit trail
 * of "which blocks this harness fakes" for the boot-log report.
 * ------------------------------------------------------------------------- */
#define RK3288_PERIPH_WIN_BASE 0xff000000ULL
#define RK3288_PERIPH_WIN_SIZE 0x01000000ULL

#define RK3288_WIN_NPAGES (RK3288_PERIPH_WIN_SIZE / 0x1000)
static uint8_t rk3288_win_seen[RK3288_WIN_NPAGES / 8];

static uint64_t rk3288_catchall_read(void *opaque, hwaddr off, unsigned size)
{
    unsigned page = off / 0x1000;

    if (page < RK3288_WIN_NPAGES &&
        !(rk3288_win_seen[page / 8] & (1u << (page % 8)))) {
        rk3288_win_seen[page / 8] |= 1u << (page % 8);
        fprintf(stderr,
                "[rk3288-ca] read  phys 0x%08llx (unmodelled block)\n",
                (unsigned long long)(RK3288_PERIPH_WIN_BASE + off));
    }
    return 0;
}

static void rk3288_catchall_write(void *opaque, hwaddr off, uint64_t val,
                                  unsigned size)
{
    /* dropped */
}

static const MemoryRegionOps rk3288_catchall_ops = {
    .read = rk3288_catchall_read,
    .write = rk3288_catchall_write,
    .valid.min_access_size = 1,
    .valid.max_access_size = 8,
    .endianness = DEVICE_NATIVE_ENDIAN,
};


/* -------------------------------------------------------------------------
 * Minimal CRU (clock & reset unit) at 0xff750000.
 *
 * MEASURED 2026-10-19 (run after backing all other register ranges): the
 * kernel reached the clock driver and spun in pll_wait_lock() forever,
 * because the PLL lock bit never sets when the CRU reads back 0
 * (trace: __clk_get_name -> pll_wait_lock -> memcpy -> pll_wait_lock ...).
 * The lock bits are bit 31 of each PLL con register, so a CRU that reads
 * back all-ones makes every PLL "already locked" and lets the clock
 * driver finish. Writes are dropped (no clock tree to reconfigure).
 * ------------------------------------------------------------------------- */
#define RK3288_CRU_BASE 0xff750000ULL
#define RK3288_CRU_SIZE 0x00001000ULL
#define RK3288_GRF_BASE 0xff770000ULL
#define RK3288_GRF_SIZE 0x00001000ULL

/* A region whose reads answer 0xFFFFFFFF (every lock/status bit set) and
 * whose writes are dropped.  Used for CRU + GRF so that the RK clock
 * driver's pll_wait_lock() polling completes instead of deadlocking. */
static uint64_t rk3288_allones_read(void *opaque, hwaddr off, unsigned size)
{
    return 0xFFFFFFFF;
}

static void rk3288_allones_write(void *opaque, hwaddr off, uint64_t val,
                                 unsigned size)
{
    /* dropped */
}

static const MemoryRegionOps rk3288_allones_ops = {
    .read = rk3288_allones_read,
    .write = rk3288_allones_write,
    .valid.min_access_size = 1,
    .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

static void rk3288_add_allones(MemoryRegion *sysmem, hwaddr base,
                               hwaddr size, const char *name)
{
    MemoryRegion *r = g_new(MemoryRegion, 1);
    memory_region_init_io(r, NULL, &rk3288_allones_ops, NULL, name, size);
    memory_region_add_subregion(sysmem, base, r);
}


/* =========================================================================
 * DDR / PMU / SGRF / MSCH — the block that makes ddr_init() finish.
 *
 * WHY THIS EXISTS (measured 2026-10-20): every recovery image — including the
 * FACTORY one that boots fine on the device — dies at 0.51 s inside
 * ddr_get_datatraing_addr(), ldr r0,[r7,#0xc] (= p_ddr_ch[ch]->pMSCH_Reg),
 * ldr r7,[r0,#8] with r0 == 0.  The RK DDR glue then never prints
 * "DDR DEBUG: init success!!!" and userspace never starts.
 *
 * EVERY CONSTANT BELOW IS DERIVED, NOT GUESSED. Two sources:
 *   (a) kernel source  arch/arm/mach-rockchip/ddr_rk32.c  (offsets + bitfields)
 *   (b) the DEVICE'S OWN boot log  /proc/last_kmsg  (the values it printed)
 *       — archived at work/device_live2/last_kmsg_20261020.txt
 *
 * (b) printed, on real hardware:
 *     Channel a/b: DDR3  Bus Width=32 Col=10 Bank=8 Row=15 CS=2  2048MB
 *     stride=13, size=256, halfcap=80000000
 *     socAddr[0]=0xcd3000 socAddr[1]=0xcd3100
 *     dtar[0]=dtar[1]=0x3019a000
 *     init success!!! freq=200MHz
 *
 * DERIVATION 1 — PMU_PMU_SYS_REG[2] (= PMU + 0x9c, one register carries all
 * of it; offsets from the PMU_FILE struct). Bit layouts:
 *   READ_CH_INFO  = (v>>28)&3      -> 0x3   both channels populated
 *   READ_CH_CNT   = 1+((v>>12)&1)  -> 2
 *   READ_CS_INFO  = ((v>>(11+ch*16))&1)+1        -> CS=2
 *   READ_BW_INFO  = 2>>((v>>(2+ch*16))&3)        -> 2  (=> "Bus Width=32")
 *   READ_COL_INFO = 9+((v>>(9+ch*16))&3)         -> 10
 *   READ_BK_INFO  = 3-((v>>(8+ch*16))&1)         -> 3  (=> 8 banks)
 *   READ_ROW_INFO = 13+((v>>(6-2*cs+ch*16))&3)   -> 15
 *   CH_ROW_INFO   = (v>>(30+ch))&1               -> 0
 * Solving those gives exactly 0x3AA01AA0, and that value reproduces the
 * printed line "Bus Width=32 Col=10 Bank=8 Row=15 CS=2 ... 2048MB".
 *
 * DERIVATION 2 — READ_DDR_STRIDE() = readl(RK_SGRF_VIRT+8) & 0x1F  -> 13
 *   gStrideInfo[13] = {size=0x100, halfCap=0x80000000} which is exactly the
 *   "stride=13, size=256, halfcap=80000000" the device printed.
 *
 * DERIVATION 3 — MSCH.ddrconf (MSCH_REG: coreid, revid, ddrconf @ +8) -> 3
 *   ddr_cfg_2_rbc[3] = (0<<7)|(3<<4)|(3<<2)|1 = 0x3D  => col 9+1=10,
 *   row 12+3=15, and (rbc>>2)&3 = 3  /  (rbc>>7)&3 = 0.
 *   Plugging into ddr_get_datatraing_addr with addr=0xcd3000 (what the device
 *   printed) yields col=0, row=0x19A<<12, bank=3<<28  =>  0x3019A000.
 *   i.e. this single value is what turns the printed soffAddr/socAddr into
 *   the printed dtar — verified arithmetically, not assumed.
 *
 * PHY readbacks (PUBL) come straight from the device's own printout:
 *   PGSR        = IDONE|DLDONE|ZCDONE|DIDONE|DTDONE = 0x1F  (all "done")
 *   DCR         = 0xB   (DDRMD=3 "DDR3" + DDR8BNK)  -> the "DDR3 Device" line
 *   DATX8[i].DXGSR[0] = DTONE 0x3, DTERR 0, DTIERR 0, DTPASS 4,4
 *   DATX8[i].DXDQSTR  = DGSL 1,1 + DGPS 180,180
 *   ZQ0SR[0]    = DRV 0x19/0x19 + ODT 0x2/0x2 ; ZQ0SR[1] = 0 (no ZERR/ZPULL)
 * PCTL:
 *   STAT (@8)  ctl_stat = 3 = Access  -> ddr_move_to_Access_state() returns
 *   PPCFG(@0x84) bit0 = 1             -> both byte lanes present
 *
 * Anything not listed reads 0, and every 4-byte word touched is logged once
 * (see rk3288_ddr_read) — so the next oracle run tells us which offsets the
 * kernel actually needs instead of us inventing them.
 * ========================================================================= */

#define RK3288_PMU_BASE   0xff730000ULL
#define RK3288_SGRF_BASE  0xff740000ULL   /* RK3288_SGRF_PHYS */
#define RK3288_SGRF_ALT   0xff771000ULL   /* RK_SGRF_VIRT == RK_GRF_VIRT+0x1000 */
#define RK3288_MSCH_BASE  0xffac0000ULL   /* RK3288_SERVICE_BUS_PHYS, ch b +0x80 */
#define RK3288_DDR_BASE   0xff610000ULL   /* PCTL0; PUBL0 +0x1000; PCTL1 +0x2000; PUBL1 +0x3000 */
#define RK3288_DDR_SIZE   0x00004000ULL
/* RK_DDR_VIRT = RK_IO_ADDRESS(0x000d0000) -> 物理 0x000d0000。
 * 内核 ddr_init() 从 RK_DDR_VIRT 读 pDDR_Reg/pPHY_Reg，
 * QEMU 若只在 0xff610000 建 model，RK_DDR_VIRT 解析为 0 -> pDDR_Reg = NULL -> panic。
 * 在 0x000d0000 处也注册同一套 DDR ops，使内核读 RK_DDR_VIRT 可命中 DDR model。 */
#define RK3288_DDR_VIRT_BASE 0x000d0000ULL

#define RK3288_PMU_SYS2     0x3AA01AA0u
#define RK3288_DDR_STRIDE_V 13u
#define RK3288_DDR_CONF_V   3u

/* -------------------------------------------------------------------------
 * SRAM @ 0xff710000 — MUST be writable RAM, not read-0/write-drop.
 *
 * Measured 2026-10-20: the P817 DTB carries
 *     sram@ff710000 { compatible = "mmio-sram"; reg = <0xff710000 0x8000>; map-exec; };
 *     rockchip,sram = <0x01>;            (machine node)
 * and ddr_init() starts with
 *     c0747edc  ldr r0,[r5]        ; r0 = rockchip_pie_chunk
 *     c0747ee0  bl  __kern_to_pie
 * i.e. every per-channel struct pointer (pDDR_Reg/pPHY_Reg/pMSCH_Reg, which the
 * disassembly proves are compile-time constants 0xfedd0000.. / 0xfed74000) is
 * relocated through the PIE chunk. rk3288_pie_init() -> pie_load_sections()
 * COPIES the PIE code+data section into this SRAM. With the catch-all region
 * (read 0 / write dropped) that copy silently evaporates: the chunk contents
 * read back as 0, p_ddr_ch[ch] points at garbage, the store of pPHY_Reg lands
 * elsewhere, and the later load yields 0 -> fault at 0x30 (= DCR offset).
 * So this block must behave like real SRAM: writes retained, reads return them.
 * ------------------------------------------------------------------------- */
#define RK3288_SRAM_BASE    0xff710000ULL
#define RK3288_SRAM_SIZE    0x00008000ULL   /* DTB: reg = <0xff710000 0x8000> */
#define RK3288_BOOTRAM_BASE 0xff720000ULL
#define RK3288_BOOTRAM_SIZE 0x00001000ULL   /* iomap.h: RK3288_BOOTRAM_SIZE */

/* one-shot per-word hit log, per region: tells us what the guest really needs */
#define RK3288_LOG_WORDS 0x4000
static uint8_t rk3288_hit[4][RK3288_LOG_WORDS / 32];

static void rk3288_hit_note(int region, hwaddr off, const char *who, uint32_t val)
{
    unsigned w = (off >> 2) & (RK3288_LOG_WORDS - 1);

    if (!(rk3288_hit[region][w / 8] & (1u << (w % 8)))) {
        rk3288_hit[region][w / 8] |= 1u << (w % 8);
        fprintf(stderr, "[rk3288-%s] read +0x%04llx -> 0x%08x\n",
                who, (unsigned long long)off, val);
    }
}

/* =========================================================================
 * RK3x I2C + ACT8846 PMIC —— 让 act8846 的 regulator 注册上。
 *
 * 证据（runs/p2..p5/boot.log）：
 *   i2c-0..5 probe 成功；act8846_i2c_probe；act8846 set 0xf4 error!
 *   act8846: probe of 0-005a failed with error -110（模型前）/ -11（模型后）
 * 语义全部取自树内驱动 drivers/i2c/busses/i2c-rk30-adapter.c：
 *
 * 寄存器：CON 0x000(EN b0 / MOD b2:1 / START b3 / STOP b4)
 *         CLKDIV 0x004 | MRXADDR 0x008 | MRXRADDR 0x00c
 *         MTXCNT 0x010 | MRXCNT 0x014 | IEN 0x018 | IPD 0x01c | FCNT 0x020
 *         TXDATA 0x100+i*4 | RXDATA 0x200+i*4     （每字打包 4 字节，见驱动
 *         rk30_irq_read_get_data：word = RXDATA[i/4]，byte = word>>((i%4)*8)）
 *
 * ★ 状态机（rk30_i2c_irq_nextblock）——这是上一轮 -EAGAIN 的根因：
 *   1) 驱动置 CON=EN|MOD|START，只等 START 中断；
 *   2) 中断里清 STARTIPD，然后把 IEN 切成 MBTF/MBRF，**再去写 TXDATA+MTXCNT /
 *      MRXCNT** —— 也就是说传输数据是在 START 中断之后才写的。
 *   所以模型不能在 START 时就做传输，必须：START -> 只置 STARTIPD；
 *   写 MTXCNT/MRXCNT 时才真正搬数据并置 MBTFIPD/MBRFIPD；写 CON.STOP 置 STOPIPD。
 *
 * ★ 地址语义：TX 时从机地址是**第一个数据字节**（(addr&0x7f)<<1）；
 *   RX 时在 MRXADDR 里，形如 (addr<<1)|1 —— 取地址必须 >>1，不能 &0x7f。
 *   MRXRADDR 带 bit24..26 的 valid 标志，寄存器号取低 8 位。
 * ========================================================================= */

#define RK3288_I2C_NR 6
static const hwaddr rk3288_i2c_base[RK3288_I2C_NR] = {
    0xff650000, 0xff140000, 0xff660000, 0xff150000, 0xff160000, 0xff170000
};
static const int rk3288_i2c_irq[RK3288_I2C_NR] = { 0x3c, 0x3e, 0x3d, 0x3f, 0x40, 0x41 };

#define ACT8846_ADDR 0x5a
/* ---- Goodix GTP touch (i2c 0x5d, 16-bit register addressing) ------------
 * 目的：让 gt9xx 驱动 probe 成功 -> 注册 /dev/input/eventX（触摸屏）。
 * 设备真实输入只有触摸屏（用户 2026-10-28 明确），所以 harness 必须建模它。
 * 当前仅实现"静态应答"：product id / config version / 状态寄存器。
 * 触摸事件注入（需要 gpio7 EINT -> GIC 0x58）为下一步。
 */
#define GTP_ADDR 0x5d
static uint16_t gtp_ptr;
static uint8_t  gtp_cfg[192];

static void gtp_reset(void)
{
    memset(gtp_cfg, 0, sizeof(gtp_cfg));
    gtp_cfg[0] = 0x43;          /* 0x8047: config version */
    gtp_ptr = 0;
}

static uint8_t gtp_read_reg(uint16_t reg)
{
    if (reg >= 0x8047 && reg < 0x8047 + sizeof(gtp_cfg)) {
        return gtp_cfg[reg - 0x8047];
    }
    switch (reg) {
    case 0x8140: return '9';    /* product id "911" */
    case 0x8141: return '1';
    case 0x8142: return '1';
    case 0x8143: return 0;
    case 0x8144: return 0x02;   /* firmware version */
    case 0x8145: return 0x04;
    case 0x8146: return 0x00;   /* x协调 resolution 低字节 */
    case 0x8147: return 0x08;
    case 0x8148: return 0xB0;   /* y resolution 0x04B0 = 1200 */
    case 0x8149: return 0x04;
    case 0x41E4: return 0xBE;   /* ★ 固件校验：驱动要求 ==0xBE，否则
                                 * "Firmware error, no config sent!" 直接返回 -1 */
    case 0x814A: return 0x00;   /* ★ sensor_id：驱动要求 < 6，否则
                                 * "Invalid sensor_id, No Config Sent!" */
    case 0x814E: return 0x00;   /* buffer status: 无触摸数据 */
    default:     return 0;
    }
}

#define I2C_IPD_NAKRCV (1u << 6)
#define I2C_IPD_STOP   (1u << 5)
#define I2C_IPD_START  (1u << 4)
#define I2C_IPD_MBRF   (1u << 3)
#define I2C_IPD_MBTF   (1u << 2)

typedef struct RK3288I2C {
    uint32_t con, clkdiv, mrxaddr, mrxraddr, mtxcnt, mrxcnt, ien, ipd, fcnt;
    uint32_t txw[64], rxw[64];      /* 4 字节打包成一个 32 位字；GTP 配置写 186+ 字节 */
    uint8_t  cur_addr;              /* 当前从机地址（分块续传时后续块不带地址） */
    qemu_irq irq;
} RK3288I2C;

static RK3288I2C rk3288_i2c[RK3288_I2C_NR];
static uint8_t act8846_regs[256];
static uint8_t act8846_ptr;

static void act8846_reset(void)
{
    memset(act8846_regs, 0, sizeof(act8846_regs));
    act8846_ptr = 0;
}

static uint8_t i2c_tx_byte(RK3288I2C *s, unsigned i)
{
    return (s->txw[i / 4] >> ((i % 4) * 8)) & 0xff;
}

static void i2c_set_rx_byte(RK3288I2C *s, unsigned i, uint8_t v)
{
    unsigned sh = (i % 4) * 8;

    s->rxw[i / 4] = (s->rxw[i / 4] & ~(0xffu << sh)) | ((uint32_t)v << sh);
}

static void rk3288_i2c_upd(RK3288I2C *s)
{
    /* 只保留"被使能"的事件位：未使能的位既不该拉中断，也不该长期挂着 */
    s->ipd &= 0x7f;
    if ((s->ipd & s->ien & 0x7f) != 0) {
        qemu_irq_raise(s->irq);
    } else {
        qemu_irq_lower(s->irq);
    }
}

/* 写阶段：tx[0] = (addr<<1)，tx[1] = 寄存器号，tx[2..] = 数据 */
static void rk3288_i2c_do_tx(RK3288I2C *s)
{
    unsigned n = s->mtxcnt, i, addr;

    if (n == 0 || n > 256) {
        return;
    }
    {
        uint8_t b0 = i2c_tx_byte(s, 0);

        if (b0 == (ACT8846_ADDR << 1) || b0 == (GTP_ADDR << 1)) {
            addr = (b0 >> 1) & 0x7f;
            s->cur_addr = (uint8_t)addr;
        } else {
            /* ★ 长写会被控制器分块，后续块只有数据、没有地址字节 */
            addr = s->cur_addr;
        }
    }
    fprintf(stderr, "[i2c] TX addr=%02x n=%u b0=%02x\n", addr, n, i2c_tx_byte(s, 0));
    if (addr == GTP_ADDR) {
        fprintf(stderr, "[gtp] W n=%u b1=%02x b2=%02x\n", n,
                n > 1 ? i2c_tx_byte(s, 1) : 0, n > 2 ? i2c_tx_byte(s, 2) : 0);
        /* GTP：tx[1..2] = 16 位寄存器号，tx[3..] = 数据 */
        unsigned off = (i2c_tx_byte(s, 0) == (GTP_ADDR << 1)) ? 1 : 0;
        if (n >= off + 2) {
            gtp_ptr = ((uint16_t)i2c_tx_byte(s, off) << 8) |
                      i2c_tx_byte(s, off + 1);
        }
        for (i = off + 2; i < n; i++) {
            uint16_t r = gtp_ptr + (uint16_t)(i - 3);
            if (r >= 0x8047 && r < 0x8047 + sizeof(gtp_cfg)) {
                gtp_cfg[r - 0x8047] = i2c_tx_byte(s, i);
            }
        }
        gtp_ptr = (uint16_t)(gtp_ptr + (n > off + 2 ? n - off - 2 : 0));
        s->ipd |= I2C_IPD_MBTF;
        return;
    }
    if (addr != ACT8846_ADDR) {
        s->ipd |= I2C_IPD_NAKRCV;
        return;
    }
    {
        unsigned off = (i2c_tx_byte(s, 0) == (ACT8846_ADDR << 1)) ? 1 : 0;

        if (n > off) {
            act8846_ptr = i2c_tx_byte(s, off);
        }
        for (i = off + 1; i < n; i++) {
            act8846_regs[(act8846_ptr + i - off - 1) & 0xff] = i2c_tx_byte(s, i);
        }
        s->ipd |= I2C_IPD_MBTF;
        return;
    }
    for (i = 2; i < n; i++) {
        act8846_regs[(act8846_ptr + i - 2) & 0xff] = i2c_tx_byte(s, i);
    }
    s->ipd |= I2C_IPD_MBTF;
}

/* 读阶段：地址来自 MRXADDR（(addr<<1)|1），寄存器号来自 MRXRADDR 低 8 位 */
static void rk3288_i2c_do_rx(RK3288I2C *s)
{
    unsigned n = s->mrxcnt, i, addr, mode, base;

    if (n == 0 || n > 256) {
        return;
    }
    addr = (s->mrxaddr >> 1) & 0x7f;
    fprintf(stderr, "[i2c] RX addr=%02x n=%u mode=%u mrxraddr=%08x con=%08x\n", addr, n, (s->con >> 1) & 3, s->mrxraddr, s->con);
    if (addr == GTP_ADDR) {
        /* ★ 实测：gt9xx 在 rockchip i2c 上走 mode=1，寄存器号放在 MRXRADDR：
         *   0x0300e441 -> 字节 41 e4 00 03 -> 寄存器 0x41E4（低字节是高位）
         *   0x03004780 -> 0x8047 ；0x03004081 -> 0x8140
         * 之前用 gtp_ptr（来自 TX）永远为 0，所以读到 0x0000 -> 固件校验失败。 */
        uint16_t base16 = (uint16_t)(((s->mrxraddr & 0xff) << 8) |
                                     ((s->mrxraddr >> 8) & 0xff));
        for (i = 0; i < n; i++) {
            i2c_set_rx_byte(s, i, gtp_read_reg((uint16_t)(base16 + i)));
        }
        gtp_ptr = (uint16_t)(base16 + n);
        s->ipd |= I2C_IPD_MBRF;
        return;
    }
    if (addr != ACT8846_ADDR) {
        s->ipd |= I2C_IPD_NAKRCV;
        return;
    }
    mode = (s->con >> 1) & 3;
    base = (mode == 1 || mode == 3) ? (s->mrxraddr & 0xff) : act8846_ptr;
    for (i = 0; i < n; i++) {
        i2c_set_rx_byte(s, i, act8846_regs[(base + i) & 0xff]);
    }
    act8846_ptr = (base + n) & 0xff;
    s->ipd |= I2C_IPD_MBRF;
}

static uint64_t rk3288_i2c_read(void *opaque, hwaddr off, unsigned size)
{
    RK3288I2C *s = opaque;

    if (off >= 0x200 && off < 0x300) {
        return s->rxw[(off - 0x200) / 4];
    }
    if (off >= 0x100 && off < 0x200) {
        return s->txw[(off - 0x100) / 4];
    }
    switch (off) {
    case 0x000: return s->con;
    case 0x004: return s->clkdiv;
    case 0x008: return s->mrxaddr;
    case 0x00c: return s->mrxraddr;
    case 0x010: return s->mtxcnt;
    case 0x014: return s->mrxcnt;
    case 0x018: return s->ien;
    case 0x01c: return s->ipd;
    case 0x020: return s->fcnt;
    default:    return 0;
    }
}

static void rk3288_i2c_write(void *opaque, hwaddr off, uint64_t val, unsigned size)
{
    RK3288I2C *s = opaque;

    if (off >= 0x100 && off < 0x200) {
        s->txw[(off - 0x100) / 4] = val;
        return;
    }
    switch (off) {
    case 0x000:
        s->con = val;
        if (val & 1) {
            if (val & (1u << 3)) {          /* START：只报事件，不做传输 */
                s->ipd |= I2C_IPD_START;
                s->con &= ~(1u << 3);
                rk3288_i2c_upd(s);
            }
            /* STOP 完成事件：t13/t16/t18/t19/t22 的 STOPIPD 不置语义（t54 回退验证）。
             * STOPIPD 置位版（t28，备份于 rk3288_stopipd_t28.c.bak）虽让 act8846
             * probe 成功，但 STOPIPD 置 + mkdtb 会走到 kernel_init 的
             * execve("/sbin/modprobe") -> ENOENT -> kthread do_exit ->
             * "Attempted to kill the idle task" panic（gdb t42-t53 实证）。
             * 回退为不置（写 CON bit4 只清位不置 IPD），恢复 t13 用户态基线。 */
            /* STOPIPD 置位（t72 起重新启用）：act8846 probe 成功 -> 12 个 regulator
             * -> vdd_logic 可用 -> TWRP 显示上电不再 DVFS ERR。
             * 此前必须回退是因为 kernel_init 的 execve("/sbin/modprobe") 以 ENOENT
             * 失败导致 panic（t42-t53）；t72 的 ramdisk 已补 sbin/modprobe
             *（18 B 脚本 #!/sbin/sh exit 0），该 panic 路径有望解除。 */
            s->con &= ~(1u << 4);
            if (val & (1u << 4)) {
                s->ipd |= I2C_IPD_STOP;
                rk3288_i2c_upd(s);
            }
        }
        break;
    case 0x004: s->clkdiv   = val; break;
    case 0x008: s->mrxaddr  = val; break;
    case 0x00c: s->mrxraddr = val; break;
    case 0x010:
        s->mtxcnt = val;
        if (val) {
            rk3288_i2c_do_tx(s);
            rk3288_i2c_upd(s);
        }
        break;
    case 0x014:
        s->mrxcnt = val;
        if (val) {
            rk3288_i2c_do_rx(s);
            rk3288_i2c_upd(s);
        }
        break;
    case 0x018: s->ien = val; rk3288_i2c_upd(s); break;
    case 0x01c: s->ipd &= ~((uint32_t)val & 0x7f); rk3288_i2c_upd(s); break;
    case 0x020: s->fcnt = val; break;
    default: break;
    }
}

static const MemoryRegionOps rk3288_i2c_ops = {
    .read = rk3288_i2c_read, .write = rk3288_i2c_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

/* ---- TSADC (thermal sensor) -------------------------------------------- */
/* WHY THIS EXISTS (measured 2026-10-20, t14/t15 stack walk):
 *   dvfs_temp_limit_work_func() (dvfs.c:1079, 100ms delayed work) reads
 *   rockchip_tsadc_get_temp(1) and, when the temperature changes by more
 *   than 1 degree, calls dvfs_clk_set_rate() -> dvfs_target() ->
 *   clk_dvfs_node_get_ref_volt(), which SPINS FOREVER on a garbage dvfs
 *   table entry (PC = clk_dvfs_node_get_ref_volt+0x4c, guest frozen at 25 s).
 *   With no TSADC model, DATA1 reads back 0 (catch-all) => code 0 does not
 *   fall into the driver table {3421..4095} => temp = 0 constantly; that is
 *   benign for the debounce (delta <= 1), but leaves the sensor blind.
 *   Model the sensor honestly: DATA1 = 3728 => 0 degC (driver table entry
 *   {3728, 0}), USER_CON & friends are read/write storage, the BUSY bit is
 *   always clear (conversion completes immediately).
 *   dts: tsadc@ff280000, reg = <0xff280000 0x100>, data regs at +0x20.. */
#define RK3288_TSADC_BASE 0xff280000ULL
#define RK3288_TSADC_SIZE 0x00000100ULL
static uint32_t rk3288_tsadc_regs[RK3288_TSADC_SIZE / 4];

static uint64_t rk3288_tsadc_read(void *opaque, hwaddr off, unsigned size)
{
    /* TSADC_DATA1 (channel 1, the one dvfs/tsadc_get_temp(1) polls): the
     * driver maps code 3728 to 0 degC.  Keep it constant so the 100ms
     * temp-limit work sees delta_temp == 0 and returns without touching
     * the DVFS path. */
    if (off == 0x24) {
        return 3728;
    }
    if (off / 4 < RK3288_TSADC_SIZE / 4) {
        return rk3288_tsadc_regs[off / 4];
    }
    return 0;
}

static void rk3288_tsadc_write(void *opaque, hwaddr off, uint64_t val,
                               unsigned size)
{
    if (off / 4 < RK3288_TSADC_SIZE / 4) {
        rk3288_tsadc_regs[off / 4] = val;
    }
}

static const MemoryRegionOps rk3288_tsadc_ops = {
    .read = rk3288_tsadc_read, .write = rk3288_tsadc_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

/* ---- LCDC0 (primary display controller) --------------------------------- */
/* WHY THIS EXISTS (measured 2026-10-21, gdb10-gdb20 + rk_fb.c source):
 *   t28 (act8846 OK via STOPIPD) gets past the DVFS path, so ddrfreq's VSYNC
 *   wait runs: ddr_change_freq() -> _ddr_change_freq() ->
 *   rk_fb_poll_wait_frame_complete() (rk_fb.c:665).  That polls
 *   dev_drv->ops->poll_vblank = rk3288_lcdc_poll_vblank()
 *   (lcdc/rk3288_lcdc.c:3332), which reads INTR_CTRL0 (+0x20) and tests
 *   m_LINE_FLAG_INTR_STS (bit2):
 *       bit2 = 0 -> RK_LF_STATUS_FR (0xee)   "frame ready"
 *       bit2 = 1 -> RK_LF_STATUS_FC (0xef)   "frame complete" (then W1C)
 *   rk_fb_poll_wait_frame_complete() spins RK_LF_MAX_TIMEOUT = 102,400,000
 *   iterations waiting for FC.  With no LCDC model INTR_CTRL0 reads 0
 *   (catch-all), FC never comes, and the guest burns ~25 s in the spin
 *   before userspace would have been reached.
 *   Model the line-flag status honestly: the primary LCDC is enabled
 *   (dts: lcdc@ff930000 status=okay, boot.log "lcdc0 probe ok"), so a frame
 *   boundary occurs every frame period.  Emulate it with a read counter
 *   (one "frame" per 256 reads of INTR_CTRL0); the W1C clear restarts the
 *   phase so the next poll observes FR before FC.
 * dts: lcdc@ff930000 reg = <0xff930000 0x10000>, IRQ 15.
 * lcdc/rk3288_lcdc.h: INTR_CTRL0 = 0x0020, m_LINE_FLAG_INTR_STS = (1<<2). */
#define RK3288_LCDC0_BASE 0xff930000ULL
#define RK3288_LCDC0_SIZE 0x00010000ULL
#define RK3288_LCDC0_FRAME_READS 256u
static uint32_t rk3288_lcdc0_reads;

static uint64_t rk3288_lcdc0_read(void *opaque, hwaddr off, unsigned size)
{
    if (off == 0x20) {
        /* INTR_CTRL0: bit2 = LINE_FLAG interrupt status (frame boundary) */
        rk3288_lcdc0_reads++;
        return ((rk3288_lcdc0_reads / RK3288_LCDC0_FRAME_READS) & 1u) ? 4u : 0u;
    }
    return 0;
}

static void rk3288_lcdc0_write(void *opaque, hwaddr off, uint64_t val,
                               unsigned size)
{
    if (off == 0x20) {
        /* v_LINE_FLAG_INTR_CLR(1) = bit3: W1C of the line flag.  Restart the
         * frame phase so the FR->FC sequence can repeat. */
        if (val & 0x8) {
            rk3288_lcdc0_reads = (rk3288_lcdc0_reads | (RK3288_LCDC0_FRAME_READS - 1)) + 1;
        }
    }
}

static const MemoryRegionOps rk3288_lcdc0_ops = {
    .read = rk3288_lcdc0_read, .write = rk3288_lcdc0_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

/* ---- SARADC (drivers/iio/adc/rockchip_adc.c) --------------------------- */
/* WHY THIS EXISTS (measured 2026-10-22, t66/t67):
 *   Without a model every read of 0xff100000 returns 0 (catch-all), so the
 *   saradc IIO driver's rk_read_raw() times out after RK_ADC_TIMEOUT (HZ)
 *   waiting for the completion its ISR feeds -> "read channel() error:
 *   -110" every ~0.5 s from extcon-adc-jack (headset detect) and the
 *   headset probe WARNING seen since t27.  Model it honestly: the RK3288
 *   SARADC converts in a few us, so STAS.BUSY is clear, DATA carries the
 *   last conversion (0x3ff = no jack / vref high), and starting a
 *   conversion (CTRL write) pulses the completion IRQ.  The driver ISR
 *   never acknowledges the line, so this MUST be an edge (pulse), not a
 *   level, or it would storm.
 * dts: adc@ff100000 reg = <0xff100000 0x100>, interrupts = <0 0x24 4> (SPI 36). */
#define RK3288_SARADC_BASE 0xff100000ULL
#define RK3288_SARADC_SIZE 0x00000100ULL
#define RK3288_SARADC_IRQ   36
static uint32_t rk3288_saradc_regs[RK3288_SARADC_SIZE / 4];
static qemu_irq rk3288_saradc_irq;

static uint64_t rk3288_saradc_read(void *opaque, hwaddr off, unsigned size)
{
    if (off == 0x00) {
        return 0x3ff;                        /* ADC_DATA: conversion result */
    }
    if (off == 0x04) {
        return 0;                            /* ADC_STAS: BUSY clear */
    }
    if (off / 4 < RK3288_SARADC_SIZE / 4) {
        return rk3288_saradc_regs[off / 4];
    }
    return 0;
}

static void rk3288_saradc_write(void *opaque, hwaddr off, uint64_t val,
                                unsigned size)
{
    if (off / 4 < RK3288_SARADC_SIZE / 4) {
        rk3288_saradc_regs[off / 4] = val;
    }
    if (off == 0x08) {
        /* ADC_CTRL: power-up (bit0) starts a conversion; the RK3288 finishes
         * it almost immediately, so raise the completion IRQ.  The driver
         * ISR acknowledges by writing CTRL=0 (it also clears DELAY_PU_SOC),
         * which lowers the line again — a level IRQ, not a pulse: the GIC
         * samples SPI lines as level-sensitive, and qemu_irq_pulse() was
         * measured (t67) to be dropped before the handler ran. */
        rk3288_saradc_regs[off / 4] = val;
        if (val & 0x01) {
            qemu_irq_raise(rk3288_saradc_irq);
        } else {
            qemu_irq_lower(rk3288_saradc_irq);
        }
    }
}

static const MemoryRegionOps rk3288_saradc_ops = {
    .read = rk3288_saradc_read, .write = rk3288_saradc_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

/* ---- PMU -------------------------------------------------------------- */
/* PMU_IDLE_REQ @0x10 / PMU_IDLE_ST @0x14 are a request/ack handshake
 * (idle_bus = bit0, idle_peri = bit1 — see ddr_rk32.c "#define idle_peri").
 * Measured 2026-10-20: the guest stalls right after rockchip_headset_probe()
 * by reading 0x10 then 0x14 forever, because a read-0 IDLE_ST never
 * acknowledges the request. Model it as "whatever was requested is already
 * idle" — that is the honest behaviour of an idle SoC, not a fake pass. */
static uint32_t rk3288_pmu_idle_req;
static uint32_t rk3288_pmu_pwrdn_con;

static uint64_t rk3288_pmu_read(void *opaque, hwaddr off, unsigned size)
{
    uint32_t v;

    switch (off) {
    case 0x9c: v = RK3288_PMU_SYS2; break;
    case 0x08: v = rk3288_pmu_pwrdn_con; break;
    /* PWRDN_ST: per-domain power status.  Measured 2026-10-22 (t65): the
     * power-domain handshake helper (0xc0021bfc) wrote PWRDN_CON = 0x80
     * (bit7) and polled PWRDN_ST for the SAME bit (mask 0x80), i.e. the
     * ST ack bit is 1:1 with the CON enable bit (RK3288 TRM:
     * pd_vio_pwr_st = 1<<7 == the vio pwren bit).  Echo con directly. */
    case 0x0c: v = rk3288_pmu_pwrdn_con; break;
    case 0x10: v = rk3288_pmu_idle_req; break;
    /* IDLE_ST carries TWO groups (ddr_rk32.c L88-96):
     *   bits  0- 9: per-domain idle STATUS (same positions as IDLE_REQ)
     *   bits 16-25: per-domain idle ACK    (= req << 16)
     * Measured 2026-10-22 (t56-t59): the 25 s freeze is a spin at
     * 0xc00245b0 in the idle handshake helper (0xc0024558): it writes
     * IDLE_REQ then polls IDLE_ST for (req_bit | ack_bit) = 0x100010
     * (idle_req_vio_cfg=1<<4 | idle_ack_vio=1<<20).  Echoing only the
     * low half (old model) never satisfies the ack half => infinite
     * loop.  So the honest value is req | (req << 16). */
    case 0x14: v = rk3288_pmu_idle_req | (rk3288_pmu_idle_req << 16); break;
    default:   v = 0; break;
    }
    rk3288_hit_note(0, off, "pmu", v);
    return v;
}

static void rk3288_pmu_write(void *opaque, hwaddr off, uint64_t val,
                             unsigned size)
{
    if (off == 0x08) {
        rk3288_pmu_pwrdn_con = val;
    }
    if (off == 0x10) {
        rk3288_pmu_idle_req = val;
    }
}

static const MemoryRegionOps rk3288_pmu_ops = {
    .read = rk3288_pmu_read, .write = rk3288_pmu_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

/* ---- SGRF (stride lives here) ------------------------------------------ */
static uint64_t rk3288_sgrf_read(void *opaque, hwaddr off, unsigned size)
{
    uint32_t v = (off == 0x08) ? RK3288_DDR_STRIDE_V : 0;

    rk3288_hit_note(1, off, "sgrf", v);
    return v;
}

static void rk3288_sgrf_write(void *opaque, hwaddr off, uint64_t val, unsigned size)
{
}

static const MemoryRegionOps rk3288_sgrf_ops = {
    .read = rk3288_sgrf_read, .write = rk3288_sgrf_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

/* ---- MSCH (ddrconf -> rbc table) --------------------------------------- */
static uint64_t rk3288_msch_read(void *opaque, hwaddr off, unsigned size)
{
    /* ch a at +0x00, ch b at +0x80; ddrconf is the 3rd word of each */
    uint32_t v = ((off & 0xff) == 0x08) ? RK3288_DDR_CONF_V : 0;

    rk3288_hit_note(2, off, "msch", v);
    return v;
}

static void rk3288_msch_write(void *opaque, hwaddr off, uint64_t val, unsigned size)
{
}

static const MemoryRegionOps rk3288_msch_ops = {
    .read = rk3288_msch_read, .write = rk3288_msch_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

/* ---- DDR: PCTL (state machine) + PUBL/PHY (training results) -----------
 *
 * ★ PCTL 状态机（本轮新增，2026-10-20）：
 *   ddr_change_freq 走 ddr_move_to_Config_state / ddr_move_to_Access_state，
 *   它们写 SCTL 然后轮询 STAT.b.ctl_stat。若 STAT 恒为 Access(3)，
 *   "写 CFG_STATE 后等 Config(1)" 就永远不成立 ⇒ 死等。
 *   常量取自 ddr_rk32.c: CFG_STATE=1 GO_STATE=2 SLEEP_STATE=3 WAKEUP_STATE=4；
 *   STAT: Init_mem=0 Config=1 Access=3 Low_power=5。
 *   => 把 STAT 做成"跟随最近一次 SCTL 命令"。
 */
static uint32_t rk3288_pctl_stat[2] = { 3, 3 };   /* 上电即 Access */
static uint32_t rk3288_pctl_sctl[2];

static void rk3288_pctl_cmd(unsigned ch, uint32_t cmd)
{
    uint32_t st;

    rk3288_pctl_sctl[ch] = cmd;
    switch (cmd) {
    case 1:  st = 1; break;   /* CFG_STATE   -> Config    */
    case 2:  st = 3; break;   /* GO_STATE    -> Access    */
    case 3:  st = 5; break;   /* SLEEP_STATE -> Low_power */
    case 4:  st = 3; break;   /* WAKEUP_STATE-> Access    */
    default: return;
    }
    rk3288_pctl_stat[ch] = st;
}
static uint32_t rk3288_phy_read(hwaddr off)
{
    static const uint32_t dxgsr0 = 0x3u | (4u << 13) | (4u << 16); /* DTONE 3, DTPASS 4,4 */
    static const uint32_t dxdqstr = 0x1u | (0x1u << 3) | (0x1u << 12) | (0x1u << 14);
    static const uint32_t zq0sr0 = 0x19u | (0x19u << 5) | (0x2u << 10) | (0x2u << 15);

    switch (off) {
    case 0x000: return 0x00000001;  /* RIDR: revision, non-zero */
    case 0x00c: return 0x1f;        /* PGSR: IDONE|DLDONE|ZCDONE|DIDONE|DTDONE */
    case 0x030: return 0x0b;        /* DCR: DDRMD=3 (DDR3) + DDR8BNK */
    case 0x188: return zq0sr0;      /* ZQ0SR[0]: DRV/ODT pull values */
    case 0x18c: return 0;           /* ZQ0SR[1]: no ZERR/ZPULL error bits */
    default:
        break;
    }
    /* DATX8[9] each 0x80 bytes starting at 0x1c0 */
    if (off >= 0x1c0 && off < 0x1c0 + 9 * 0x80) {
        unsigned rel = (off - 0x1c0) % 0x80;

        if (rel == 0x04) return dxgsr0;   /* DXGSR[0] */
        if (rel == 0x14) return dxdqstr;  /* DXDQSTR   */
    }
    return 0;
}

static uint64_t rk3288_ddr_read(void *opaque, hwaddr off, unsigned size)
{
    unsigned blk = off >> 12;          /* 0=PCTL0 1=PUBL0 2=PCTL1 3=PUBL1 */
    hwaddr  rel = off & 0xfff;
    uint32_t v;

    if (blk & 1) {
        v = rk3288_phy_read(rel);       /* PUBL / PHY */
    } else if (rel == 0x08) {
        v = rk3288_pctl_stat[blk >> 1]; /* STAT.ctl_stat：跟随 SCTL */
    } else if (rel == 0x04) {
        v = rk3288_pctl_sctl[blk >> 1]; /* SCTL 回读 */
    } else if (rel == 0x84) {
        v = 1;                          /* PPCFG: both byte lanes */
    } else {
        v = 0;
    }
    rk3288_hit_note(3, off, "ddr", v);
    return v;
}

static void rk3288_ddr_write(void *opaque, hwaddr off, uint64_t val, unsigned size)
{
    unsigned blk = off >> 12;

    if (!(blk & 1) && (off & 0xfff) == 0x04) {
        rk3288_pctl_cmd(blk >> 1, val);   /* SCTL：驱动状态机 */
    }
    /* 其余(MCMD/TREFI/MR)保持 fire-and-forget */
}

static const MemoryRegionOps rk3288_ddr_ops = {
    .read = rk3288_ddr_read, .write = rk3288_ddr_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

static void rk3288_add_io(MemoryRegion *sysmem, hwaddr base, hwaddr size,
                          const MemoryRegionOps *ops, const char *name)
{
    MemoryRegion *r = g_new(MemoryRegion, 1);

    memory_region_init_io(r, NULL, ops, NULL, name, size);
    memory_region_add_subregion(sysmem, base, r);
}


/* ------------------------------------------------------------------------- */
/* Machine                                                                    */
/* ------------------------------------------------------------------------- */

#define RK3288_PERIPHBASE 0xffc00000ULL

/* DTB serial nodes: reg / interrupts (SPI numbers, measured from p817.dts) */
static const hwaddr rk3288_uart_base[5] = {
    0xff180000, 0xff190000, 0xff690000, 0xff1b0000, 0xff1c0000
};
static const int rk3288_uart_irq[5] = { 0x37, 0x38, 0x39, 0x3a, 0x3b };

static void rk3288_init(MachineState *machine)
{
    DeviceState *cpudev;
    DeviceState *mpcore;
    MemoryRegion *sysmem = get_system_memory();
    unsigned int smp_cpus = machine->smp.cpus;
    qemu_irq pic[256];
    int n;

    /* DRAM at 0 — P817 evidence: logo buffer at 0xfbc00000 (see header) */
    memory_region_add_subregion(sysmem, 0, machine->ram);

    /* One catch-all over the whole peripheral window, at a priority BELOW
     * every real model, so nothing the kernel probes can raise an external
     * abort (see the comment above the ops).  Specific blocks added later
     * shadow it automatically because they use the default priority 0. */
    {
        MemoryRegion *win = g_new(MemoryRegion, 1);

        memory_region_init_io(win, NULL, &rk3288_catchall_ops, NULL,
                              "rk3288-periph-window", RK3288_PERIPH_WIN_SIZE);
        memory_region_add_subregion_overlap(sysmem, RK3288_PERIPH_WIN_BASE,
                                            win, -1000);
    }

    /* CRU + GRF read back all-ones so the PLL lock waits complete.
     *
     * MEASURED (drivers/clk/rockchip/clk-pll.c:173-198): pll_wait_lock()
     * polls grf_readl(pll->status_offset) & (1 << status_shift) 24,000,000
     * times and, on timeout, prints and enters while(1) forever.  The lock
     * bits live in the GRF (0xff770000) - and RK_GRF_VIRT is the io_desc
     * virtual 0xfed10000, i.e. exactly the range the disassembly showed.
     * Reads of 0 therefore make the wait always time out.  The CRU gets the
     * same treatment for the same reason (any lock/mode bit read there). */
    rk3288_add_allones(sysmem, RK3288_CRU_BASE, RK3288_CRU_SIZE, "rk3288-cru");
    rk3288_add_allones(sysmem, RK3288_GRF_BASE, RK3288_GRF_SIZE, "rk3288-grf");

    /* DDR / PMU / SGRF / MSCH — see the derivation block above.
     * Without these, ddr_get_datatraing_addr() dereferences a NULL pMSCH_Reg
     * and no recovery image ever reaches userspace (0.51 s panic). */
    rk3288_add_io(sysmem, RK3288_PMU_BASE,  0x1000, &rk3288_pmu_ops,  "rk3288-pmu");
    rk3288_add_io(sysmem, RK3288_SGRF_BASE, 0x1000, &rk3288_sgrf_ops, "rk3288-sgrf");
    rk3288_add_io(sysmem, RK3288_SGRF_ALT,  0x1000, &rk3288_sgrf_ops, "rk3288-sgrf-alt");
    rk3288_add_io(sysmem, RK3288_MSCH_BASE, 0x1000, &rk3288_msch_ops, "rk3288-msch");
    rk3288_add_io(sysmem, RK3288_DDR_BASE,  RK3288_DDR_SIZE, &rk3288_ddr_ops, "rk3288-ddr");
    /* ★ 补丁 1 的区域默认关闭（2026-10-28 实测证据）：
     * 该内核用默认 loader_start 装到 0x00008000，自解压后映像约 13 MB
     * （字符串区实测在 0x00d165xx），正好覆盖 0x000d0000。若在此注册
     * DDR model，会把自解压器自己的代码/数据挖掉 16 KiB ⇒ 死在
     * 0xd13af8 `b .`，串口 0 字节。要用本方案，必须同时把内核装到
     * 0x000d4000 以上且避开其 TEXTADDR；否则应走内核侧补丁 2。 */
#ifdef RK3288_DDR_VIRT_REGION
    rk3288_add_io(sysmem, RK3288_DDR_VIRT_BASE, RK3288_DDR_SIZE,
                  &rk3288_ddr_ops, "rk3288-ddr-virt");
#endif

    /* TSADC: a constant 0 degC reading keeps dvfs_temp_limit_work_func()
     * inside its debounce (delta_temp <= 1) so it never calls into the
     * DVFS set-rate path that spins on a garbage table. */
    rk3288_add_io(sysmem, RK3288_TSADC_BASE, RK3288_TSADC_SIZE,
                  &rk3288_tsadc_ops, "rk3288-tsadc");

    /* LCDC0: INTR_CTRL0(+0x20) bit2 = line-flag/frame-complete status so
     * rk3288_lcdc_poll_vblank() returns FC and rk_fb_poll_wait_frame_complete()
     * (ddrfreq VSYNC wait) terminates instead of spinning 102.4M times. */
    rk3288_add_io(sysmem, RK3288_LCDC0_BASE, RK3288_LCDC0_SIZE,
                  &rk3288_lcdc0_ops, "rk3288-lcdc0");

    /* SARADC: completing conversions (edge IRQ 36) keeps the IIO driver's
     * wait_for_completion_timeout from failing with -110 every poll.
     * The region can be mapped now; the IRQ line is picked up after the
     * pic[] array is filled below. */
    rk3288_add_io(sysmem, RK3288_SARADC_BASE, RK3288_SARADC_SIZE,
                  &rk3288_saradc_ops, "rk3288-saradc");

    /* SRAM + bootram: real RAM, because the PIE chunk is COPIED into it
     * (see the comment block above RK3288_SRAM_BASE). */
    {
        MemoryRegion *sram = g_new(MemoryRegion, 1);
        MemoryRegion *bram = g_new(MemoryRegion, 1);

        memory_region_init_ram(sram, NULL, "rk3288-sram",
                               RK3288_SRAM_SIZE, &error_fatal);
        memory_region_add_subregion(sysmem, RK3288_SRAM_BASE, sram);
        memory_region_init_ram(bram, NULL, "rk3288-bootram",
                               RK3288_BOOTRAM_SIZE, &error_fatal);
        memory_region_add_subregion(sysmem, RK3288_BOOTRAM_BASE, bram);
    }

    machine->cpu_type = ARM_CPU_TYPE_NAME("cortex-a15");

    for (n = 0; n < smp_cpus; n++) {
        Object *cpuobj = object_new(machine->cpu_type);

        /* CBAR: where the CPU finds its private peripherals. The
         * a15mpcore_priv maps the GIC at CBAR+0x1000 (dist) and CBAR+0x2000
         * (cpu if) — exactly the P817 DTB's GIC layout. */
        if (object_property_find(cpuobj, "reset-cbar")) {
            object_property_set_int(cpuobj, "reset-cbar", RK3288_PERIPHBASE,
                                    &error_abort);
        }
        /* DTB timer node: clock-frequency = 24000000 */
        if (object_property_find(cpuobj, "cntfrq")) {
            object_property_set_int(cpuobj, "cntfrq", 24000000,
                                    &error_abort);
        }
        object_property_set_bool(cpuobj, "realized", true, &error_abort);
    }

    /* GIC + private peripherals. a15mpcore_priv mmio 0 = the container:
     * periph at +0x0000, GIC dist at +0x1000, GIC cpu if at +0x2000. */
    mpcore = qdev_new(TYPE_A15MPCORE_PRIV);
    qdev_prop_set_uint32(mpcore, "num-cpu", smp_cpus);
    qdev_prop_set_uint32(mpcore, "num-irq", 256);
    sysbus_realize_and_unref(SYS_BUS_DEVICE(mpcore), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(mpcore), 0, RK3288_PERIPHBASE);
    for (n = 0; n < smp_cpus; n++) {
        cpudev = DEVICE(qemu_get_cpu(n));
        sysbus_connect_irq(SYS_BUS_DEVICE(mpcore), n,
                           qdev_get_gpio_in(cpudev, ARM_CPU_IRQ));
        sysbus_connect_irq(SYS_BUS_DEVICE(mpcore), n + smp_cpus,
                           qdev_get_gpio_in(cpudev, ARM_CPU_FIQ));
    }
    /* a15mpcore_priv exposes num_irq-32 GPIO inputs; mpcore GPIO i maps to
     * GIC IRQ i+32, i.e. exactly the DTB's SPI numbering. The P817 DTB uses
     * SPI numbers 0x09..0x6f, so 224 external inputs are plenty. */
    for (n = 0; n < 256 - 32; n++) {
        pic[n] = qdev_get_gpio_in(mpcore, n);
    }
    rk3288_saradc_irq = pic[RK3288_SARADC_IRQ];   /* after pic[] is filled */

    /* 5x RK UART at the DTB addresses. serial2 (ff690000) is the device's
     * real console port, so the chardev goes there; the others stay silent. */
    for (n = 0; n < 5; n++) {
        DeviceState *uart = qdev_new(TYPE_RK3288_UART);

        if (n == 2) {
            qdev_prop_set_chr(uart, "chardev", serial_hd(0));
        }
        sysbus_realize_and_unref(SYS_BUS_DEVICE(uart), &error_fatal);
        sysbus_mmio_map(SYS_BUS_DEVICE(uart), 0, rk3288_uart_base[n]);
        sysbus_connect_irq(SYS_BUS_DEVICE(uart), 0, pic[rk3288_uart_irq[n]]);
    }

    /* 6x RK I2C + ACT8846（i2c-0 @0x5a）。IRQ 必须真接上：
     * 驱动是 wait_event_timeout(is_busy==0)，不拉中断就只会超时 -110。 */
    act8846_reset();
    gtp_reset();
    for (n = 0; n < RK3288_I2C_NR; n++) {
        MemoryRegion *r = g_new(MemoryRegion, 1);

        memset(&rk3288_i2c[n], 0, sizeof(rk3288_i2c[n]));
        rk3288_i2c[n].irq = pic[rk3288_i2c_irq[n]];
        memory_region_init_io(r, NULL, &rk3288_i2c_ops, &rk3288_i2c[n],
                              "rk3288-i2c", 0x1000);
        memory_region_add_subregion(sysmem, rk3288_i2c_base[n], r);
    }

    /* Kernel + DTB. The -dtb we pass is the P817 DTB (memory + serial
     * status fixed up by the harness script, both changes logged). */
    {
        struct arm_boot_info binfo;

        memset(&binfo, 0, sizeof(binfo));
        binfo.ram_size = machine->ram_size;
        binfo.kernel_filename = machine->kernel_filename;
        binfo.kernel_cmdline = machine->kernel_cmdline;
        binfo.initrd_filename = machine->initrd_filename;
        binfo.dtb_filename = machine->dtb;
        binfo.board_id = -1;    /* DT boot, not ATAG */
        /* ★ 2026-10-28 实测：默认装载把 zImage 放在 0x00008000，自解压映像
         * 实测覆盖到 0x00d165xx（约 13 MB）—— 请勿把 DDR model 映射进
         * 0x000d0000（见上面 RK3288_DDR_VIRT_REGION 的说明）。
         * 另测：改 loader_start 到 0x02080000 会因 zImage 内置 TEXTADDR
         * 不匹配而死在 0xffff000c（prefetch abort 自循环）；
         * 改到 0x00100000 仍未产出任何串口输出。故保持默认装载地址。 */
        arm_load_kernel(ARM_CPU(qemu_get_cpu(0)), machine, &binfo);
    }
}

static void rk3288_machine_class_init(ObjectClass *oc, void *data)
{
    MachineClass *mc = MACHINE_CLASS(oc);

    mc->desc = "Rockchip RK3288 (P817 minimal, milestone-2 harness)";
    mc->init = rk3288_init;
    mc->max_cpus = 4;
    mc->default_cpu_type = ARM_CPU_TYPE_NAME("cortex-a15");
    mc->default_ram_size = 2 * 1024 * 1024 * 1024ULL;
    mc->default_ram_id = "rk3288.ram";
    mc->no_parallel = 1;   /* the 5 UARTs + GIC wiring is per-machine state */
}

static const TypeInfo rk3288_machine_info = {
    .name          = MACHINE_TYPE_NAME("rk3288"),
    .parent        = TYPE_MACHINE,
    .instance_size = sizeof(MachineState),
    .class_init    = rk3288_machine_class_init,
};

static void rk3288_machine_register_types(void)
{
    type_register_static(&rk3288_uart_info);
    type_register_static(&rk3288_machine_info);
}

type_init(rk3288_machine_register_types)
