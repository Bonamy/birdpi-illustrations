#!/usr/bin/env python3
"""Bake each bird's name into its colour print, written along its back.

  python3 tools/label.py                # all species in manifest.json missing from labeled/
  python3 tools/label.py SLUG ...       # specific slugs
  python3 tools/label.py --force        # redo everything

Reads colour/<slug>.png, writes labeled/<slug>.png (RGBA, canvas grown to fit the
text). The name follows the smoothed top outline of the bird when that curve is
long and gentle enough; otherwise it is set straight above the bird.
"""
import json, math, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "refs" / "fonts" / "Caveat[wght].ttf"
INK = (138, 131, 120, 255)          # #8a8378
STEEP = 0.5                          # max rise/run for a curved label
SPAN = 0.70                          # share of the bird's width the curve may use


def outline(alpha):
    h, w = alpha.shape
    top = np.full(w, -1, dtype=int)
    for x in range(w):
        ys = np.nonzero(alpha[:, x])[0]
        if ys.size: top[x] = ys[0]
    return top


def smooth(vals, k):
    out = vals.astype(float).copy()
    for i in range(len(vals)):
        a, b = max(0, i - k), min(len(vals), i + k + 1)
        out[i] = vals[a:b].mean()
    return out


def glyph_tile(font, ch, size):
    """RGBA tile with the glyph, plus the baseline origin inside the tile."""
    pad = size
    tile = Image.new("RGBA", (int(font.getlength(ch)) + 2 * pad, size * 2 + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((pad, pad + size), ch, font=font, fill=INK, anchor="ls")
    return tile, (pad, pad + size)


def write_along(canvas, pts, name, font, size):
    """pts: list of (x, y) along which the baseline runs, left to right."""
    seg = [math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1]) for i in range(len(pts)-1)]
    total = sum(seg); text_w = font.getlength(name)
    s = (total - text_w) / 2                     # centre the text on the path
    def at(d):
        acc = 0.0
        for i, L in enumerate(seg):
            if acc + L >= d or i == len(seg) - 1:
                t = 0 if L == 0 else (d - acc) / L
                x = pts[i][0] + (pts[i+1][0]-pts[i][0]) * t; y = pts[i][1] + (pts[i+1][1]-pts[i][1]) * t
                ang = math.degrees(math.atan2(pts[i+1][1]-pts[i][1], pts[i+1][0]-pts[i][0]))
                return x, y, ang
            acc += L
    for ch in name:
        w = font.getlength(ch)
        x, y, ang = at(s + w / 2)
        tile, (ox, oy) = glyph_tile(font, ch, size)
        # rotate the glyph about its baseline-left origin so it follows the tangent
        rot = tile.rotate(-ang, resample=Image.BICUBIC, center=(ox, oy), expand=False)
        # baseline-left of the glyph sits half a glyph back along the tangent
        rad = math.radians(ang)
        bx, by = x - math.cos(rad) * w / 2, y - math.sin(rad) * w / 2
        canvas.alpha_composite(rot, (int(round(bx - ox)), int(round(by - oy))))
        s += w


def label(slug, name, force=False):
    src = ROOT / "colour" / f"{slug}.png"; dst = ROOT / "labeled" / f"{slug}.png"
    if dst.exists() and not force: return "skip"
    im = Image.open(src).convert("RGBA")
    a = np.asarray(im)[..., 3] > 60
    ys, xs = np.nonzero(a)
    if xs.size == 0: return "empty"
    x0, x1, y0 = xs.min(), xs.max(), ys.min()
    bw = x1 - x0 + 1
    # font size is bird-relative. Long names may shrink a little to ride the
    # curve, but never below a floor: a tiny label is worse than a straight one.
    size = int(max(30, min(96, bw / 8.5)))
    floor = int(max(28, bw / 13))
    top = outline(a)
    pad_top = int(size * 1.9); pad_side = int(size * 6)   # generous; cropped away at the end
    canvas = Image.new("RGBA", (im.width + 2 * pad_side, im.height + pad_top), (0, 0, 0, 0))
    canvas.alpha_composite(im, (pad_side, pad_top))
    mode = "straight"; font = None

    # Smoothed top outline of the whole bird. Running median first so crests and
    # raised tail-tips do not lift the line, then a moving average.
    cols = [x for x in range(x0, x1 + 1) if top[x] >= 0]
    raw = top[cols].astype(float)
    k = max(4, len(cols) // 14)
    med = np.array([np.median(raw[max(0, i-k):i+k+1]) for i in range(len(raw))])
    sm = smooth(med, k)

    def best_window(sz, tw):
        """Slide a window the width of the text along the back and pick the
        flattest stretch. Returns lifted path points, or None."""
        need = int(tw * 1.04)
        lift = sz * 0.45
        MAX_LOCAL, MAX_OVERALL = 1.0, 0.75         # ~45 degrees locally, ~37 overall
        w = max(6, int(sz * 0.6)); best = None
        lo, hi = int(len(cols) * 0.04), int(len(cols) * 0.96)
        for s in range(lo, hi - need, max(2, need // 40)):
            seg = range(s, s + need)
            pts = [(cols[i] + pad_side, sm[i] + pad_top - lift) for i in seg]
            worst = 0.0
            for i in range(0, len(pts) - w, max(1, w // 3)):
                worst = max(worst, abs(pts[i+w][1] - pts[i][1]) / max(pts[i+w][0] - pts[i][0], 1))
            if worst > MAX_LOCAL: continue
            overall = abs(pts[-1][1] - pts[0][1]) / max(pts[-1][0] - pts[0][0], 1)
            if overall > MAX_OVERALL: continue
            centre_pen = abs((s + need / 2) / len(cols) - 0.5)    # mild preference for the middle
            score = worst + 0.6 * overall + 0.25 * centre_pen
            if best is None or score < best[0]: best = (score, pts)
        return None if best is None else best[1]

    for sz in range(size, floor - 1, -4):
        f = ImageFont.truetype(str(FONT), sz)
        try: f.set_variation_by_axes([550])
        except Exception: pass
        pts = best_window(sz, f.getlength(name)) if len(cols) > 20 else None
        if pts:
            write_along(canvas, pts, name, f, sz); mode = "curved"; font = f; size = sz; break
    if mode == "straight":
        font = ImageFont.truetype(str(FONT), size)
        try: font.set_variation_by_axes([550])
        except Exception: pass
        d = ImageDraw.Draw(canvas)
        d.text((pad_side + x0 + bw / 2, pad_top + y0 - size * 0.35), name, font=font, fill=INK, anchor="ms")
    bbox = canvas.getbbox()
    if bbox: canvas = canvas.crop((max(0, bbox[0]-8), max(0, bbox[1]-8), min(canvas.width, bbox[2]+8), min(canvas.height, bbox[3]+8)))
    canvas.save(dst, optimize=True)
    return mode


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]; force = "--force" in sys.argv
    m = json.loads((ROOT / "manifest.json").read_text())
    slugs = args or [k for k, v in m.items() if "error" not in v]
    stats = {}
    for s in slugs:
        if s not in m: print("unknown slug", s); continue
        if not (ROOT / "colour" / f"{s}.png").exists(): continue
        r = label(s, m[s]["common"], force); stats[r] = stats.get(r, 0) + 1
        if args: print(s, r)
    print(stats)
