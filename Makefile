# MANTIS — convenience targets. Run inside the OSS CAD Suite environment:
#   source ~/eda/oss-cad-suite/environment
#
#   make test     all cocotb suites (~2 min)
#   make lint     Verilator -Wall on the top level and the prototypes
#   make formal   SymbiYosys proof + cover for tt_um_lucas_rigsby_mantis
#   make synth    Yosys/ABC area + tt/ss timing estimate for tt_um_lucas_rigsby_mantis
#   make vectors      regenerate bringup/vectors.py from the reference model
#   make bringup-sim  run bringup/test_bringup.py against the RTL
#   make all      lint test formal

# cocotb from the OSS CAD Suite has a stale built-in libpython path
export LIBPYTHON_LOC ?= $(shell cocotb-config --libpython 2>/dev/null)

CORE := rtl/fp8_unpack.v rtl/fp8_mul.v rtl/bf16_add_s1.v rtl/bf16_add_s2.v \
        rtl/mantis_stage.v rtl/mantis_dp_shared.v
TOP  := $(CORE) rtl/tt_um_lucas_rigsby_mantis.v

.PHONY: all test test-mul test-add test-datapath test-top lint formal synth vectors bringup-sim clean

all: lint test formal

test: test-mul test-add test-datapath test-top

test-mul:
	cd tb && python3 -m pytest -q test_fp8_mul.py

test-add:
	cd tb && python3 -m pytest -q test_bf16_add.py

test-datapath:
	cd tb && python3 -m pytest -q test_datapath.py

test-top:
	cd tb && python3 -m pytest -q test_top.py

lint:
	verilator --lint-only -Wall $(TOP) --top-module tt_um_lucas_rigsby_mantis
	verilator --lint-only -Wall rtl/fp8_unpack.v rtl/fp8_mul.v rtl/bf16_add_s1.v \
	    rtl/bf16_add_s2.v rtl/bf16_add.v rtl/mantis_stage.v rtl/mantis_dp_pe4.v \
	    --top-module mantis_dp_pe4

formal:
	cd formal && sby -f tt_um_lucas_rigsby_mantis.sby

vectors:
	python3 bringup/export_vectors.py

bringup-sim:
	cd bringup && python3 -m pytest -q test_bringup.py

synth:
	syn/synth.sh tt_um_lucas_rigsby_mantis $(TOP)

clean:
	rm -rf tb/sim_build tb/*.result.xml tb/__pycache__ tb/.pytest_cache \
	       bringup/__pycache__ bringup/.pytest_cache bringup/*.result.xml \
	       syn/out formal/tt_um_lucas_rigsby_mantis_prove formal/tt_um_lucas_rigsby_mantis_cover formal/tt_um_lucas_rigsby_mantis
