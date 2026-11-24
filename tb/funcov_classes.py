"""Input classification for functional coverage (docs/spec.md Formats, R3 to R9).

Every function here works from operand bit patterns and the format rules in
the specification, never from DUT outputs. Integer arithmetic only, so the
classifiers are cheap enough to sample every vector of the exhaustive and
differential suites.
"""
E4M3FN, E5M2 = 0, 1


def fp8_class(x, fmt):
    """'zero', 'sub', 'normal', 'max', 'inf' or 'nan' for an FP8 byte (R4, R5)."""
    mag = x & 0x7F
    if fmt == E4M3FN:
        if mag == 0x7F:
            return "nan"
        if mag == 0x7E:
            return "max"                         # 448
        e = mag >> 3
    else:
        if mag > 0x7C:
            return "nan"
        if mag == 0x7C:
            return "inf"
        if mag == 0x7B:
            return "max"                         # 57344
        e = mag >> 2
    if mag == 0:
        return "zero"
    return "sub" if e == 0 else "normal"


def bf16_class(x):
    """'zero', 'normal', 'inf' or 'nan' for a BF16 pattern (subnormals read as zero, FTZ)."""
    e, m = (x >> 7) & 0xFF, x & 0x7F
    if e == 0xFF:
        return "inf" if m == 0 else "nan"
    return "zero" if e == 0 else "normal"


def _bf16_int(x):
    """Finite BF16 as (sign, integer significand, exponent of its LSB)."""
    e, m = (x >> 7) & 0xFF, x & 0x7F
    if e == 0:
        return x >> 15, 0, 0
    return x >> 15, 128 | m, e - 127 - 7


def add_features(acc, prod):
    """Spec-level features of one accumulation acc + prod (R3, R7, R8, R9).

    Returns a dict with:
      special  None for finite + finite, else one of 'nan_in', 'inf_opp',
               'inf_same', 'inf_acc', 'inf_prod'
      zeros    sign pattern when both addends are zero ('++', '+-', '-+', '--'), else None
      eff_sub  True when finite non-zero addends have opposite signs
      align    exponent difference of two non-zero finite addends, else None
      round    'exact', 'below', 'tie_even', 'tie_odd', 'above' (RNE position)
      carry    rounding up carries into the exponent
      cancel   exact sum is zero from non-zero addends
      drop     exponent of the sum is at least 4 below the larger addend
      overflow rounded magnitude exceeds the BF16 maximum (R8 overflow)
      ftz      non-zero exact sum below the smallest normal, flushed (R9)
    """
    ca, cp = bf16_class(acc), bf16_class(prod)
    f = {"special": None, "zeros": None, "eff_sub": False, "align": None, "round": None,
         "carry": False, "cancel": False, "drop": False, "overflow": False, "ftz": False}
    if ca == "nan" or cp == "nan":
        f["special"] = "nan_in"
        return f
    if ca == "inf" and cp == "inf":
        f["special"] = "inf_opp" if (acc ^ prod) >> 15 else "inf_same"
        return f
    if ca == "inf" or cp == "inf":
        f["special"] = "inf_acc" if ca == "inf" else "inf_prod"
        return f
    sa, ma, ea = _bf16_int(acc)
    sp, mp, ep = _bf16_int(prod)
    if ma == 0 and mp == 0:
        f["zeros"] = ("-" if sa else "+") + ("-" if sp else "+")
        f["round"] = "exact"
        return f
    if ma and mp:
        f["eff_sub"] = sa != sp
        f["align"] = abs(ea - ep)
    lo = min(e for m, e in ((ma, ea), (mp, ep)) if m)
    va = (-ma if sa else ma) << (ea - lo) if ma else 0
    vp = (-mp if sp else mp) << (ep - lo) if mp else 0
    total = va + vp
    if total == 0:
        f["cancel"] = True
        f["round"] = "exact"
        return f
    mag = abs(total)
    bits = mag.bit_length()
    big_exp = max(e + m.bit_length() for m, e in ((ma, ea), (mp, ep)) if m)
    f["drop"] = (lo + bits) <= big_exp - 4
    shift = bits - 8                              # keep 8 significant bits
    if shift <= 0:
        f["round"] = "exact"
        kept, exp_lsb = mag, lo
    else:
        kept, rem = mag >> shift, mag & ((1 << shift) - 1)
        half = 1 << (shift - 1)
        if rem == 0:
            f["round"] = "exact"
        elif rem < half:
            f["round"] = "below"
        elif rem > half:
            f["round"] = "above"
        else:
            f["round"] = "tie_odd" if kept & 1 else "tie_even"
        if f["round"] in ("above", "tie_odd"):
            kept += 1
            f["carry"] = kept == 256
        exp_lsb = lo + shift
    if f["carry"]:
        kept, exp_lsb = kept >> 1, exp_lsb + 1
    unbiased = exp_lsb + 7 + (kept.bit_length() - 8)
    f["overflow"] = unbiased > 127
    f["ftz"] = unbiased < -126
    return f


# ---------------------------------------------------------------- command level
WRITE, CLEAR, READ, NOP = 0, 1, 2, 3
_ACC_CLASSES = ("nan", "+inf", "-inf", "zero", "+finite", "-finite")


def acc_class(x):
    """Spec class of a BF16 accumulator value from the reference model (R1, R7 to R9)."""
    c = bf16_class(x)
    if c in ("nan", "zero"):
        return c
    return ("-" if x >> 15 else "+") + ("inf" if c == "inf" else "finite")


class CommandCoverage:
    """Functional coverage of the command stream (R6, R10 to R14, P6).

    `step()` is called once per clock with the inputs applied at that edge. A
    small model of the specified command semantics (group position n, read
    pointer p, edges since the last issuing WRITE) classifies each command;
    no DUT signal is read.
    """

    def __init__(self, Cover, top=False):
        on = lambda k: (lambda e: k in e)
        self.formats = Cover("R6: formats loaded by CLEAR", {
            f"A {'E5M2' if fa else 'E4M3FN'}, B {'E5M2' if fb else 'E4M3FN'}":
                (lambda v: lambda e: e.get("clear_fmt") == v)((fa, fb))
            for fa in (0, 1) for fb in (0, 1)})
        self.issue = Cover("R10, R11: issue spacing", {
            "first issue after CLEAR or reset": lambda e: e.get("issue") == "first",
            "back-to-back (4 edges)":          lambda e: e.get("issue") == 4,
            "with idle cycles (> 4 edges)":     lambda e: isinstance(e.get("issue"), int) and e["issue"] > 4,
        })
        self.clear = Cover("R13, P10: CLEAR timing", {
            **{f"CLEAR {k} edges after issue": (lambda k: lambda e: e.get("clear_after") == k)(k) for k in range(1, 7)},
            "CLEAR >= 7 edges after issue": lambda e: (e.get("clear_after") or 0) >= 7,
            **{f"CLEAR with n = {k}": (lambda k: lambda e: e.get("clear_n") == k)(k) for k in (1, 2, 3)},
        })
        self.reset = Cover("R14: reset timing", {
            **{f"reset {k} edges after issue": (lambda k: lambda e: e.get("reset_after") == k)(k) for k in range(1, 7)},
            "reset with a partial group": lambda e: (e.get("reset_n") or 0) > 0,
        })
        self.idle = Cover("P6: commands with no effect on the computation", {
            "in_valid = 0, cmd WRITE": lambda e: e.get("idle") == ("invalid", WRITE),
            "in_valid = 0, cmd CLEAR": lambda e: e.get("idle") == ("invalid", CLEAR),
            "in_valid = 0, cmd READ":  lambda e: e.get("idle") == ("invalid", READ),
            "in_valid = 0, cmd NOP":   lambda e: e.get("idle") == ("invalid", NOP),
            "NOP":                     lambda e: e.get("idle") == ("valid", NOP),
            "idle inside a partial group": lambda e: e.get("idle_in_group", False),
            "idle while a step is in flight": lambda e: e.get("idle_in_flight", False),
        })
        self.result = Cover("R1, R7, R8, R9: accumulator result class (reference model)", {
            c: (lambda c: lambda e: c in e.get("results", ()))(c) for c in _ACC_CLASSES})
        self.length = Cover("R1, R10: reduction length K", {
            "K = 1":       lambda e: e.get("K") == 1,
            "K = 2..8":    lambda e: e.get("K") is not None and 2 <= e["K"] <= 8,
            "K = 9..64":   lambda e: e.get("K") is not None and 9 <= e["K"] <= 64,
            "K >= 65":     lambda e: (e.get("K") or 0) >= 65,
        })
        self.groups = [self.formats, self.issue, self.clear, self.reset, self.idle, self.result, self.length]
        if top:
            self.read = Cover("R12, R13, R14: read pointer", {
                "READ wraps p 7 -> 0":         lambda e: e.get("read_from") == 7,
                "READ while a step is in flight": lambda e: e.get("read_in_flight", False),
                "CLEAR with p != 0":           lambda e: (e.get("clear_p") or 0) != 0,
                "reset with p != 0":           lambda e: (e.get("reset_p") or 0) != 0,
            })
            self.jtag = Cover("R25, P8: reserved JTAG pins active", {
                f"{name} high while a step is in flight":
                    (lambda bit: lambda e: e.get("in_flight", False) and (e.get("jtag", 0) >> bit) & 1)(bit)
                for name, bit in (("tck", 3), ("tms", 5), ("tdi", 6))})
            self.groups += [self.read, self.jtag]
        self.n = 0
        self.p = 0
        self.since_issue = None
        self.k = 0

    DRAIN = 6                                   # spec drain bound is 8; 6 for the shared MAC

    def _emit(self, e):
        for g in self.groups:
            g.sample(e)

    def results(self, C):
        """Sample the reference result matrix of a finished computation."""
        self._emit({"results": {acc_class(C[i][j]) for i in (0, 1) for j in (0, 1)}})

    def step(self, valid, cmd, din, rst_n=1, jtag=0):
        e = {"jtag": jtag}
        in_flight = self.since_issue is not None and self.since_issue < self.DRAIN
        e["in_flight"] = in_flight
        if not rst_n:
            if self.since_issue is not None:
                e["reset_after"] = self.since_issue + 1
            e["reset_n"], e["reset_p"] = self.n, self.p
            self._end_stream(e)
            self.n = self.p = 0
            self.since_issue = None
        elif not valid or cmd == NOP:
            e["idle"] = ("invalid", cmd) if not valid else ("valid", NOP)
            e["idle_in_group"] = self.n > 0
            e["idle_in_flight"] = in_flight
        elif cmd == CLEAR:
            e["clear_fmt"] = (din & 1, (din >> 1) & 1)
            if self.since_issue is not None:
                e["clear_after"] = self.since_issue + 1
            e["clear_n"], e["clear_p"] = self.n, self.p
            self._end_stream(e)
            self.n = self.p = 0
            self.since_issue = None
        elif cmd == READ:
            e["read_from"] = self.p
            e["read_in_flight"] = in_flight
            self.p = (self.p + 1) % 8
        elif cmd == WRITE:
            if self.n == 3:
                if self.since_issue is None or self.k == 0:
                    e["issue"] = "first"
                else:
                    e["issue"] = self.since_issue + 1
                self.k += 1
                self.n = 0
                self.since_issue = -1
            else:
                self.n += 1
        if self.since_issue is not None:
            self.since_issue += 1
        self._emit(e)

    def _end_stream(self, e):
        if self.k:
            e["K"] = self.k
        self.k = 0
