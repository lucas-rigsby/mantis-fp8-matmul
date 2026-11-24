# MANTIS signoff record

| Item | Value |
|---|---|
| Design | `tt_um_mantis` (MANTIS FP8 matrix multiplier) |
| Front-end commit | RTL at `75c23a1` (this repository); tests, coverage and this record in the commit that adds this file |
| Back-end commit | `35026d4` ([tt-mantis-fp8-matmul](https://github.com/lucas-rigsby/tt-mantis-fp8-matmul)); `src/` is byte-identical to `rtl/` at `75c23a1` |
| Hardening run | [actions run 45324496603](https://github.com/lucas-rigsby/tt-mantis-fp8-matmul/actions/runs/45324496603) |
| Date | 2026-11-23 |
| Shuttle | Tiny Tapeout Sky130, `tt-gds-action@ttsky26d`, PDK `sky130A`, `sky130_fd_sc_hd`, $1 \times 2$ tiles |
| Front-end tools | Yosys 0.71+50, Verilator 5.055 (devel), Icarus Verilog 14.0 (devel), SymbiYosys v0.71-7, cocotb 2.1.0.dev0 |
| Back-end tools | LibreLane 3.0.14 (Tiny Tapeout app `main 7d2d2ef5`) |

**Decision: not ready for tapeout.** Every check passes or is waived with
approval except row 17: the bring-up vectors and plan do not exist yet. See
[Open items](#open-items).

## Front-end checks

| # | Check | Command | Result | Status |
|---|---|---|---|---|
| 1 | Requirements traced | `spec_trace.py --strict` | 44 IDs, 29 tested or proven, 15 gaps: R16 to R24, P7, P9 and T4 (JTAG stretch, not built) and T1 to T3 (back-end; the tool does not read the hardening results, which are rows 10, 12 and 13 below) | WAIVED (W2, W3) |
| 2 | Lint | `make lint` | Verilator `-Wall`: no warnings for `tt_um_mantis` or `mantis_dp_pe4` | PASS |
| 3 | Regression | `make test` | 4 suites, 5 pytest items, all pass: `test_fp8_mul` 10.9 s, `test_bf16_add` 60.4 s, `test_datapath` (both datapaths) 4.4 s, `test_top` 2.0 s. 3 + 6 + 7 (per datapath) + 11 cocotb tests including the closure tests, 0 failures | PASS |
| 4 | Formal | `make formal` | `tt_um_mantis_prove`: basecase and induction pass (smtbmc boolector). `tt_um_mantis_cover`: 3 cover statements reached, 0 unreached | PASS |
| 5 | Code coverage | Verilator `--coverage` on all four suites, merged with `cov_report.py --min 100` (no `make cov` target exists; run from a scratch runner) | Before waivers: line 100 %, branch 100 %, expression 1 hole, toggle 63 holes on the submitted files. With the 13 waivers in `tb/coverage_waivers.txt`: 100.0 % of 2,313 points, 115 waived | WAIVED (W1) |
| 6 | Functional coverage | `functional_coverage` test, last in each suite (`tb/funcov.py`, bins in `tb/funcov_classes.py` and the test modules) | 16 groups, 119 bins, every bin hit; a deliberately empty bin was confirmed to fail the suite. See [Functional coverage](#functional-coverage) | PASS |
| 7 | Mutation | `mutate.py` on the 7 submitted files, checks `test` and `formal`, 40 sampled mutants of 246 | 35 of 38 killed (92 %), 2 stillborn. `test` killed 35, `formal` 3 (all also killed by `test`). The 3 survivors are equivalent mutants, see [Mutation survivors](#mutation-survivors) | PASS |
| 8 | CDC and latches | `domains.py --top tt_um_mantis --strict` | 1 domain (`posedge clk`), 0 crossings, 0 latches | PASS |
| 9 | FPGA timing | `make fpga` | Not prototyped on an FPGA | N/A |

## Back-end checks

| # | Check | Command | Result | Status |
|---|---|---|---|---|
| 10 | Physical signoff | `ll_summary.py runs/wokwi --check` on the `GDS_logs` artifact | Worst setup slack: ss +3.347 ns (`max_ss_100C_1v60`), tt +11.69 ns, ff +13.48 ns; 0 violations. Worst hold slack +0.116 ns (`min_ff_n40C_1v95`); 0 violations. Routing DRC 0, Magic DRC 0, LVS 0, antenna 0, latches 0, illegal overlaps 0. KLayout DRC is skipped in the flow and run by precheck (row 13) | PASS |
| 11 | Warnings reviewed | `tt_tool.py --print-warnings` not available locally; `runs/wokwi/warning.log` reviewed instead | See [Warnings](#warnings); each is explained | PASS |
| 12 | Gate-level sim | CI job `gl_test`, `make GATES=yes` | 8 tests, 8 pass, 0 fail | PASS |
| 13 | Shuttle precheck | CI job `precheck` | Pass, including Magic DRC, KLayout FEOL, BEOL, offgrid and the pin, boundary and power-pin checks | PASS |
| 14 | Achievable clock | period minus worst setup slack | ss: $20 - 3.347 = 16.65$ ns, about 60 MHz, above `clock_hz` = 50 MHz with 3.3 ns of margin | PASS |
| 15 | Power | `ll_summary.py` power section | 1.07 mW total (0.77 mW internal, 0.30 mW switching, 36 nW leakage), worst IR drop 60 µV. Default switching activity, no VCD. The specification sets no power budget | PASS |
| 16 | Docs | `info.yaml`, `docs/info.md` | Pinout matches `tt_um_mantis.v` and the specification interface table. The worked example in `docs/info.md` is the `readout_example` test, which passes at RTL and gate level | PASS |
| 17 | Bring-up ready | `make vectors bringup-sim` | No target, no vectors, no `bringup/plan.md` | FAIL |

The CI `viewer` job of the same run failed while deploying to GitHub Pages
("Fetching artifact metadata failed"). It publishes the layout viewer and
does not affect any check above.

### Size

| Measure | Value |
|---|---|
| Die | $161 \times 225.76$ µm, 36,347 µm² |
| Standard cells | 17,939 µm², 52.4 % of the 34,255 µm² core (filler cells excluded) |
| Flip-flops | 206 |
| Added by the flow | 269 timing-repair buffers (the flow reports 186 hold buffers), 29 clock buffers, tap cells |

### Slow-corner timing history

The first hardening run (commit `32dd1bb`,
[run 45316669657](https://github.com/lucas-rigsby/tt-mantis-fp8-matmul/actions/runs/45316669657))
failed setup at all three ss corners, worst $-0.944$ ns. The path went from
the accumulator index `ptag` through the 4:1 accumulator multiplexer into
adder stage 1. Commit `75c23a1` moves the multiplexer into stage M and
registers the selected accumulator as `pacc`. The change is exact and leaves
latency unchanged; `docs/feasibility.md` gives the argument and the before and
after figures.

### Functional coverage

Bins are classified from the applied inputs and the rules in
`docs/spec.md`, never from DUT outputs. The adder classifier in
`funcov_classes.add_features` was checked against the reference model on
300,000 additions (rounding direction, overflow, flush to zero and
cancellation all agreed).

| Suite | Group | Bins | Minimum hits |
|---|---|---|---|
| `test_fp8_mul` | R4, R5: operand class (zero, subnormal, normal, maximum, NaN, and inf for E5M2) per format and sign | 22 | 1 |
| | R6: format pair | 4 | 1 |
| | R2, R7, R8, R9: product class (NaN operand, $\infty \times 0$, $\infty \times$ finite, zero products, signed zeros, smallest and largest products, sign combinations) | 17 | 1 |
| `test_bf16_add` | R3: rounding position (exact, below half, tie kept even, tie rounded up, above half, carry into the exponent) | 6 | 10 |
| | R3: alignment distance by effective add or subtract, including $d = 11$, $d \ge 12$ and cancellation by 4 or more exponent steps | 10 | 10 |
| | R8, R9: overflow, flush to zero, exact cancellation, the four signed-zero sums | 7 | 1 |
| | R7, R8: NaN in, $+\infty + (-\infty)$, same-sign infinities, infinity in either operand | 5 | 1 |
| `test_datapath` (both datapaths) and `test_top` | R6: formats loaded by CLEAR | 4 | 1 |
| | R10, R11: issue spacing (first, back-to-back, with idle cycles) | 3 | 1 |
| | R13, P10: CLEAR 1 to 6 and 7 or more edges after an issue, CLEAR with $n = 1, 2, 3$ | 10 | 1 |
| | R14: reset 1 to 6 edges after an issue, reset with a partial group | 7 | 1 |
| | P6: `in_valid = 0` with each command, NOP, idle cycles inside a group and while a step is in flight | 7 | 1 |
| | R1, R7, R8, R9: result class from the reference model (NaN, $\pm\infty$, zero, positive and negative finite) | 6 | 1 |
| | R1, R10: reduction length $K$ (1, 2 to 8, 9 to 64, 65 or more) | 4 | 1 |
| `test_top` only | R12, R13, R14: READ wrapping 7 to 0, READ while a step is in flight, CLEAR and reset with $p \ne 0$ | 4 | 1 |
| | R25, P8: each reserved JTAG input high while a step is in flight | 3 | 1 |

Closing the holes found on the first run added stimulus but changed no RTL:

| Hole | Added |
|---|---|
| Reset during a partial group (datapath and top) | `test_datapath.reset_flush`: 1, 2 or 3 bytes written, reset, then a full group must give only the new result (R14) |
| CLEAR at 6 edges and reset at 2 to 6 edges after an issue, at the pins | `test_top.flush_at_pins`: CLEAR or reset 1 to 7 edges after an issue, all 8 result bytes read as zero, and still zero 12 cycles later (R13, R14, P10) |
| NaN, $\pm\infty$ and zero results at the pins | `test_top._traffic` now checks every result against the reference model (it only compared the quiet and noisy runs before); `test_top.special_results_at_pins` reads $+\infty$, $-\infty$ and $+0$ through `uo_out` (R8, R9) |

### Mutation survivors

| Mutant | Why it is equivalent |
|---|---|
| `mantis_stage.v:49`, `&&` to `\|\|` in the operand-slot write enable | The `case (n)` still writes only slot $n$, the slot that has not been written yet in the current group. An extra write puts a stray byte there, and the real WRITE replaces it before the slot is read. Slots below $n$ are never touched |
| `bf16_add_s1.v:43`, shift clamp `5'd11` to `5'd12` | Used only when $d > 11$. With either shift the significand lies entirely below the guard and round bits, and the sticky bit is 1 because the hidden bit is 1 (or 0 for both when the operand is zero). The rounded result is identical |
| `bf16_add_s1.v:43`, `d > 8'd11` to `d >= 8'd11` | Differs only at $d = 11$, where both arms give a shift of 11 |

Formal kills only controller mutants, because the proofs cover the pin
behaviour and the arithmetic is verified by simulation (exhaustive multiplier,
differential adder).

### Warnings

| Warning | Count | Explanation |
|---|---|---|
| Max slew violations | 333 at `max_ss`, 11 at `nom_tt` | At tt, all 11 are the `cnt[1]` select net (0.887 ns against a 0.75 ns limit), which feeds the stage-M multiplexers. At ss the 0.75 ns limit is exceeded by up to a few ps on many nets. Setup slack, computed with these slews, is +3.35 ns at ss. Tiny Tapeout does not treat slew as an error |
| Max fanout on 10 clock-tree leaf buffers, 11 to 13 against a limit of 10 | 10 | Built by clock-tree synthesis for 206 flip-flops. Hold passes at every corner |
| 6 input pins without antenna gate information; 6 disconnected pins | 1 each | `uio_in[3]` to `uio_in[7]` and `ena`, unused by design (R25; `ena` is ignored). Critical disconnected pins: 0 |
| 15 output pins without antenna diffusion information | 1 | `uio_out[0..3, 5..7]` and `uio_oe[7:0]`, driven by tie cells as constants (R15, P1) |
| `RSZ-0020` 2 floating nets | 1 | `VPWR` and `VGND` in the logical netlist; the power grid connects them. Floating pins: 0 |
| `STA-1140` library already exists | 18 | Liberty files loaded again for each STA corner; informational |
| `DRT-0349` `LEF58_ENCLOSURE` without `CUTCLASS` | 10 | PDK technology LEF rule the router does not parse; DRC is checked independently by Magic and KLayout (rows 10 and 13) |
| `PNR_SDC_FILE`, `SIGNOFF_SDC_FILE` not defined | 2 | Tiny Tapeout's generic SDC: one clock on `clk` at `CLOCK_PERIOD` = 20 ns |
| `VSRC_LOC_FILES` not given | 1 | IR-drop analysis uses default supply locations; the 60 µV result is an estimate |
| KLayout DRC not reported; long-wire threshold not set | 2 | Both skipped in the flow by the Tiny Tapeout configuration. KLayout DRC is covered by precheck |
| `VPWR`, `VGND` declared as power pins | 2 | Informational |

## Open items

| Row | Item | Flow step | Skill |
|---|---|---|---|
| 17 | No bring-up vectors or plan | Bring-up preparation | `/bringup` |

## Waivers

All three waivers were approved by the project owner.

| ID | Row | Waiver | Reason | Approval |
|---|---|---|---|---|
| W1 | 5 | 115 code-coverage points in 13 groups, listed below | Every point is constant by construction or is not logic | approved by lucas-rigsby on 2026-11-23 |
| W2 | 1 | Trace gaps R16 to R24, P7, P9, T4 | JTAG stretch goal from Annex S, not built in the baseline. The pins are reserved and inert, which R25 and P8 cover | approved by lucas-rigsby on 2026-11-23 |
| W3 | 1 | Trace gaps T1 to T3 | Back-end requirements. The evidence is rows 10, 12 and 13, which the trace tool does not read. T1 passes (no violations at any corner); T2 passes (fits $1 \times 2$, 0 DRC, 0 LVS); T3 passes (gate-level tests include the R1 example) | approved by lucas-rigsby on 2026-11-23 |

W1 waiver groups (`tb/coverage_waivers.txt`):

| Points | Reason |
|---|---|
| `spec_val[5:0]` in `bf16_add_s1`, `bf16_add_s2`, `mantis_dp_shared` (wire and `q_spec_val` register) | Special results are only $\pm 0$, $\pm\infty$ (`7F80`, `FF80`) and NaN `7FC0`, whose low 6 bits are 0 |
| `m_big[7]` | Hidden bit, tied to 1 |
| `big_al[2:0]`, `big_al[10]` | `{m_big, 3'b000}`: zero padding and the hidden bit |
| `bias[6:4]`, `bias[2:0]` in `fp8_unpack` | Bias is 7 (`0000111`) or 15 (`0001111`); only bit 3 changes |
| `e_sub[6:4]`, `e_sub[2:0]` in `fp8_unpack` | $1 - \mathit{bias}$ is $-6$ (`1111010`) or $-14$ (`1110010`); only bit 3 changes |
| `uio_out` bits other than 4 | Constant 0 by specification (R15, R25, P1) |
| `uio_oe[7:0]` | Constant `8'h90` by specification (R15, P1) |
| `ena` | Held at 1 by Tiny Tapeout while the design is selected; unused |
| `_unused` reduction in `tt_um_mantis` | Lint sink for unused inputs, not logic |
| All points in `bf16_add.v` | Combinational wrapper kept for the T6 prototype; not part of the submitted design |
