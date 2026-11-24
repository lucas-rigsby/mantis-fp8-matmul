"""cocotb tests for rtl/fp8_mul.v (T5 multiplier prototype gate).

P4: exhaustive check of every operand pair in all four format combinations
(4 x 65,536 = 262,144) against the independent reference model tb/mantis_ref.py.
That exhaustively covers R2 (exact product), R4 (E4M3FN decode), R5 (E5M2
decode), R6 (independent formats), R7 (NaN and inf*0 products), R8 (signed
infinity products) and R9 (signed-zero products) at the product level.

Run (OSS CAD Suite):
    source ~/eda/oss-cad-suite/environment
    export LIBPYTHON_LOC=$(cocotb-config --libpython)
    python3 -m pytest tb/test_fp8_mul.py          # SIM=verilator also works
"""
import os
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

from mantis_ref import DIRECTED_MUL, mul


async def _apply(dut, a, b, fa, fb):
    dut.a.value = a
    dut.b.value = b
    dut.fmt_a.value = fa
    dut.fmt_b.value = fb
    await Timer(1, unit="ns")
    return int(dut.p.value)


@cocotb.test()
async def directed(dut):
    """Spec worked examples and format boundaries (R2, R4, R5, R6, R7, R8, R9)."""
    for a, b, fa, fb, exp, why in DIRECTED_MUL:
        got = await _apply(dut, a, b, fa, fb)
        assert got == exp, f"{why}: {a:#04x} x {b:#04x} fmt=({fa},{fb}) got {got:#06x} expected {exp:#06x}"


@cocotb.test()
async def exhaustive(dut):
    """P4: all 262,144 operand pairs match the reference (R2, R4, R5, R6, R7, R8, R9)."""
    errors = []
    for fa in (0, 1):
        for fb in (0, 1):
            for a in range(256):
                for b in range(256):
                    got = await _apply(dut, a, b, fa, fb)
                    exp = mul(a, b, fa, fb)
                    if got != exp:
                        errors.append(f"{a:#04x} x {b:#04x} fmt=({fa},{fb}) got {got:#06x} expected {exp:#06x}")
    assert not errors, f"P4: {len(errors)} mismatches, first: {errors[:5]}"
    dut._log.info("P4: 262144 operand pairs match the reference")


def test_fp8_mul():
    from cocotb_tools.runner import get_runner
    root = Path(__file__).resolve().parent.parent
    sim = os.getenv("SIM", "icarus")
    runner = get_runner(sim)
    runner.build(
        sources=[root / "rtl" / "fp8_unpack.v", root / "rtl" / "fp8_mul.v"],
        hdl_toplevel="fp8_mul",
        build_dir=root / "tb" / "sim_build" / f"fp8_mul_{sim}",
        build_args=["--timing"] if sim == "verilator" else [],
        always=True,
        timescale=("1ns", "1ps"),
    )
    runner.test(hdl_toplevel="fp8_mul", test_module="test_fp8_mul",
                test_dir=Path(__file__).resolve().parent)


if __name__ == "__main__":
    test_fp8_mul()
