# MANTIS bring-up plan

This plan covers the first tests of a fabricated `tt_um_lucas_rigsby_mantis`
on the Tiny Tapeout demo board. The test that runs on the board,
`test_bringup.py`, is the same file that passes in simulation, and its expected
results come from the reference model through `vectors.py`.

## Files

| File | Purpose |
|---|---|
| `export_vectors.py` | Writes `vectors.py` from `tb/mantis_ref.py` (`make vectors`) |
| `vectors.py` | 58 computations: the 8 spec examples (R1, R3 to R9), 48 random ones with $K$ from 1 to 16 and about 20 % special values, and two streams with $K = 64$. Each entry holds the format bits, the WRITE bytes and the 8 expected result bytes |
| `test_bringup.py` | Smoke check, every vector, and an at-speed variant. Runs under cocotb (`CocotbPins`) and on the RP2040 (`BoardPins`) |
| `log.md` | Created on the bench: one line per run and per failure |

## Before the chip arrives

| Step | Command | Pass criterion | Status |
|---|---|---|---|
| 1. Export vectors | `make vectors` | `vectors.py` written; regenerate whenever the reference model changes | done, 58 vectors |
| 2. RTL simulation | `make bringup-sim` | `bringup_smoke`, `bringup_vectors` and `bringup_at_speed` pass | pass |
| 3. Gate-level simulation | Tiny Tapeout repo, `test/`: `make GATES=yes` with the netlist from the GDS run (the CI job `gl_test` does this) | the same three tests pass on the routed netlist | pass in CI |
| 4. Board script check | Copy both files to a demo board with any project and run `import test_bringup` | the module imports under MicroPython | not done |

`BoardPins` uses the tt-micropython-firmware SDK (`DemoBoard`, `RPMode`,
`shuttle.<project>.enable()`, `clock_project_once`, `clock_project_PWM`,
`reset_project`, `uio_oe_pico`). It has not run on hardware. Check these names
against the firmware version on the board before step 4 and adjust the driver
if they differ; the test logic above the driver does not change.

## On the bench

The physical steps (power, flashing, probing) are done by hand. Every result
goes into `log.md` with the date, board revision, chip or shuttle ID and
ambient temperature.

1. **Board setup.** Update the demo board to the latest firmware for the
   shuttle, then copy the files:

   ```bash
   mpremote cp bringup/test_bringup.py bringup/vectors.py :
   ```

2. **Smoke check, power and selection.** The board powers up and selects the
   project with `tt.shuttle.tt_um_lucas_rigsby_mantis.enable()`. Supply current
   from a USB power meter is recorded with the project selected and in reset.
   Signoff estimates 1.07 mW for the design at 50 MHz, so a large jump in current
   after selection points to a board or selection problem.

3. **Functional at a manually stepped clock.** The RP2040 steps the clock once
   per command, so the inputs are stable around every edge.

   ```bash
   mpremote exec "import test_bringup; test_bringup.main('tt_um_lucas_rigsby_mantis')"
   ```

   Pass: `smoke: pass` and `vectors, manual clock: 58 of 58 pass`. The smoke
   check reads all eight result bytes as `00` after reset, with `busy` and
   `tdo` low (R14, R15). The first vector is the spec example and must read
   `98 41 B0 41 2C 42 48 42` (R1).

4. **Pin mapping check, only if step 3 fails.** Compare the wrong bytes with
   the expected ones. If the same bits are wrong in every vector, check the
   pinout in `info.yaml` and `uio_oe_pico` before suspecting the design.

5. **At-speed characterization.** Each command still needs one RP2040-driven
   edge, but after every issuing WRITE the driver runs the project clock from
   the RP2040 PWM for about 2 ms. The issued step passes through the
   multiplier and both adder stages on these fast edges, so this exercises the
   critical paths at the chosen frequency.

   ```bash
   mpremote exec "import test_bringup; test_bringup.main('tt_um_lucas_rigsby_mantis', [1_000_000, 10_000_000, 25_000_000, 50_000_000])"
   ```

   Record pass counts per frequency in `log.md`. Signoff gives a worst-case
   setup slack of $+3.35$ ns at the slow corner, so every frequency up to 50 MHz
   should pass, and the limit at the slow corner is about

   ```math
   f_{\max} = \frac{1}{20\ \mathrm{ns} - 3.35\ \mathrm{ns}} \approx 60\ \mathrm{MHz} .
   ```

   A failure below 50 MHz is a finding, not an expected limit. Results above
   50 MHz depend on the demo board's clock routing as much as on the design.

6. **Repeat on a second chip** if one is available. Differences between chips
   point to process variation; identical failures point to the design or the
   setup.

## When something fails

| Observation | Suspect | Check |
|---|---|---|
| Nothing responds | project not selected, wrong name, power | the `enable()` name, board LEDs, supply current |
| Smoke fails, bytes not `00` after reset | reset not reaching the design, or reset released before a clock edge | step `reset_project` and the clock by hand; reset is synchronous and needs edges while `rst_n` is low |
| Every vector wrong in the same bits | pin mapping or `uio_oe_pico` | which bits differ, against the pinout in `info.yaml` |
| Fails with the manual clock, passes in gate-level simulation | protocol timing on the board | single-step with `clock_project_once` and read the pins after each edge |
| Passes slowly, fails at speed | timing or board signal integrity | compare the failing frequency with the slow-corner slack; probe the clock |
| The same few vectors always wrong | a design bug the tests missed | reproduce in RTL simulation with exactly those inputs, then add the case to `DIRECTED` in `export_vectors.py` |
| Random, intermittent failures | power, clock glitches or reset | longer reset, slower clock, a different USB supply |

Each failure gets a line in `log.md` with the symptom, the root cause and the
flow step that should have caught it (specification, reference model, test,
formal, timing or signoff).
