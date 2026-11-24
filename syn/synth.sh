#!/usr/bin/env bash
# Prototype synthesis for the feasibility gates (docs/spec.md T5-T7).
#
#   syn/synth.sh <top> <rtl files...>        (results in syn/out/<top>/)
#
# Yosys -> sky130_fd_sc_hd, mapped at tt_025C_1v80 (override with LIB=...),
# then ABC `stime` critical-path estimates of that netlist at tt and, if the
# library sits next to $LIB, at ss_100C_1v60. Requires the OSS CAD Suite
# environment (yosys, yosys-abc, python3).
# NOTE: this is a synthesis-level estimate (no placement, no wire parasitics,
# no OpenSTA). Final T1 timing comes from the Tiny Tapeout hardening flow.
set -euo pipefail
LIB=${LIB:-$HOME/eda/pdk/sky130_fd_sc_hd/sky130_fd_sc_hd__tt_025C_1v80.lib}
PERIOD_PS=${PERIOD_PS:-20000}
# Cells the Tiny Tapeout / OpenLane sky130 flow treats as dont_use.
DONT_USE="-dont_use *lpflow* -dont_use *probe* -dont_use *diode* -dont_use *_0"
TOP=$1; shift
OUT=$(cd "$(dirname "$0")" && pwd)/out/$TOP
mkdir -p "$OUT"

READS=""
for f in "$@"; do READS+="read_verilog -sv $(cd "$(dirname "$f")" && pwd)/$(basename "$f"); "; done

yosys -q -l "$OUT/yosys.log" -p "
  $READS
  synth -top $TOP -flatten
  dfflegalize -cell \$_DFF_P_ 01
  abc -liberty $LIB -D $PERIOD_PS $DONT_USE
  opt_clean -purge
  setundef -zero
  design -save mapped
  expose -evert-dff
  write_blif -gates -impltf -buf sky130_fd_sc_hd__buf_1 A X $OUT/${TOP}.blif
  design -load mapped
  dfflibmap -liberty $LIB $DONT_USE
  hilomap -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO
  tee -o $OUT/stat.txt stat -liberty $LIB
  write_verilog -noattr $OUT/${TOP}_netlist.v
"

# Flip-flops are legalized to plain $_DFF_P_ (sync reset/enable become logic,
# as with sky130 dfxtp); for the timing BLIF `expose -evert-dff` turns each
# flop into an input (Q) and output (D), so ABC `stime` reports the worst
# input/register -> register/output combinational path (clk-to-q and setup
# not included). ABC crashes on .latch-based BLIFs, hence the eversion.
# Liberty-based critical path estimate with ABC on the mapped netlist.
# raw: netlist exactly as mapped (no buffering; weak gates may drive large fanout).
# sized: after ABC buffering + gate sizing, approximating the repair the
# hardening flow's resizer performs. The sized figure is the gate estimate.
# Cut any flops `expose` left as .latch: Q becomes an input, D an output.
python3 - "$OUT/${TOP}.blif" <<'PY'
import sys
p = sys.argv[1]; out = []; ins = []; outs = []
for line in open(p):
    if line.startswith(".latch"):
        f = line.split(); outs.append(f[1]); ins.append(f[2])
    else:
        out.append(line)
i = next(k for k, l in enumerate(out) if l.startswith(".inputs"))
extra = [".inputs " + " ".join(ins) + "\n"] if ins else []
extra += [".outputs " + " ".join(dict.fromkeys(outs)) + "\n"] if outs else []
open(p, "w").writelines(out[:i] + extra + out[i:])
PY
area=$(grep -E "Chip area" "$OUT/stat.txt" | awk '{print $NF}')
cells=$(awk '$3=="cells"{print $1; exit}' "$OUT/stat.txt")
ffs=$( (grep -E "sky130_fd_sc_hd__df" "$OUT/stat.txt" || true) | awk '{n+=$1} END{print n+0}')
echo "$TOP: cells=$cells ffs=$ffs area_um2=$area (mapped at $(basename "$LIB" .lib | sed 's/.*__//'))"

# Time the same mapped netlist at each corner (tt and, if installed, ss).
# stime areas cover combinational cells only; sized total = mapped total + sizing delta.
LIBDIR=$(dirname "$LIB")
for CLIB in "$LIB" "$LIBDIR/sky130_fd_sc_hd__ss_100C_1v60.lib"; do
  [ -f "$CLIB" ] || continue
  C=$(basename "$CLIB" .lib | sed 's/.*__//')
  yosys-abc -c "read_lib -w $CLIB; read_blif $OUT/${TOP}.blif; topo; stime -p" > "$OUT/stime_$C.txt" 2>&1 || true
  yosys-abc -c "read_lib -w $CLIB; read_blif $OUT/${TOP}.blif; topo; buffer -p; upsize; dnsize; stime -p" > "$OUT/stime_sized_$C.txt" 2>&1 || true
  delay=$(grep -oE "Delay *= *[0-9.]+ ps" "$OUT/stime_$C.txt" | head -1 | grep -oE "[0-9.]+" || true)
  sdelay=$(grep -oE "Delay *= *[0-9.]+ ps" "$OUT/stime_sized_$C.txt" | tail -1 | grep -oE "[0-9.]+" || true)
  carea=$(grep -oE "Area *= *[0-9.]+" "$OUT/stime_$C.txt" | head -1 | grep -oE "[0-9.]+" || true)
  csarea=$(grep -oE "Area *= *[0-9.]+" "$OUT/stime_sized_$C.txt" | tail -1 | grep -oE "[0-9.]+" || true)
  sarea=$(python3 -c "print(round($area + ${csarea:-0} - ${carea:-0}, 1))")
  echo "  $C: crit_raw_ps=${delay:-?} | sized: area_um2=$sarea crit_ps=${sdelay:-?} (period ${PERIOD_PS} ps)"
done
