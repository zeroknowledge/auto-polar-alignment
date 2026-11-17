#!/bin/bash
# Slice every STL in ../stl with the Bambu X1C / PETG profiles in ./profiles using the OrcaSlicer CLI.
# Profiles are flattened copies of OrcaSlicer v2.5.0's "Bambu Lab X1 Carbon 0.4 nozzle", "0.20mm Standard @BBL X1C"
# (overridden to 4 walls, 30% gyroid) and "Bambu PETG Basic @BBL X1C".
# Scratch folders come from mktemp (under $TMPDIR); this script deletes nothing.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ORCA=/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer
DATA="$(mktemp -d)"            # isolated data dir: does not touch ~/Library/Application Support/OrcaSlicer
mkdir -p "$HERE/../gcode"
FILTER="${1:-}"                # optional: only parts whose name contains this text, e.g. ./slice_all.sh fit_test
for stl in "$HERE"/../stl/*.stl; do
  name="$(basename "$stl" .stl)"
  [ -n "$FILTER" ] && [[ "$name" != *"$FILTER"* ]] && continue
  PROC="$HERE/profiles/process.json"
  [[ "$name" == *fit_test* ]] && PROC="$HERE/profiles/process_fast.json"   # the coupon only needs accurate holes
  work="$(mktemp -d)"
  "$ORCA" --datadir "$DATA" --arrange 1 \
    --load-settings "$HERE/profiles/machine.json;$PROC" \
    --load-filaments "$HERE/profiles/filament.json" \
    --slice 0 --export-statistics --outputdir "$work" "$stl" > "$work/log.txt" 2>&1 || { echo "FAILED $name"; tail -5 "$work/log.txt"; continue; }
  cp "$work/plate_1.gcode" "$HERE/../gcode/$name.gcode"
  [ -f "$work/plate_1.statistics.json" ] && cp "$work/plate_1.statistics.json" "$HERE/../gcode/$name.stats.json"
  echo "sliced $name"
done

# Multi-copy plates: part:count (the single-part G-code above is still produced for each)
for spec in "01_nut_trunnion:3" "05_coarse_cheek:2" "08_alt_cheek:2"; do
  part="${spec%%:*}"; n="${spec##*:}"
  if [ -z "$FILTER" ] || [[ "$part" == *"$FILTER"* ]]; then
    work="$(mktemp -d)"
    "$ORCA" --datadir "$DATA" --arrange 1 --clone-objects "$n" \
      --load-settings "$HERE/profiles/machine.json;$HERE/profiles/process.json" \
      --load-filaments "$HERE/profiles/filament.json" \
      --slice 0 --export-statistics --outputdir "$work" "$HERE/../stl/$part.stl" > "$work/log.txt" 2>&1 \
      && cp "$work/plate_1.gcode" "$HERE/../gcode/${part}_x$n.gcode" \
      && cp "$work/plate_1.statistics.json" "$HERE/../gcode/${part}_x$n.stats.json" \
      && echo "sliced ${part}_x$n" || echo "FAILED ${part}_x$n"
  fi
done
