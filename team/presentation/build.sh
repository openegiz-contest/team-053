#!/usr/bin/env bash
# Rebuild presentation.pdf (repository root) from team/presentation/index.html
# with headless Chrome. Works in Git Bash on Windows and in bash on Linux.
#
#   bash team/presentation/build.sh            # PDF only
#   bash team/presentation/build.sh --pages    # also PNG of every page (needs PyMuPDF)
#
# The images in img/ are crops of live Stand / Grafana screenshots; see capture.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="$ROOT/presentation.pdf"

find_chrome() {
  if [ -n "${CHROME:-}" ]; then echo "$CHROME"; return; fi
  for c in "/c/Program Files/Google/Chrome/Application/chrome.exe" \
           "/c/Program Files (x86)/Google/Chrome/Application/chrome.exe" \
           "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
           google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then echo "$c"; return; fi
  done
  echo "Chrome not found; set CHROME=/path/to/chrome" >&2
  exit 1
}

to_native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else echo "$1"; fi; }

CHROME_BIN="$(find_chrome)"
HTML="$(to_native "$HERE/index.html")"
PDF="$(to_native "$OUT")"
PROFILE="$(mktemp -d)"
trap 'rm -rf "$PROFILE"' EXIT

"$CHROME_BIN" --headless=new --disable-gpu --no-pdf-header-footer \
  --user-data-dir="$(to_native "$PROFILE")" \
  --virtual-time-budget=5000 \
  --print-to-pdf="$PDF" "file:///${HTML#/}" 2>/dev/null

python_bin="$(command -v python3 || command -v python)"
"$python_bin" - "$PDF" <<'EOF'
import os, sys
path = sys.argv[1]
size = os.path.getsize(path)
try:
    import pypdf
    pages = len(pypdf.PdfReader(path).pages)
except ImportError:
    pages = "?"
print(f"{path}: {pages} pages, {size / 1048576:.2f} MB")
EOF

if [ "${1:-}" = "--pages" ]; then
  PAGES_DIR="${PAGES_DIR:-$(mktemp -d)}"
  "$python_bin" - "$PDF" "$(to_native "$PAGES_DIR")" <<'EOF'
import sys
import pymupdf
doc = pymupdf.open(sys.argv[1])
for i, page in enumerate(doc, 1):
    page.get_pixmap(dpi=96).save(f"{sys.argv[2]}/page-{i:02d}.png")
print(f"pages rendered to {sys.argv[2]}")
EOF
fi
