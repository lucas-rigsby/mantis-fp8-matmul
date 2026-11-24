"""Minimal functional coverage for cocotb testbenches (no dependencies).

Copy this file next to your tests (e.g. tb/funcov.py). Usage:

    from funcov import Cover, closure_report

    cls = Cover("result class", {
        "zero":      lambda a, b, p: (p & 0x7FFF) == 0,
        "saturated": lambda a, b, p: (p & 0x7FFF) == 0x7F7F,
    }, at_least=10)

    cls.sample(a, b, p)            # in your driver/monitor, every transaction

    @cocotb.test()                 # define LAST in the module: cocotb runs tests in order
    async def functional_coverage(dut):
        closure_report(dut._log)   # logs every group; fails on any hole

A bin is a predicate over whatever you pass to sample(). Crosses are just
bins whose predicate combines conditions ("overflow and negative").
"""

_ALL = []


class Cover:
    def __init__(self, name, bins, at_least=1):
        self.name, self.bins, self.at_least = name, dict(bins), at_least
        self.hits = {b: 0 for b in self.bins}
        _ALL.append(self)

    def sample(self, *args, **kwargs):
        for b, pred in self.bins.items():
            if pred(*args, **kwargs):
                self.hits[b] += 1

    def holes(self):
        return [b for b, n in self.hits.items() if n < self.at_least]

    def percent(self):
        return 100.0 * (len(self.bins) - len(self.holes())) / max(1, len(self.bins))

    def lines(self):
        out = [f"{self.name}: {self.percent():.0f}% ({len(self.bins) - len(self.holes())}/"
               f"{len(self.bins)} bins with >= {self.at_least} hits)"]
        for b, n in self.hits.items():
            out.append(f"    {'HOLE ' if n < self.at_least else '     '}{b:<32} {n}")
        return out


def closure_report(log=None, require_closed=True):
    lines, holes = [], []
    for c in _ALL:
        lines += c.lines()
        holes += [f"{c.name}: {h}" for h in c.holes()]
    for l in lines:
        (log.info if log else print)(l)
    if require_closed:
        assert not holes, "functional coverage holes: " + "; ".join(holes)
    return holes
