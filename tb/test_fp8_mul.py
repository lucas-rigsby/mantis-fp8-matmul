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

from funcov import Cover, closure_report
from funcov_classes import fp8_class
from mantis_ref import DIRECTED_MUL, mul

# ---- functional coverage (classified from the operands and docs/spec.md Formats)
FMT = {0: "E4M3FN", 1: "E5M2"}
_CLASSES = {0: ("zero", "sub", "normal", "max", "nan"), 1: ("zero", "sub", "normal", "max", "inf", "nan")}
COV_OPERAND = Cover("R4, R5: operand class per format and sign", {
    f"{FMT[f]} {c} {'-' if s else '+'}": (lambda f, c, s: lambda x, fmt: fmt == f and x >> 7 == s and fp8_class(x, fmt) == c)(f, c, s)
    for f in (0, 1) for c in _CLASSES[f] for s in (0, 1)})
COV_FORMATS = Cover("R6: format pair", {
    f"A {FMT[fa]}, B {FMT[fb]}": (lambda fa, fb: lambda a, b, ca, cb, x, y: (x, y) == (fa, fb))(fa, fb)
    for fa in (0, 1) for fb in (0, 1)})
_FIN = ("sub", "normal", "max")
COV_PRODUCT = Cover("R2, R7, R8, R9: product class", {
    "R7 NaN operand A":           lambda a, b, ca, cb, x, y: ca == "nan",
    "R7 NaN operand B":           lambda a, b, ca, cb, x, y: cb == "nan",
    "R7 inf x 0":                 lambda a, b, ca, cb, x, y: ca == "inf" and cb == "zero",
    "R7 0 x inf":                 lambda a, b, ca, cb, x, y: ca == "zero" and cb == "inf",
    "R8 inf x finite":            lambda a, b, ca, cb, x, y: ca == "inf" and cb in _FIN,
    "R8 finite x inf":            lambda a, b, ca, cb, x, y: ca in _FIN and cb == "inf",
    "R8 inf x inf":               lambda a, b, ca, cb, x, y: ca == "inf" and cb == "inf",
    "R9 0 x finite":              lambda a, b, ca, cb, x, y: ca == "zero" and cb in _FIN,
    "R9 finite x 0":              lambda a, b, ca, cb, x, y: ca in _FIN and cb == "zero",
    "R9 -0 x +0":                 lambda a, b, ca, cb, x, y: (a, b) == (0x80, 0x00),
    "R9 -0 x -0":                 lambda a, b, ca, cb, x, y: (a, b) == (0x80, 0x80),
    "R2 sub x sub (smallest)":    lambda a, b, ca, cb, x, y: ca == "sub" and cb == "sub",
    "R2 max x max (largest)":     lambda a, b, ca, cb, x, y: ca == "max" and cb == "max",
    **{f"R2 sign {'-' if sa else '+'}{'-' if sb else '+'} finite": (lambda sa, sb: lambda a, b, ca, cb, x, y:
       ca in _FIN and cb in _FIN and (a >> 7, b >> 7) == (sa, sb))(sa, sb) for sa in (0, 1) for sb in (0, 1)},
})


def _sample(a, b, fa, fb):
    ca, cb = fp8_class(a, fa), fp8_class(b, fb)
    COV_OPERAND.sample(a, fa)
    COV_OPERAND.sample(b, fb)
    COV_FORMATS.sample(a, b, ca, cb, fa, fb)
    COV_PRODUCT.sample(a, b, ca, cb, fa, fb)


async def _apply(dut, a, b, fa, fb):
    _sample(a, b, fa, fb)
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


@cocotb.test()
async def functional_coverage(dut):
    """Closure of the functional-coverage groups above; fails on any empty bin."""
    closure_report(dut._log)


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
