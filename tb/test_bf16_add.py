"""cocotb tests for rtl/bf16_add.v (T6 BF16 accumulator prototype gate).

Differential testing against the independent reference model tb/mantis_ref.py
(add_bf16, mac), covering R3 (RNE every accumulation), R7 (NaN generation and
persistence), R8 (infinity rules; overflow boundary at unit level) and R9
(signed zero; FTZ at unit level):

  directed      every DIRECTED_ADD case (spec examples and boundaries)
  reachable     every BF16 accumulator pattern x 8 port-reachable products
                (65,536 x 8 = 524,288)
  random_full   200,000 uniform BF16 x BF16 pairs (full-range unit behaviour)
  boundary      200,000 boundary_add pairs (cancellation, alignment 0..12,
                ties, overflow edge, FTZ edge)
  mac_chains    2,000 accumulation chains of length 1..64 through the adder
                with products from the reference multiplier (R3 sequential)

Run (OSS CAD Suite):
    source ~/eda/oss-cad-suite/environment
    export LIBPYTHON_LOC=$(cocotb-config --libpython)
    python3 -m pytest tb/test_bf16_add.py
"""
import os
import random
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

from funcov import Cover, closure_report
from funcov_classes import add_features
from mantis_ref import (DIRECTED_ADD, add_bf16, boundary_add, mac,
                        mul, rand_bf16, rand_operands, rand_product)

# ---- functional coverage (classified from the addends and docs/spec.md R3, R7 to R9)
COV_ROUND = Cover("R3: round-to-nearest-even position", {
    "exact":                lambda f: f["round"] == "exact" and f["special"] is None and not f["zeros"] and not f["cancel"],
    "below half":           lambda f: f["round"] == "below",
    "tie, kept even":       lambda f: f["round"] == "tie_even",
    "tie, rounded to even": lambda f: f["round"] == "tie_odd",
    "above half":           lambda f: f["round"] == "above",
    "carry into exponent":  lambda f: f["carry"],
}, at_least=10)
COV_ALIGN = Cover("R3: operand alignment and effective operation", {
    "add, d = 0":           lambda f: f["align"] == 0 and not f["eff_sub"],
    "add, d = 1..7":        lambda f: f["align"] is not None and 1 <= f["align"] <= 7 and not f["eff_sub"],
    "add, d = 8..10":       lambda f: f["align"] is not None and 8 <= f["align"] <= 10 and not f["eff_sub"],
    "add, d = 11":          lambda f: f["align"] == 11 and not f["eff_sub"],
    "add, d >= 12":         lambda f: f["align"] is not None and f["align"] >= 12 and not f["eff_sub"],
    "sub, d = 0":           lambda f: f["align"] == 0 and f["eff_sub"],
    "sub, d = 1":           lambda f: f["align"] == 1 and f["eff_sub"],
    "sub, d = 2..10":       lambda f: f["align"] is not None and 2 <= f["align"] <= 10 and f["eff_sub"],
    "sub, d >= 11":         lambda f: f["align"] is not None and f["align"] >= 11 and f["eff_sub"],
    "sub, exponent drops >= 4": lambda f: f["drop"] and f["eff_sub"],
}, at_least=10)
COV_RANGE = Cover("R8, R9: range limits and zeros", {
    "R8 overflow to inf":   lambda f: f["overflow"],
    "R9 flush to zero":     lambda f: f["ftz"],
    "R9 x + (-x) = +0":     lambda f: f["cancel"],
    "R9 +0 + +0":           lambda f: f["zeros"] == "++",
    "R9 +0 + -0":           lambda f: f["zeros"] == "+-",
    "R9 -0 + +0":           lambda f: f["zeros"] == "-+",
    "R9 -0 + -0":           lambda f: f["zeros"] == "--",
})
COV_SPECIAL = Cover("R7, R8: special operands", {
    "R7 NaN in":            lambda f: f["special"] == "nan_in",
    "R7 +inf + -inf":       lambda f: f["special"] == "inf_opp",
    "R8 inf + inf, same sign": lambda f: f["special"] == "inf_same",
    "R8 inf acc + finite":  lambda f: f["special"] == "inf_acc",
    "R8 finite + inf prod": lambda f: f["special"] == "inf_prod",
})


def _sample(acc, prod):
    f = add_features(acc, prod)
    for c in (COV_ROUND, COV_ALIGN, COV_RANGE, COV_SPECIAL):
        c.sample(f)


async def _apply(dut, acc, prod):
    _sample(acc, prod)
    dut.a.value = acc
    dut.b.value = prod
    await Timer(1, unit="ns")
    return int(dut.y.value)


async def _check_many(dut, pairs, label):
    errors = []
    n = 0
    for acc, prod in pairs:
        got = await _apply(dut, acc, prod)
        exp = add_bf16(acc, prod)
        n += 1
        if got != exp:
            errors.append(f"{acc:#06x} + {prod:#06x}: got {got:#06x} expected {exp:#06x}")
    assert not errors, f"{label}: {len(errors)}/{n} mismatches, first: {errors[:6]}"
    dut._log.info(f"{label}: {n} pairs match the reference")


@cocotb.test()
async def directed(dut):
    """Spec examples and adder boundaries (R3, R7, R8, R9)."""
    for acc, prod, exp, why in DIRECTED_ADD:
        got = await _apply(dut, acc, prod)
        assert got == exp, f"{why}: {acc:#06x} + {prod:#06x} got {got:#06x} expected {exp:#06x}"


@cocotb.test()
async def reachable(dut):
    """Every accumulator pattern x port-reachable products (R3, R7, R8, R9)."""
    rng = random.Random(61)
    pairs = ((acc, rand_product(rng)) for acc in range(1 << 16) for _ in range(8))
    await _check_many(dut, pairs, "reachable")


@cocotb.test()
async def random_full(dut):
    """Uniform BF16 x BF16, full range incl. overflow and FTZ (R3, R8, R9)."""
    rng = random.Random(62)
    await _check_many(dut, ((rand_bf16(rng), rand_bf16(rng)) for _ in range(200_000)),
                      "random_full")


@cocotb.test()
async def boundary(dut):
    """Cancellation, alignment, ties, overflow and FTZ edges (R3, R8, R9)."""
    rng = random.Random(63)
    await _check_many(dut, (boundary_add(rng) for _ in range(200_000)), "boundary")


@cocotb.test()
async def mac_chains(dut):
    """Sequential BF16 accumulation through the RTL adder (R3, R7, R8)."""
    rng = random.Random(64)
    steps = 0
    for chain in range(2000):
        fa, fb = rng.getrandbits(1), rng.getrandbits(1)
        acc_rtl = acc_ref = 0
        for _ in range(rng.randint(1, 64)):
            a, b, _, _ = rand_operands(rng)
            if rng.random() < 0.97:              # mostly finite chains
                while mac(0, a, b, fa, fb) & 0x7F80 == 0x7F80:
                    a, b, _, _ = rand_operands(rng)
            acc_rtl = await _apply(dut, acc_rtl, mul(a, b, fa, fb))
            acc_ref = mac(acc_ref, a, b, fa, fb)
            steps += 1
            assert acc_rtl == acc_ref, f"chain {chain}: got {acc_rtl:#06x} expected {acc_ref:#06x}"
    dut._log.info(f"mac_chains: 2000 chains, {steps} steps match the reference")


@cocotb.test()
async def functional_coverage(dut):
    """Closure of the functional-coverage groups above; fails on any bin under its minimum."""
    closure_report(dut._log)


def test_bf16_add():
    from cocotb_tools.runner import get_runner
    root = Path(__file__).resolve().parent.parent
    sim = os.getenv("SIM", "icarus")
    runner = get_runner(sim)
    runner.build(
        sources=[root / "rtl" / "bf16_add_s1.v", root / "rtl" / "bf16_add_s2.v",
                 root / "rtl" / "bf16_add.v"],
        hdl_toplevel="bf16_add",
        build_dir=root / "tb" / "sim_build" / f"bf16_add_{sim}",
        always=True,
        timescale=("1ns", "1ps"),
    )
    runner.test(hdl_toplevel="bf16_add", test_module="test_bf16_add",
                test_dir=Path(__file__).resolve().parent)


if __name__ == "__main__":
    test_bf16_add()
