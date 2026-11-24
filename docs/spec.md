# MANTIS (`tt_um_lucas_rigsby_mantis`): specification

**Revision:** 0.6 (2026-11-23; top module renamed from `tt_um_mantis` to `tt_um_lucas_rigsby_mantis` for a unique name on the shuttle. 0.5: T2 tile target changed from 2 × 2 to 1 × 2)
**Top module:** `tt_um_lucas_rigsby_mantis` · **Target:** Tiny Tapeout, Sky130 `sky130_fd_sc_hd`, 50 MHz, 2 tiles (1 × 2) (changed from 2 × 2 on 2026-11-23 after T7 and Milestone 4 synthesis)

MANTIS is a 2 × 2 output-stationary FP8 matrix-multiply accelerator. It computes
$C = AB$ for $A$ ($2 \times K$), $B$ ($K \times 2$), $C$ ($2 \times 2$), $K \ge 1$. Inputs are OCP FP8 (E4M3FN or
E5M2, selectable independently for A and B); the four accumulators and outputs are
BF16, rounded RNE after every accumulation. The host streams one byte per clock;
four WRITEs make one reduction step. The host tiles larger matrices in software.

Requirements constrain **port-observable behaviour only**. The number of
physical multipliers/adders (four PEs, one shared time-multiplexed MAC, or
anything else) is a microarchitecture choice settled by the feasibility gates
T5–T7.

The JTAG-style TAP is a **stretch goal**. The baseline submission
reserves its pins and keeps them inert (R25); the TAP requirements R16–R24,
P7, P9 and T4 apply only if the stretch is built (Annex S).

Status words: MUST/SHALL normative; SHOULD recommended (deviations documented);
**(assumed)** a provisional default to revisit.

## Interfaces

| Port | Dir | Width | Clock | Description |
|------|-----|-------|-------|-------------|
| clk | in | 1 | — | rising-edge clock, $\le 50$ MHz |
| rst_n | in | 1 | clk | synchronous, active low |
| ena | in | 1 | — | ignored (asserted when the design is selected) |
| ui_in[7:0] | in | 8 | clk | WRITE: operand byte. CLEAR: `ui_in[0]`=fmt_a, `ui_in[1]`=fmt_b, `[7:2]` ignored |
| uio_in[0] | in | 1 | clk | `in_valid` |
| uio_in[2:1] | in | 2 | clk | `cmd` |
| uio_in[3] | in | 1 | async | reserved: JTAG `tck` (inert in baseline, R25) |
| uio_in[5] | in | 1 | async | reserved: JTAG `tms` (inert in baseline, R25) |
| uio_in[6] | in | 1 | async | reserved: JTAG `tdi` (inert in baseline, R25) |
| uio_in[4], uio_in[7] | in | 2 | — | ignored (pins are outputs) |
| uo_out[7:0] | out | 8 | clk | `rdata`: result byte selected by pointer `p` |
| uio_out[4] | out | 1 | clk | `busy` |
| uio_out[7] | out | 1 | — | reserved: JTAG `tdo`; constant 0 in baseline (R25) |
| uio_out[6:5], uio_out[3:0] | out | 6 | — | constant 0 |
| uio_oe[7:0] | out | 8 | — | constant `8'h90` |

Handshake: **valid-only, no back-pressure.** A command is accepted at a rising
edge when `in_valid=1` and `rst_n=1`. The design accepts a command on every
edge, including while `busy=1`.

### Commands

| `cmd` | Name | Effect when accepted |
|-------|------|----------------------|
| `2'b00` | WRITE | store `ui_in` in staging slot $n$; $n \leftarrow n + 1$; the write to slot 3 issues one reduction step and sets $n \leftarrow 0$ |
| `2'b01` | CLEAR | accumulators $\leftarrow$ `16'h0000`; `fmt_a ← ui_in[0]`; `fmt_b ← ui_in[1]`; $n \leftarrow 0$; $p \leftarrow 0$; all outstanding steps and partial groups discarded; `busy ← 0` |
| `2'b10` | READ | $p \leftarrow (p + 1) \bmod 8$; nothing else changes |
| `2'b11` | NOP | no effect |

Staging order for reduction index $k$ (first complete group after CLEAR is $k = 0$):
slot 0 = `A[0][k]`, slot 1 = `A[1][k]`, slot 2 = `B[k][0]`, slot 3 = `B[k][1]`.

Result byte map (little-endian within each BF16 word):

| p | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| uo_out | C00[7:0] | C00[15:8] | C01[7:0] | C01[15:8] | C10[7:0] | C10[15:8] | C11[7:0] | C11[15:8] |

`uo_out` reflects the current `p`; a READ or CLEAR sampled at an edge changes
`p` at that edge, and `uo_out` shows the new byte after that edge. `uo_out`
SHOULD be a combinational mux of registered `p` and the accumulators unless
timing requires a registered byte (externally visible timing is the same).

## Clocks, resets, crossings

| Domain | Clock | Frequency | Reset |
|--------|-------|-----------|-------|
| core | clk | $\le 50$ MHz | rst_n, synchronous, active low |

Crossings (baseline): **none.** `tck/tms/tdi` are asynchronous but unused
in the baseline. The host is assumed to generate `clk` and drive
`cmd/in_valid/ui_in` synchronously to it **(assumed)**.

## Number formats and arithmetic

| Format | Layout | Bias | Specials |
|--------|--------|------|----------|
| E4M3FN | s.eeee.mmm | 7 | max finite $\pm 448$; no $\infty$; NaN = `0x7F`, `0xFF`; subnormals (min $2^{-9}$) |
| E5M2 | s.eeeee.mm | 15 | max finite $\pm 57344$; $\pm\infty$ = `0x7C`/`0xFC`; NaN = `0x7D–0x7F`, `0xFD–0xFF`; subnormals (min $2^{-16}$) |
| `BF16` | s.eeeeeeee.mmmmmmm | 127 | $\pm\infty$; canonical NaN `16'h7FC0`; output subnormals flushed to zero |

`fmt_a=0/1` selects E4M3FN/E5M2 for every A operand; `fmt_b` likewise for B.

Per step:

```math
C_{ij} \leftarrow \mathrm{RNE}_{\mathrm{BF16}}\left( C_{ij} + A_{ik} \, B_{kj} \right)
```

The product is formed exactly
($\le 8$ significant bits, exponent within BF16 normal range). Rounding happens on
every accumulation; no wider running sum is kept.

Special values: NaN operand $\to$ NaN; $\infty \times 0 \to \mathrm{NaN}$;
$\infty \times x \to \pm\infty$ for finite nonzero $x$ (sign XOR);
$\pm 0 \times x \to$ zero with sign XOR for finite $x$; $(+\infty) + (-\infty) \to \mathrm{NaN}$;
$\infty + x \to \infty$ (same sign) for finite $x$; $\infty + \infty \to \infty$ for equal signs; NaN accumulator stays NaN until CLEAR/reset.
Every NaN reads as `16'h7FC0`.

Signed zero: $x + (-x) = +0$; $(+0) + (-0) = +0$; $(-0) + (-0) = -0$.

**Overflow boundary.** Rounding uses IEEE RNE with unbounded
exponent; a result whose exact magnitude satisfies $\lvert x \rvert \ge 2^{128} - 2^{119}$
(halfway above the max finite `0x7F7F`; the tie rounds to even, which is $\infty$) becomes $\pm\infty$.

**Reachability (derived, informs verification).** From the ports:
- $\lvert A_{ik} B_{kj} \rvert \le 57344^2 < 2^{32}$, so once $\lvert C \rvert \ge 2^{41}$ every product is below half an ulp
  and $\lvert C \rvert$ never exceeds $2^{42}$. **Finite overflow to $\infty$ is unreachable**; $\infty$ arises
  only from E5M2 $\infty$ operands.
- Every product and every accumulator value is a multiple of $2^{-32}$, so the
  smallest nonzero $\lvert C \rvert$ is $2^{-32}$. **FTZ is unreachable.**
- Accumulators start at $+0$ and $x + (-x) = +0$, so **an accumulator never
  holds $-0$.**

The reference model implements the full definition. The RTL MAY omit logic
for cases unreachable from the ports, as long as port behaviour matches
**(assumed)**. Those cases are checked at unit level only when the
corresponding unit claims to implement them.

## Requirements

| ID | Requirement |
|----|-------------|
| R1 | **Matrix function.** After CLEAR and $K \ge 1$ complete steps, once `busy=0`, reading $p = 0, \ldots, 7$ returns the four step-by-step BF16 results. Example (E4M3FN, $`A = \left[\begin{smallmatrix} 1 & 2 \\ 3 & 4 \end{smallmatrix}\right]`$, $`B = \left[\begin{smallmatrix} 5 & 6 \\ 7 & 8 \end{smallmatrix}\right]`$): WRITE `38 44 4A 4C 40 48 4E 50` → bytes `98 41 B0 41 2C 42 48 42` ($`C = \left[\begin{smallmatrix} 19 & 22 \\ 43 & 50 \end{smallmatrix}\right]`$ = `4198, 41B0, 422C, 4248`). |
| R2 | **Exact products.** Every finite FP8×FP8 product enters accumulation unrounded. Example: E4M3FN $448 \times 448 = 200704$ (`7E × 7E`) from $+0$ → `16'h4844`. |
| R3 | **RNE every step.** Example: products $16 \times 16$, $1 \times 1$, $1 \times 1$ into one accumulator → 256, 256, 256 = `16'h4380` (not 258). |
| R4 | **E4M3FN decode.** Normals and subnormals decode correctly; `0x7F`/`0xFF` are NaN. Example: `0x01 × 0x38` → `16'h3B00` ($2^{-9}$). |
| R5 | **E5M2 decode.** Normals, subnormals, $\pm\infty$, NaN decode correctly. Example: CLEAR `ui_in=0x03` (both E5M2), `0x3C × 0x7B` → `16'h4760` (57344). |
| R6 | **Mixed formats.** fmt_a and fmt_b select formats independently. Example: CLEAR with `ui_in=0x02` (A=E4M3FN, B=E5M2), A=`0x38`, B=`0x3C` → `16'h3F80`. |
| R7 | **NaN.** NaN operands, $\infty \times 0$ and $(+\infty) + (-\infty)$ give `16'h7FC0`, which persists through later steps until CLEAR/reset. Example: E4M3FN `0x7F × 0x38` then `0x38 × 0x38` → `16'h7FC0`. |
| R8 | **Infinity and overflow.** $\infty$ signs and $\infty + x$ for finite $x$ follow the arithmetic section; overflow follows the stated boundary (unreachable from ports, so checked at unit level only). Example: CLEAR `ui_in=0x03`, `0x7C × 0x3C` ($+\infty \times 1$) → `16'h7F80`; then `0x38 × 0x38` ($0.5 \times 0.5$) → still `16'h7F80`. |
| R9 | **Zero and FTZ.** Signed-zero and FTZ rules hold ($-0$ and FTZ unreachable from ports). Example: $+1$ then $-1$ → `16'h0000`; E4M3FN `0x80 × 0x38` from $+0$ → `16'h0000`. |
| R10 | **Throughput.** One accepted command per clock with no loss; a step can be issued every 4 clocks indefinitely. Example: 1000 back-to-back groups (4000 consecutive WRITEs) match the reference. |
| R11 | **Busy and drain.** If the 4th WRITE of a step is sampled at edge $t_0$, `busy=1` after $t_0$ and stays high while any issued step is uncommitted; `busy=0` no later than after edge $t_0 + 8$ when no further step is issued **(8-cycle target assumed, confirmed by T7)**. |
| R12 | **Readout.** `uo_out` is the byte selected by `p` per the map; READ increments $p$ modulo 8 ($7 \to 0$) and changes no accumulator. Reads during `busy=1` return an unspecified byte and don't disturb computation. |
| R13 | **CLEAR.** CLEAR sets accumulators to `16'h0000`, loads fmt_a/fmt_b, sets $n = 0$, $p = 0$, `busy=0`; no step issued before the CLEAR edge updates an accumulator afterwards; a partial group is discarded. Example: 3 WRITEs, CLEAR, then 4 WRITEs (1,1,1,1) → all C = `16'h3F80`. |
| R14 | **Reset.** An edge with `rst_n=0` sets accumulators to $+0$, fmt_a = fmt_b = 0, $n = 0$, $p = 0$, `busy=0`, invalidates outstanding steps; commands are ignored while `rst_n=0`. |
| R15 | **Static pins and idle.** `uio_oe=8'h90`; `uio_out[6:5]` and `uio_out[3:0]` are 0; NOP and `in_valid=0` cycles change no command-controlled state (n, p, fmt, accumulators, issue). |
| R16 | **(stretch)** TAP 16-state controller — Annex S. |
| R17 | **(stretch)** 4-bit instruction register — Annex S. |
| R18 | **(stretch)** TDO timing — Annex S. |
| R19 | **(stretch)** IDCODE `32'h1F8A20FF` (provisional) and BYPASS — Annex S. |
| R20 | **(stretch)** 20-cell boundary register — Annex S. |
| R21 | **(stretch)** SAMPLE/PRELOAD — Annex S. |
| R22 | **(stretch)** EXTEST with Policy A (only entered when `busy=0`) — Annex S. |
| R23 | **(stretch)** STATUS register — Annex S. |
| R24 | **(stretch)** ACCUM snapshot; for the R1 example `64'h4248_422C_41B0_4198` — Annex S. |
| R25 | **Inert JTAG pins (baseline).** Without the TAP: `uio_out[7]` (tdo) is constant 0; any toggling of `uio_in[3]`, `uio_in[5]`, `uio_in[6]` (tck/tms/tdi) in any pattern and phase changes no state and no output; `uio_oe` stays `8'h90`. Example: run R1 with tck/tms/tdi driven by random bits every cycle → identical bytes, tdo=0 throughout. Replaced by R16–R24 if the stretch is built. |

## Derived properties (for formal / assertions)

- P1 `uio_oe == 8'h90`; `uio_out[6:5]`, `uio_out[3:0]` are 0 (and `uio_out[7]` is 0 in the baseline).
- P2 `busy` is 1 whenever at least one issued step is uncommitted.
- P3 A NaN accumulator reads `16'h7FC0` and stays NaN until CLEAR or reset.
- P4 The product unit matches the reference for every operand pair (exhaustive simulation baseline, $4 \times 65{,}536 = 262{,}144$ pairs).
- P5 `n` and `p` change only on accepted WRITE (n), READ (p), CLEAR or reset.
- P6 NOP and `in_valid=0` cycles cause no command-controlled state change.
- P7 **(stretch)** Five TMS-high TCK rising edges reach Test-Logic-Reset from any TAP state.
- P8 Outside EXTEST, core outputs drive the pins; JTAG pin activity never changes accelerator state (baseline: never changes anything, R25).
- P9 **(stretch)** TDO changes only within 3 clk cycles after a detected TCK falling edge.
- P10 No step issued before a CLEAR updates an accumulator after that CLEAR.
- P11 Complete steps commit in issue order, without loss or duplication, and each accumulator's updates happen in ascending $k$.
- P12 With `busy=0`, accumulators are stable unless a step commits, CLEAR, or reset occurs.

## Budget

| ID | Target |
|----|--------|
| T1 | No setup/hold violations at 20 ns (50 MHz) in the Tiny Tapeout Sky130 hardening flow, `sky130_fd_sc_hd`, nominal reported corner. |
| T2 | Fits 2 tiles (1 × 2, ≈ 161 × 225 µm) with no DRC/LVS errors. Basis: complete baseline design synthesizes to ≈ 11,050 µm² (≈ 30 % of 1 × 2; docs/feasibility.md). If the JTAG stretch doesn't fit in 1 × 2, drop the stretch before growing the tile count (revisit with the user). |
| T3 | Gate-level simulation passes R1, R3, R5, R7 examples (plus IDCODE and ACCUM if the stretch is built). |
| T4 | **(stretch)** JTAG works at $f_{\mathrm{TCK}} = f_{\mathrm{clk}} / 8$, 50 % duty, varied phase vs clk. |
| T5 | **Gate 1: FP8 multiplier prototype.** One dual-format FP8×FP8 → exact product unit, synthesized with Yosys to `sky130_fd_sc_hd`, passes exhaustive P4, and reports cell area and STA critical path at 20 ns (tt corner). |
| T6 | **Gate 2: BF16 accumulator prototype.** One BF16 add-and-round-RNE unit (product + accumulator → accumulator, with specials) passes differential tests vs the reference, reports cell area and critical path at 20 ns (tt corner). |
| T7 | **Gate 3: complete 2 × 2 datapath prototype.** Staging + arithmetic + 4 accumulators + issue/commit/busy (no JTAG), in both (a) four parallel PEs and (b) one shared MAC at 1 MAC/cycle, each passing R1–R3, R10, R11. Pass if synthesized cell area $\le 65\,\%$ of the 4-tile placeable area **(assumed threshold)**, synthesis STA slack $\ge 0$ at 20 ns, and drain $\le 8$ cycles; the chosen organization is recorded before RTL freeze. |

Gates T5 → T6 → T7 run in order, before the controller and integration RTL is
frozen. If T7 fails for both organizations, stop and revisit the architecture or
area target with the user (planning allocation: datapath ≈ 60–70 % of area).

## Out of scope

- Output tiles other than 2 × 2; on-chip K-deep storage; host tiling.
- `FP16`/`FP32` accumulation; non-RNE rounding; stochastic rounding.
- MX/microscaling or scale factors; nonzero initial C or bias loading.
- NaN payload propagation (all NaNs canonical).
- Back-pressure, interrupts, input FIFO.
- Full IEEE 1149.1 compliance or package-pad boundary scan.
- JTAG/TAP in the baseline submission (stretch: Annex S).

## Open items

- **Tile allocation:** closed: 1 × 2 (T2). Confirm the slot is available on the chosen shuttle.
- **Host clocking:** host generates clk, assumed; confirm board integration.
- **Pipeline schedule:** closed by T7.
- **EXTEST policy:** Policy A, stretch only.
- **JTAG synchronizer timing:** stretch only; to be fixed in the microarch doc if built.
- **IDCODE:** `32'h1F8A20FF` provisional; manufacturer field `11'h07F` is not a JEDEC assignment.
- **uo_out registered vs combinational:** combinational preferred; decided by T1.
- **Area split:** from T5–T7 numbers.

## Annex S — JTAG-style TAP (stretch; normative only if built)

When built, R25 is replaced by the following; all baseline requirements still hold.

- **Synchronization.** tck/tms/tdi each pass through a 2-FF synchronizer into
  `clk`; TCK rise/fall are detected in the clk domain; there is no TCK clock domain.
  clk must run; $f_{\mathrm{TCK}} \le f_{\mathrm{clk}} / 8$; TCK high and low phases each last $\ge 4$ clk periods.
- **R16 TAP.** Standard 16-state controller advancing on detected TCK rise
  using synchronized TMS; 5 TMS-high rises reach Test-Logic-Reset; `rst_n=0`
  forces Test-Logic-Reset (no TRST).
- **R17 IR.** 4 bits, LSB first; Capture-IR loads `4'b0001`; Test-Logic-Reset
  selects IDCODE. Opcodes: EXTEST `0000`, SAMPLE/PRELOAD `0001`, IDCODE `0010`,
  STATUS `1000`, ACCUM `1001`, BYPASS `1111`; all others act as BYPASS.
- **R18 TDO.** In Shift-IR/Shift-DR, TDO = LSB of the selected register, changing only
  after a detected TCK fall, within 3 clk cycles, and stable before the next TCK rise.
  Elsewhere TDO = 0; never tri-stated.
- **R19 IDCODE/BYPASS.** BYPASS is 1 bit and captures 0. IDCODE = `32'h1F8A20FF`
  (version 1, part `F8A2`, manufacturer `07F` provisional, LSB 1); 32 shifts after
  TAP reset return it LSB first.
- **R20 Boundary register.** 20 cells, cell 0 nearest TDO: 0–7 `uo_out[0..7]` (out),
  8 `busy` (out), 9–16 `ui_in[0..7]` (in), 17–19 `uio_in[0..2]` (in). Capture-DR:
  inputs capture synchronized pin values, outputs capture the core-driven values.
  Update-DR transfers shift → update latch. `rst_n=0` and Test-Logic-Reset clear the latches.
- **R21 SAMPLE/PRELOAD.** Capture/Shift/Update as above; core and pins operate normally;
  latches don't drive pins. Example: `ui_in=8'hA5` at Capture-DR shifts out `A5` in cells 9–16.
- **R22 EXTEST (Policy A).** Entered only with `busy=0` (host's responsibility).
  `uo_out` $\leftarrow$ latches 0–7, `uio_out[4]` $\leftarrow$ latch 8; inputs keep capturing. Core outputs
  return within 1 clk after leaving EXTEST. Example: preload `3C` into cells 0–7, select
  EXTEST → `uo_out=8'h3C`; without preload → `8'h00`.
- **R23 STATUS.** 16 bits, captures `{4'b0, nan[3:0], p[2:0], n[1:0], fmt_b, fmt_a, busy}`
  (nan[0]=C00 … nan[3]=C11); Update-DR has no effect.
- **R24 ACCUM.** 64 bits, captures `{C11, C10, C01, C00}` coherently in one snapshot,
  bit 0 = C00[0], LSB first; capture/shift never change accumulators, p or n.
