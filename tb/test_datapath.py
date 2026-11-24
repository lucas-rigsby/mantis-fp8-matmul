"""cocotb tests for the T7 2x2 datapath prototypes (docs/spec.md T7):
rtl/mantis_dp_pe4.v (four PEs) and rtl/mantis_dp_shared.v (one shared MAC).

Both expose the same ports, so the same tests run on each top level:
  spec_examples   R1 worked example, R3 rounding example, R5/R6/R7/R8/R9 examples
  busy_drain      R11: busy=1 after the 4th WRITE edge, falls within 8 cycles
  streaming       R10, P11: 1,000 back-to-back groups with no gaps, vs reference
  random_traffic  R1, R10, P6: random K, formats, specials, interleaved
                  NOP/READ/in_valid=0 idle cycles
  clear_flush     R13, P10: CLEAR at every cycle 0..7 after issue and during
                  partial groups; nothing pre-CLEAR commits afterwards
  reset_flush     R14: reset at every cycle after issue and during partial
                  groups clears all state

Run (OSS CAD Suite):
    source ~/eda/oss-cad-suite/environment
    export LIBPYTHON_LOC=$(cocotb-config --libpython)
    python3 -m pytest tb/test_datapath.py          # both organizations
"""
import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

from funcov import Cover, closure_report
from funcov_classes import CommandCoverage
from mantis_ref import matmul, rand_matmul, write_stream

WRITE, CLEAR, READ, NOP = 0, 1, 2, 3
MAX_DRAIN = 8                                     # R11 target
COV = CommandCoverage(Cover)                      # functional coverage of the command stream


def ref(A, B, fa, fb):
    """Reference result; also samples its result classes for coverage."""
    C = matmul(A, B, fa, fb)
    COV.results(C)
    return C


def acc_words(dut):
    v = int(dut.acc.value)
    return [[v & 0xFFFF, (v >> 16) & 0xFFFF], [(v >> 32) & 0xFFFF, (v >> 48) & 0xFFFF]]


def fmt_hex(C):
    return "[[%04X %04X] [%04X %04X]]" % (C[0][0], C[0][1], C[1][0], C[1][1])


class Driver:
    def __init__(self, dut):
        self.dut = dut

    async def cycle(self, valid=0, cmd=NOP, din=0, rst_n=1):
        """Drive inputs mid-cycle, then sample state just after the rising edge."""
        await FallingEdge(self.dut.clk)
        COV.step(valid, cmd, din, rst_n)
        self.dut.rst_n.value = rst_n
        self.dut.in_valid.value = valid
        self.dut.cmd.value = cmd
        self.dut.din.value = din
        await RisingEdge(self.dut.clk)
        await ReadOnly()

    async def idle_until_done(self, limit=64):
        for _ in range(limit):
            if not int(self.dut.busy.value):
                return
            await self.cycle()
        raise AssertionError("busy never fell")

    async def clear(self, fa=0, fb=0):
        await self.cycle(1, CLEAR, (fb << 1) | fa)

    async def write(self, byte):
        await self.cycle(1, WRITE, byte)


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())   # 50 MHz
    d = Driver(dut)
    await d.cycle(rst_n=0)
    await d.cycle(rst_n=0)
    await d.cycle()
    return d


async def run_matmul(d, A, B, fa, fb):
    await d.clear(fa, fb)
    for byte in write_stream(A, B):
        await d.write(byte)
    await d.idle_until_done()
    return acc_words(d.dut)


@cocotb.test()
async def spec_examples(dut):
    """R1 matrix example, R3 rounding example, R5-R9 examples."""
    d = await start(dut)
    # R1: E4M3FN [[1,2],[3,4]] x [[5,6],[7,8]]
    C = await run_matmul(d, [[0x38, 0x40], [0x44, 0x48]], [[0x4A, 0x4C], [0x4E, 0x50]], 0, 0)
    assert C == [[0x4198, 0x41B0], [0x422C, 0x4248]], f"R1: {fmt_hex(C)}"
    # R3: C00 accumulates 16*16, 1*1, 1*1 -> 256 (0x4380), not 258
    one, sixteen = 0x38, 0x58
    C = await run_matmul(d, [[sixteen, one, one], [one] * 3],
                         [[sixteen, one], [one, one], [one, one]], 0, 0)
    assert C[0][0] == 0x4380, f"R3: C00 = {C[0][0]:#06x}"
    assert C == ref([[sixteen, one, one], [one] * 3], [[sixteen, one], [one, one], [one, one]], 0, 0)
    # R5: E5M2 1 * 57344; R6: A=E4M3FN 1, B=E5M2 1
    C = await run_matmul(d, [[0x3C], [0x3C]], [[0x7B, 0x3C]], 1, 1)
    assert C[0][0] == 0x4760 and C[0][1] == 0x3F80, f"R5: {fmt_hex(C)}"
    C = await run_matmul(d, [[0x38], [0x38]], [[0x3C, 0x3C]], 0, 1)
    assert C[0][0] == 0x3F80, f"R6: {fmt_hex(C)}"
    # R7: NaN then finite, persists; R8: +inf then 0.25 stays +inf (E5M2)
    C = await run_matmul(d, [[0x7F, 0x38], [0x38, 0x38]], [[0x38, 0x38], [0x38, 0x38]], 0, 0)
    assert C[0][0] == 0x7FC0 and C[0][1] == 0x7FC0, f"R7: {fmt_hex(C)}"
    C = await run_matmul(d, [[0x7C, 0x38], [0x3C, 0x3C]], [[0x3C, 0x3C], [0x38, 0x38]], 1, 1)
    assert C[0][0] == 0x7F80, f"R8: {fmt_hex(C)}"
    # R9: +1 then -1 -> +0; -0 product into +0 -> +0
    C = await run_matmul(d, [[0x38, 0xB8], [0x80, 0x80]], [[0x38, 0x38], [0x38, 0x38]], 0, 0)
    assert C[0][0] == 0x0000 and C[1][0] == 0x0000, f"R9: {fmt_hex(C)}"


@cocotb.test()
async def busy_drain(dut):
    """R11: busy rises at the 4th WRITE edge and falls within 8 cycles."""
    d = await start(dut)
    await d.clear()
    for byte in (0x38, 0x40, 0x44):
        await d.write(byte)
        assert int(dut.busy.value) == 0, "R11: a partial group must not set busy"
    await d.write(0x48)                                   # edge t0
    assert int(dut.busy.value) == 1, "R11: busy must be 1 after the issuing edge"
    drain = 1
    while True:
        await d.cycle()
        if not int(dut.busy.value):
            break
        drain += 1
        assert drain <= MAX_DRAIN, f"R11: busy still high {drain} cycles after issue"
    dut._log.info(f"R11: drain latency = {drain} cycles (busy=0 after edge t0+{drain})")
    snap = acc_words(dut)
    for _ in range(10):                                   # P12: stable when idle
        await d.cycle()
        assert acc_words(dut) == snap, "P12: accumulators changed while busy=0"


@cocotb.test()
async def streaming(dut):
    """R10, P11: 1,000 back-to-back groups (4,000 consecutive WRITEs)."""
    d = await start(dut)
    rng = random.Random(71)
    for fa, fb in ((0, 0), (0, 1), (1, 0), (1, 1)):
        A, B, _, _ = rand_matmul(rng, 250, fa, fb)
        C = await run_matmul(d, A, B, fa, fb)
        exp = ref(A, B, fa, fb)
        assert C == exp, f"R10 fmt=({fa},{fb}): got {fmt_hex(C)} expected {fmt_hex(exp)}"
    dut._log.info("R10: 4 x 250 back-to-back groups match the reference")


@cocotb.test()
async def random_traffic(dut):
    """R1, R10, P6: random K and formats with idle/NOP/READ cycles mixed in."""
    d = await start(dut)
    rng = random.Random(72)
    for trial in range(150):
        K = rng.randint(1, 48)
        A, B, fa, fb = rand_matmul(rng, K, finite=(rng.random() < 0.85))
        await d.clear(fa, fb)
        for byte in write_stream(A, B):
            while rng.random() < 0.3:                      # P6: no effect
                kind = rng.randrange(3)
                if kind == 0:
                    await d.cycle(0, rng.randrange(4), rng.getrandbits(8))
                elif kind == 1:
                    await d.cycle(1, NOP, rng.getrandbits(8))
                else:
                    await d.cycle(1, READ, rng.getrandbits(8))
            await d.write(byte)
        await d.idle_until_done()
        C, exp = acc_words(dut), ref(A, B, fa, fb)
        assert C == exp, f"trial {trial} K={K} fmt=({fa},{fb}): got {fmt_hex(C)} expected {fmt_hex(exp)}"
    dut._log.info("R1: 150 random matrix products match the reference")


@cocotb.test()
async def clear_flush(dut):
    """R13, P10: CLEAR at each cycle after issue, and during partial groups."""
    d = await start(dut)
    rng = random.Random(73)
    for delay in range(0, MAX_DRAIN):
        A, B, fa, fb = rand_matmul(rng, 3, 0, 0)
        await d.clear(fa, fb)
        for byte in write_stream(A, B):                   # last edge issues step 2
            await d.write(byte)
        for _ in range(delay):
            await d.cycle()
        await d.clear(1, 0)                               # new formats
        assert acc_words(dut) == [[0, 0], [0, 0]], f"R13: delay {delay} acc not cleared"
        assert int(dut.busy.value) == 0, f"R13: delay {delay} busy not cleared"
        assert (int(dut.fmt_a.value), int(dut.fmt_b.value)) == (1, 0), "R13: fmt not loaded"
        for _ in range(12):
            await d.cycle()
            assert acc_words(dut) == [[0, 0], [0, 0]], f"P10: pre-CLEAR step committed (delay {delay})"
    # partial group (1, 2 or 3 bytes) then CLEAR then a full group: only the new one counts
    for partial in (1, 2, 3):
        await d.clear(0, 0)
        for _ in range(partial):
            await d.write(0x58)                           # 16.0 in E4M3FN
        await d.clear(0, 0)
        assert int(dut.n.value) == 0, "R13: n not reset by CLEAR"
        C = await run_matmul_no_clear(d, [[0x38], [0x38]], [[0x38, 0x38]])
        assert C == [[0x3F80, 0x3F80], [0x3F80, 0x3F80]], f"R13: partial {partial}: {fmt_hex(C)}"


async def run_matmul_no_clear(d, A, B):
    for byte in write_stream(A, B):
        await d.write(byte)
    await d.idle_until_done()
    return acc_words(d.dut)


@cocotb.test()
async def reset_flush(dut):
    """R14: synchronous reset at each cycle after issue clears all state."""
    d = await start(dut)
    rng = random.Random(74)
    for delay in range(0, MAX_DRAIN):
        A, B, _, _ = rand_matmul(rng, 2, 1, 1)
        await d.clear(1, 1)
        for byte in write_stream(A, B):
            await d.write(byte)
        for _ in range(delay):
            await d.cycle()
        await d.cycle(1, WRITE, 0x3C, rst_n=0)            # command ignored in reset
        assert acc_words(dut) == [[0, 0], [0, 0]], f"R14: delay {delay} acc not reset"
        assert int(dut.busy.value) == 0 and int(dut.n.value) == 0, "R14: busy/n not reset"
        assert (int(dut.fmt_a.value), int(dut.fmt_b.value)) == (0, 0), "R14: fmt not reset"
        for _ in range(12):
            await d.cycle()
            assert acc_words(dut) == [[0, 0], [0, 0]], f"R14: pre-reset step committed (delay {delay})"
    # partial group (1, 2 or 3 bytes) then reset then a full group: only the new one counts
    for partial in (1, 2, 3):
        await d.clear(0, 0)
        for _ in range(partial):
            await d.write(0x58)                           # 16.0 in E4M3FN
        await d.cycle(rst_n=0)
        assert int(dut.n.value) == 0, f"R14: n not reset (partial {partial})"
        C = await run_matmul_no_clear(d, [[0x38], [0x38]], [[0x38, 0x38]])
        assert C == [[0x3F80, 0x3F80], [0x3F80, 0x3F80]], f"R14: partial {partial}: {fmt_hex(C)}"


@cocotb.test()
async def functional_coverage(dut):
    """Closure of the command-level coverage groups; fails on any empty bin."""
    closure_report(dut._log)


def _run(top):
    from cocotb_tools.runner import get_runner
    root = Path(__file__).resolve().parent.parent
    sim = os.getenv("SIM", "icarus")
    runner = get_runner(sim)
    rtl = root / "rtl"
    runner.build(
        sources=[rtl / "fp8_unpack.v", rtl / "fp8_mul.v", rtl / "bf16_add_s1.v",
                 rtl / "bf16_add_s2.v", rtl / "bf16_add.v",
                 rtl / "mantis_stage.v", rtl / f"{top}.v"],
        hdl_toplevel=top,
        build_dir=root / "tb" / "sim_build" / f"{top}_{sim}",
        always=True,
        timescale=("1ns", "1ps"),
    )
    runner.test(hdl_toplevel=top, test_module="test_datapath",
                test_dir=Path(__file__).resolve().parent)


def test_dp_pe4():
    _run("mantis_dp_pe4")


def test_dp_shared():
    _run("mantis_dp_shared")
