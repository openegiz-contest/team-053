"""Crop and compress the raw Stand / Grafana screenshots into img/.

Usage: python prep_images.py <raw_dir>
The raw PNGs are taken by capture.mjs at device scale 2 (see capture.sh);
crop boxes are in raw pixels. Output: JPEG, quality 86, longest side <= 2000 px.
"""
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / "img"

# name: (raw file, crop box (left, top, right, bottom) or None)
CROPS = {
    "s01_section": ("b_sec.png", (0, 225, 2272, 1865)),
    "s04_openegiz_children": ("g_children.png", (620, 200, 3200, 1140)),
    "s05_grafana_overview": ("g_gov_base.png", (0, 0, 3200, 1720)),
    "s06_scene3d": ("b_3d.png", (0, 190, 2272, 2266)),
    "s06_section": ("b_sec.png", (0, 225, 2272, 1764)),
    "s08_advisor": ("b_advisor.png", (0, 0, 784, 1240)),
    "s09_scene_held": ("n1_3d_decl.png", (118, 330, 2159, 1676)),
    "s09_changes": ("n1_chg.png", (0, 0, 784, 600)),
    "s09_advisor_vpv": ("n2_adv.png", (0, 0, 784, 1170)),
    "s10_ladder": ("b_plan.png", (20, 160, 2262, 800)),
    "s11_projection": ("b_plan.png", (2280, 110, 3780, 835)),
    "s12_tu2_scene": ("tu2_3d_decl.png", (590, 354, 2218, 1492)),
    "s12_tu2_next": ("tu2_adv.png", (0, 700, 784, 935)),
    "s12_vs2_scene": ("vs2_3d_decl.png", (1180, 354, 2218, 1080)),
    "s12_vs2_next": ("vs2_adv.png", (0, 700, 784, 935)),
    "s12_ps_scene": ("ps_3d_water.png", (755, 1097, 1982, 1955)),
    "s12_ps_next": ("ps3_adv.png", (0, 700, 784, 965)),
}


def main(raw_dir: str) -> None:
    raw = Path(raw_dir)
    OUT.mkdir(exist_ok=True)
    only = set(sys.argv[2:])
    for name, (src, box) in CROPS.items():
        if only and name not in only:
            continue
        path = raw / src
        if not path.exists():
            print(f"skip {name}: {path} missing")
            continue
        im = Image.open(path).convert("RGB")
        if box:
            im = im.crop(box)
        if max(im.size) > 2000:
            k = 2000 / max(im.size)
            im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
        out = OUT / f"{name}.jpg"
        im.save(out, "JPEG", quality=86, optimize=True, progressive=True)
        print(f"{out.name}: {im.size[0]}x{im.size[1]}, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(sys.argv[1])
