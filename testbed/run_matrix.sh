#!/bin/bash
# Reproduce the paper's testbed matrix. Run from this directory.
# Requires: ZEBRA_RELAY_BIN pointing at a release build of zebra-relay (see README).
set -eu
: "${ZEBRA_RELAY_BIN:?set ZEBRA_RELAY_BIN to the zebra-relay binary}"
mkdir -p runs
run() { # profile topo mode attackers
  out=runs/m_$1_t$2_$3_a$4
  [ -f "$out/run.json" ] && return
  rm -rf "$out"
  python3 harness_attack.py --n 100 --outbound 25 --mode "$3" --topo-seed "$2" --profile "$1" \
    --attackers "$4" --blocks 8 --dilation 4 --stagger 0.02 --warmup 15 --out "$out"
}
for t in 1 2 3; do run mixed $t zebra 0; run mixed $t prio_warm 0; done
run mixed 1 prio 0; run mixed 2 prio 0; run mixed 1 prio_third 0
run dc 1 zebra 0; run dc 1 prio_warm 0
run mixed 1 zebra 10; run mixed 1 prio_warm 10
python3 summarize.py runs
