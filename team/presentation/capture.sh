#!/usr/bin/env bash
# Retake the screenshots used in the presentation from the running Stand and Grafana,
# then crop them into img/ (prep_images.py). Takes about 20 minutes: after the pump-station
# failure the level -50 m floods in about 3.5 real minutes and the level 0 m in about
# 10 (the flood episode runs 24 times faster than the mine clock); the shot is taken at 11.5.
# The panel «Вентиляция по потребности» is taken first: start the script after the Stand
# has run at least 24 real minutes in «Базовый режим», so that «Экономия за 24 ч» covers it.
#
#   bash team/presentation/capture.sh [raw_dir]
#
# Needs: the Stand on http://localhost:8088, Grafana on $GRAFANA (default
# http://localhost:3000), Node 22+, Google Chrome, Python 3 with Pillow.
# Scenarios are switched through POST /api/scenario; the script always ends
# with {"preset":"reset"}, which leaves the Stand in «Базовый режим».
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW="${1:-$(mktemp -d)}"
STAND="${STAND:-http://localhost:8088}"
GRAFANA="${GRAFANA:-http://localhost:3000}"
JOBS="$(mktemp -d)"
mkdir -p "$RAW"
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else echo "$1"; fi; }
R="$(native "$RAW")"

preset() { curl -fsS -X POST -H 'Content-Type: application/json' -d "{\"preset\":\"$1\"}" "$STAND/api/scenario" >/dev/null; echo "preset $1"; }
trap 'preset reset || true' EXIT

# job NAME JSON: write a capture job and run it
job() { printf '%s' "$2" > "$JOBS/$1.json"; node "$HERE/capture.mjs" "$(native "$JOBS/$1.json")"; }

# Stand page, panels at device scale 2. $1 prefix, $2 extra steps (JSON array)
panels() {
  job "$1" "{\"url\":\"$STAND/\",\"width\":1920,\"height\":1500,\"scale\":2,\"wait\":14000,
    \"shots\":[{\"out\":\"$R/$1_adv.png\",\"selector\":\"#advisor\"},{\"out\":\"$R/$1_chg.png\",\"selector\":\"#changes\"},
               {\"out\":\"$R/$1_mine.png\",\"selector\":\"#mine\"}]}"
}
# 3D-only view with a camera preset: $1 output name, $2 preset id (mine, declines, vent, water, plant)
scene() {
  job "$1" "{\"url\":\"$STAND/\",\"width\":1920,\"height\":1500,\"scale\":2,\"wait\":12000,
    \"steps\":[{\"click\":\"#mine button[data-mode=\\\"scene3d\\\"]\",\"wait\":3000},
               {\"click\":\"#view-scene3d button[data-preset=\\\"$2\\\"]\",\"wait\":5000}],
    \"shots\":[{\"out\":\"$R/$1.png\",\"selector\":\"#mine\"}]}"
}

preset reset; sleep 20
# ventilation on demand at baseline, and the plan view on the satellite image
job bvod "{\"url\":\"$STAND/\",\"width\":1150,\"height\":4000,\"scale\":2,\"wait\":15000,
  \"shots\":[{\"out\":\"$R/b_vod.png\",\"selector\":\"#vod\"}]}"
job bplanview "{\"url\":\"$STAND/?view=plan\",\"width\":1920,\"height\":1500,\"scale\":2,\"wait\":15000,
  \"shots\":[{\"out\":\"$R/b_planview.png\",\"selector\":\"#mine\"}]}"
# baseline: advisor, ladder and projection, calibration, 3D and section
job base "{\"url\":\"$STAND/\",\"width\":1920,\"height\":5200,\"scale\":2,\"wait\":15000,
  \"shots\":[{\"out\":\"$R/b_advisor.png\",\"selector\":\"#advisor\"},{\"out\":\"$R/b_plan.png\",\"selector\":\"#advisor-plan\"},
             {\"out\":\"$R/b_cal.png\",\"selector\":\"#calibration\"}]}"
scene b_3d mine
job bsec "{\"url\":\"$STAND/\",\"width\":1920,\"height\":1500,\"scale\":2,\"wait\":12000,
  \"steps\":[{\"click\":\"#mine button[data-mode=\\\"section2d\\\"]\",\"wait\":4000}],
  \"shots\":[{\"out\":\"$R/b_sec.png\",\"selector\":\"#mine\"}]}"

# what-if: «Снять узкое место» twice
preset advisor_next; sleep 40; panels n1; scene n1_3d_decl declines
preset advisor_next; sleep 50; panels n2; scene n2_3d_vent vent

# disturbances
preset reset; sleep 3; preset close_tu2; sleep 55; panels tu2; scene tu2_3d_decl declines
preset reset; sleep 3; preset fan_vs2_fail; sleep 55; panels vs2; scene vs2_3d_decl declines
preset reset; sleep 3; preset pump_station_fail; sleep 690; panels ps3; scene ps_3d_water water
preset reset

# Grafana (anonymous viewer): OpenEgiz twins of the enterprise, overview dashboard
job g_children "{\"url\":\"$GRAFANA/a/ertis-opentwins-app/twins\",\"width\":1600,\"height\":1000,\"scale\":2,\"wait\":20000,
  \"steps\":[{\"eval\":\"(() => { const e=[...document.querySelectorAll('*')].find(x=>x.children.length===0 && x.textContent.trim()==='kz.sekis:enterprise'); e.click(); return true; })()\",\"wait\":12000},
             {\"eval\":\"(() => { [...document.querySelectorAll('button,a,[role=tab]')].find(x=>x.textContent.trim()==='Children').click(); return true; })()\",\"wait\":10000}],
  \"shots\":[{\"out\":\"$R/g_children.png\"}]}"
sleep 300   # let the flooded level drain before the overview is taken
job g_gov_base "{\"url\":\"$GRAFANA/d/sekis-overview?kiosk\",\"width\":1600,\"height\":1000,\"scale\":2,\"wait\":30000,
  \"shots\":[{\"out\":\"$R/g_gov_base.png\"}]}"

python3 "$HERE/prep_images.py" "$R" 2>/dev/null || python "$HERE/prep_images.py" "$R"
echo "raw screenshots: $RAW"
