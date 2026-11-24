# MANTIS feasibility gates (spec T5–T7)

Reference area: Tiny Tapeout sky130 2 × 2 slot, $334 \times 225 \approx 75{,}150$ µm² (**75,150 µm²**)
(1 × 1 tile 161 × 111.52 µm; Tiny Tapeout analog specs page, approximate). T7
pass threshold: datapath cell area $\le 65\,\%$ of this.

Method: `syn/synth.sh`, which runs Yosys 0.71 `synth -flatten` → `abc -liberty -D 20000`
to `sky130_fd_sc_hd__tt_025C_1v80`, with OpenLane don't-use cells excluded
(`lpflow*`, `probe*`, `diode*`, `*_0`). Timing is ABC `stime` on the mapped
netlist: liberty cell delays, no wires, no placement, **tt corner only**. It
is an estimate, not the OpenSTA signoff that T1 requires. Two figures are reported:
- **raw:** as mapped. Yosys's ABC flow does no buffering, so weak gates can
  drive large fanouts. The adder had an `a31oi_1` driving 26 loads with a
  2.7 ns transition time.
- **sized:** after ABC `buffer -p; upsize; dnsize`, approximating the
  resizer in the hardening flow. **Sized is the gate figure.**

The ABC `-D` target has no effect here (results are identical from 3 ns to
20 ns), so these numbers are not delay-optimized.

Sequential designs: flops are legalized to plain D flip-flops (sync
reset/enable become logic, as with `dfxtp`) and cut at the register
boundaries for timing. The reported path is the worst input/register →
register/output path; clock-to-Q (~0.3–0.4 ns) and setup (~0.1–0.2 ns) are
**not** included. Wire aliases are written as `buf_1` for ABC, which adds a
little pessimism to the delays.

## T5: FP8 multiplier (`rtl/fp8_mul.v`, `rtl/fp8_unpack.v`), 2026-11-23: PASS

| Check | Result |
|-------|--------|
| P4 exhaustive ($4 \times 65{,}536$ pairs vs `tb/mantis_ref.py`) | 262,144 / 262,144 match |
| Directed spec examples (`DIRECTED_MUL`, 21 cases) | pass |
| Mutation sanity (disable $0 \times \infty \to \mathrm{NaN}$) | caught: 8 mismatches |
| Cells / area | 212 cells, **1,185 µm²** mapped, 1,328 µm² sized (1.8 % of 2 × 2) |
| Critical path (comb., in → out) | raw 3.96 ns; **sized 3.50 ns** of 20 ns |

Interface: combinational `a, b, fmt_a, fmt_b → p[15:0]`. `p` is the exact
product as a BF16 bit pattern, with canonical NaN `7FC0`, signed $\infty$ and signed 0.

Implications for T6/T7:
- Four multipliers: $4 \times 1{,}185 \approx 4{,}740$ µm² (6.3 % of 2 × 2). Even the four-PE datapath
  spends little area on multiplication, so the BF16 adders and the 64 accumulator
  flops are what will decide T7.
- About 16 ns of the cycle is left for add and round. T6 found that a
  one-cycle MAC is tight; see below.
- The BF16 output encoding means the adder re-decodes the product. If the T6
  area is tight, an unpacked product interface (sign, exponent, 8-bit
  significand, class flags) would remove that redundant decode.

## T6: BF16 accumulator (`rtl/bf16_add.v`), 2026-11-23: PASS

Full-range BF16 adder (`acc + prod → acc`, RNE, specials, overflow, FTZ). No
reachable-range shortcuts are taken yet.

| Check | Result |
|-------|--------|
| Directed (`DIRECTED_ADD`, 24 spec examples and boundaries) | pass |
| Every accumulator pattern × 8 reachable products ($2^{16} \times 8 = 524{,}288$) | all match |
| Uniform BF16 × BF16, full range (200,000) | all match |
| Boundary generator: cancellation, alignment 0–12, ties, overflow, FTZ (200,000) | all match |
| Sequential MAC chains through the RTL adder (2,000 chains, 65,108 steps) | all match |
| Mutation: ties-away rounding | caught by all 5 tests |
| Mutation: alignment sticky bit dropped | caught; a directed sticky-tie case was added |
| Cells / area | 440 cells, 2,655 µm² mapped, **2,828 µm² sized** (3.8 % of 2 × 2) |
| Critical path | raw 13.4 ns; **sized 10.4 ns** of 20 ns |

Combined multiply → add in one cycle (`syn/mac_comb.v`, synthesis only):
641 cells, **4,280 µm² sized**, critical path **13.4 ns sized** (raw 16.6 ns).

### What T6 means for T7

**Timing.** A single-cycle MAC uses 67 % of the period at tt with no wires.
The slow corner (ss, 100 °C, 1.60 V) is typically $1.5\times$ to $2\times$ slower, which would put
it at about 20–27 ns. **A single-cycle MAC is not safe.** The fix is structural
and costs no throughput: each accumulator updates only once every 4 clocks
(R10), so the MAC can be pipelined.
- Register the product between the multiplier and the adder: stages of
  3.5 ns and 10.4 ns. The adder stage still needs a slow-corner check.
- If needed, split the adder too (align | add + normalize | round). In the
  four-PE design, the 4-cycle update interval also allows multicycle paths.
- The adder's longest chain is magnitude compare → align shift → 12-bit
  add → leading-zero count → normalize shift → round increment → exponent
  checks. A near/far-path split or comparing exponents only would shorten it
  if needed.

**Drain latency (R11).** A 2–3 stage MAC plus staging gives about 3–5 cycles
from the 4th WRITE to commit in the four-PE design. In the shared-MAC design the
last product of a step (C11) starts 3 cycles after the step's first product,
which gives about 5–7 cycles. Both are within the 8-cycle target. T7 confirms it.

**Area projection** (sized cells; flip-flop `dfxtp_1` = 20.0 µm²):

| Organization | Arithmetic | 64 accumulator FFs | Staging and pipeline FFs, muxes, control (est.) | Total | % of 2 × 2 |
|---|---|---|---|---|---|
| (a) four PEs | $4 \times 4{,}280 = 17{,}120$ | 1,281 | ~2,000 | **~20,400 µm²** | ~27 % |
| (b) one shared MAC | 4,280 | 1,281 | ~2,500 | **~8,100 µm²** | ~11 % |

Both organizations look comfortably under the 65 % T7 threshold. Four PEs
leave about 38 percentage points of headroom for the controller, readout and
the JTAG stretch. If timing allows, the shared MAC frees about 16 % of the slot.
These are projections; T7 measures them.

## T7: 2 × 2 datapath (`rtl/mantis_stage.v` + organization), 2026-11-23: PASS (both)

Scope: staging, CLEAR/format registers, issue, a pipelined MAC, four
accumulators and `busy`. READ/`p`/`uo_out` and JTAG are excluded. The test
port `acc[63:0]` = `{C11, C10, C01, C00}`.

| | (a) four PEs `mantis_dp_pe4` | (b) shared MAC `mantis_dp_shared` |
|---|---|---|
| Pipeline | issue → 4× multiply → product regs → 4× add → commit | issue → operand snapshot → 1 product/clk → add → commit (round-robin) |
| Drain latency (R11) | **2 cycles** | **5 cycles** |
| Tests `tb/test_datapath.py` (R1, R3, R5–R11, R13, R14, P6, P10–P12) | 6/6 pass | 6/6 pass |
| Flip-flops | 166 | 148 |
| Cells / mapped area | 2,741 / 18,792 µm² | 1,095 / 8,865 µm² |
| **Sized area / % of 2 × 2** | **19,703 µm² / 26.2 %** | **9,071 µm² / 12.1 %** |
| **Critical path (sized, tt)** | **11.5 ns**: product reg → adder → acc | **12.3 ns**: acc reg → 4:1 acc mux → adder → acc |
| Slack at 20 ns (tt, synthesis) | +8.5 ns before clk-to-Q/setup | +7.7 ns before clk-to-Q/setup |

Test content:
- Spec examples R1, R3 and R5–R9 at the command level.
- Drain measured cycle by cycle, with the accumulators stable while
  idle (P12).
- $4 \times 250$ back-to-back groups in all format pairs (R10).
- 150 random $K \le 48$ products with specials and NOP/READ/`in_valid=0` cycles
  interleaved (P6).
- CLEAR at each of 8 cycles after issue and during 1-, 2- and 3-byte partial
  groups (R13, P10).
- Reset at each of 8 cycles after issue (R14).

Mutation sanity:
- CLEAR not flushing the last pipeline valid: caught by clear_flush and
  reset_flush, in both designs.
- Wrong multiplier operand (pe4) and swapped accumulator tags (shared):
  caught by spec_examples, streaming and random_traffic.

### Gate verdict

Both organizations pass every T7 criterion. Area is far below the 65 %
threshold, tt synthesis slack is positive at 20 ns, drain is $\le 8$ cycles, and
R1–R3, R10 and R11 pass.

### Remaining risk: slow corner

The worst stage is the adder (11.5–12.3 ns at tt, no wires). At a typical
$1.5\times$ to $2\times$ ss derating that is about 17 to 25 ns, which is marginal. The library
for this corner (`sky130_fd_sc_hd__ss_100C_1v60.lib`) isn't installed, so
this is not measured. The fix exists in both organizations at no throughput
cost, because each accumulator is written once per 4 clocks:
- split `bf16_add` into 2 pipeline stages (align/add | normalize/round), or
- in (a), treat product → acc as a 2-cycle path (products and accumulators
  are stable for 4 cycles), if the hardening flow accepts a multicycle SDC.

### Choosing an organization

- **(a) four PEs:** simplest control, shortest drain (2), 0.8 ns faster.
  At 26 % of the slot it still leaves ~39 percentage points under the 65 %
  line for the controller, readout and the JTAG stretch.
- **(b) shared MAC:** less than half the area. At 9,071 µm² it is ~25 % of
  a 1 × 2 slot ($161 \times 225 \approx 36{,}200$ µm²), so a 2-tile submission becomes
  plausible. Four PEs would be ~54 % of 1 × 2 before the controller and JTAG.

**Decision (2026-11-23): (b) shared MAC, `rtl/mantis_dp_shared.v`.** Chosen
for half the area and the option of a 1 × 2 submission. `rtl/mantis_dp_pe4.v`
stays as a reference prototype only (not updated for the ss corner). The
slow-corner check below changed the adder to two pipeline stages. Still open
before RTL freeze: whether T2 moves from 2 × 2 to 1 × 2 (a spec change).

## Slow-corner check (ss_100C_1v60), 2026-11-23: PASS after adder split

Library: `sky130_fd_sc_hd__ss_100C_1v60.lib` from open_pdks build
`sky130-f6eeac7d…` (ciel-releases), installed in `~/eda/pdk/sky130_fd_sc_hd/`
(see `SOURCE.txt` there). The netlist is mapped once at tt; `syn/synth.sh` then
times that same netlist at tt and at ss. In this library ss is
**$1.9\times$ to $2.0\times$ slower** than tt.

### Before: single-stage adder (T6/T7 RTL)

| Block | tt sized | ss sized | 20 ns at ss |
|---|---|---|---|
| `fp8_mul` | 3.5 ns | 6.7 ns | pass |
| `bf16_add` (one stage) | 10.4 ns | 20.0 ns | **fail** (no slack) |
| `mantis_dp_shared` (acc mux → adder → acc) | 12.3 ns | 24.3 ns | **fail** |
| `mantis_dp_pe4` (reference only) | 11.5 ns | 22.6 ns | **fail** |

### Fix: two-stage BF16 adder

`bf16_add` is split into `rtl/bf16_add_s1.v` (specials, magnitude order,
align, add) and `rtl/bf16_add_s2.v` (normalize, round, pack). A 38-bit bundle
passes between them. `rtl/bf16_add.v` now chains the two with no register,
so the T6 suite (`tb/test_bf16_add.py`, ~990k vectors) tests exactly the logic
the datapath uses. It passes unchanged.

`mantis_dp_shared` registers the bundle between the stages, giving pipeline
M → A1 → A2. Each accumulator is read in A1 and written 2 cycles later; the
same accumulator is next read 4 cycles after its previous read, so there is
no hazard. **Drain latency is now 6 cycles** (R11 target 8).

| Block | Area (sized, tt) | tt sized | ss sized | ss raw |
|---|---|---|---|---|
| `bf16_add_s1` | 1,889 µm² | 6.2 ns | 12.1 ns | 20.9 ns |
| `bf16_add_s2` | 1,164 µm² | 4.6 ns | 9.1 ns | 12.0 ns |
| **`mantis_dp_shared`** | **10,501 µm²** (189 FFs) | **6.9 ns** | **14.0 ns** | 18.3 ns |

The shared datapath's ss critical path is acc register → 4:1 accumulator
mux → `bf16_add_s1` → bundle register. Slack at ss is about **+6.0 ns**
before clock-to-Q/setup (about 1 ns at ss) and wires.

Updated T7 figures for the chosen organization: **10,501 µm²**, $10{,}501 / 75{,}150 \approx 14.0\,\%$ of 2 × 2
(about 29 % of a 1 × 2 slot, $161 \times 225 \approx 36{,}200$ µm²), drain 6 cycles. All 6
datapath tests pass. Area grew by 1,430 µm², mostly the 41 bundle and tag
flip-flops.

Mutation sanity on the new stage: CLEAR not flushing `qv` is caught by
clear_flush and reset_flush.

Caveats:
- These are synthesis estimates: no wires, no clock skew, and ABC's sizing
  stands in for the flow's resizer.
- T1 (hardening-flow STA at every corner) remains the authority.

## Milestone 4: controller and top level (`rtl/tt_um_lucas_rigsby_mantis.v`), 2026-11-23: PASS

`tt_um_lucas_rigsby_mantis` wraps `mantis_dp_shared` and adds:
- the read pointer `p` (READ: $p \leftarrow (p + 1) \bmod 8$, cleared by CLEAR and reset),
- `uo_out` as a combinational byte mux of registered `p` (resolves the open item on registered versus combinational `uo_out`),
- `uio_out = {0, 00, busy, 0000}` and `uio_oe = 8'h90`,
- inert JTAG pins (R25).

Verification:

| Check | Result |
|-------|--------|
| `tb/test_top.py` (8 pin-level tests) | 8/8 pass |
| R1 bytes `98 41 B0 41 2C 42 48 42` via READ, p wraps 7 → 0 | pass |
| p and uo_out vs a model, 6,000 random cycles incl. reset/CLEAR/invalid | pass |
| READ during computation (60 trials) | results unchanged |
| P1 static pins checked on every cycle of every test | pass |
| NaN reads `C0 7F` and persists (P3); drain at the pins = 6 cycles | pass |
| R25: asynchronous random tck/tms/tdi (and uio_in[4], [7]) noise; 2,542 cycles identical to a quiet run, tdo = 0 | pass |
| $4 \times 200$ back-to-back groups read from the pins (R10) | pass |
| Formal `formal/tt_um_lucas_rigsby_mantis.sby`: P1, P5, P6 by k-induction; 3 non-vacuity covers reached | pass |
| Mutants: p wraps at 6 (formal fails); in_valid gated by tck&tms&tdi (only jtag_inert_noisy fails); byte order swapped (5 tests fail) | all caught |

Synthesis (complete design, no JTAG):

| | Value |
|---|---|
| Cells / flip-flops | 1,247 / 191 |
| Area, sized | **11,047 µm²**: 14.7 % of 2 × 2 (≈ 75,150 µm²), ~30.5 % of 1 × 2 (≈ 36,200 µm²) |
| Critical path, sized | tt **6.9 ns**; ss_100C_1v60 **13.6 ns** (raw 17.2 ns): acc → 4:1 mux → `bf16_add_s1` → bundle register |

The controller adds about 550 µm² and does not touch the critical path.
Pin-to-register and register-to-pin paths (the Tiny Tapeout mux and pad
delays) are not modelled here; they are part of T1.

## Tile target changed to 1 × 2 (2026-11-23)

Spec T2 is now 2 tiles (1 × 2, $161 \times 225 \approx 36{,}200$ µm²), approved by the
project owner. Basis: the complete baseline design is 11,047 µm² sized,
about 30.5 % of the slot. If the JTAG stretch is added (the original requirements budgeted
roughly 7,500–11,300 µm²), it would land around 50–60 %. Policy: drop the
stretch rather than grow the tile count. The T7 gate above was judged
against 2 × 2 and is left as recorded; the chosen design would also have
passed against 65 % of 1 × 2.

## Post-route timing and the accumulator select (2026-11-23)

The first Tiny Tapeout hardening run
([run 45316669657](https://github.com/lucas-rigsby/tt-mantis-fp8-matmul/actions/runs/45316669657),
commit `32dd1bb`) failed setup at all three slow corners:

| Corner | Setup slack | Violating endpoints |
|---|---|---|
| `max_ss_100C_1v60` | $-0.944$ ns | 3 |
| `nom_ss_100C_1v60` | $-0.732$ ns | 2 |
| `min_ss_100C_1v60` | $-0.555$ ns | 2 |

All violations end in `q_sum[11:9]` and start at a synthesis copy of `ptag`.
The path is the one estimated above as 13.6 ns at ss (acc → 4:1 mux →
`bf16_add_s1` → bundle register). After routing it is about 21 ns. The select
net drives 16 `mux4` cells through one buffer, with a slew of 1.22 ns and a
`mux4` select-to-output delay of 1.67 ns at ss. The synthesis estimate does
not model either effect.

**Decision:** select the accumulator in stage M and register it as `pacc`
next to `prod`; stage A1 adds `pacc` and `prod`. An accumulator read for
product $j$ in cycle $t_0 + j$ commits at edge $t_0 + j + 3$, and the next read
of it is no earlier than cycle $t_0 + 4 + j$, so the change is exact.
Latency, drain (6 cycles) and all requirements are unchanged; no test or
property was modified.

| | Before (`32dd1bb`) | After (`35026d4`) |
|---|---|---|
| Synthesis, sized | 11,047 µm², 191 FFs | 11,451 µm², 206 FFs |
| Synthesis critical path, ss | 13.6 ns | 11.7 ns |
| Post-route setup slack, worst ss | $-0.944$ ns | **$+3.347$ ns** |
| Post-route setup slack, worst tt | $+9.617$ ns | $+11.69$ ns |
| Post-route hold slack, worst (ff) | $+0.129$ ns | $+0.116$ ns |
| Standard-cell area, utilization | 17,690 µm², 51.6 % | 17,939 µm², 52.4 % |
| DRC, LVS, antenna, precheck, gate-level tests | pass | pass |

After run
[45324496603](https://github.com/lucas-rigsby/tt-mantis-fp8-matmul/actions/runs/45324496603)
the achievable clock at the slow corner is about 60 MHz. The remaining slew
warnings at tt are on the `cnt[1]` select net, which now feeds the stage-M
multiplexer and has more than 8 ns of slack.
