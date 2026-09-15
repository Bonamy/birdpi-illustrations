#!/usr/bin/env python3
"""Bake each bird's name into its colour print, written along its back.

  python3 tools/label.py                # all species in manifest.json missing from labeled/
  python3 tools/label.py SLUG ...       # specific slugs
  python3 tools/label.py --force        # redo everything

Reads colour/<slug>.png, writes labeled/<slug>.png (RGBA, canvas grown to fit the
text). Names come from names.json (British everyday names). The name follows the smoothed top outline of the bird when that curve is
long and gentle enough; otherwise it is set straight above the bird.
"""
import json, math, sys
from pathlib import Path
import numpy as np
import cv2
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


def solid_mask(rgba):
    """The bird's silhouette for placing text: faint alpha counts (pale plumage is
    only half-opaque after the cut-out), gaps in the outline are closed and holes
    filled, so white heads and bellies are not mistaken for empty space."""
    a = (np.asarray(rgba)[..., 3] > 10).astype(np.uint8)
    k = max(3, int(max(a.shape) / 60)) | 1
    a = cv2.morphologyEx(a, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    ff = np.pad(a, 1).copy(); cv2.floodFill(ff, None, (0, 0), 1)
    holes = ff[1:-1, 1:-1] == 0
    return (a > 0) | holes


def overlap(layer, bird):
    """Share of the text's ink that lands on the bird (both canvas-sized)."""
    ink = np.asarray(layer)[..., 3] > 40
    n = ink.sum()
    return 0.0 if n == 0 else (ink & bird).sum() / n


def write_along(canvas, pts, name, font, size):
    """pts: list of (x, y) along which the baseline runs, left to right."""
    # smooth the baseline over about half a glyph so the ends of the path (where
    # the outline turns into the neck or tail) cannot tip a letter over
    k = max(2, size // 2); ys = np.array([p[1] for p in pts], dtype=float)
    ys = np.array([ys[max(0, i - k):i + k + 1].mean() for i in range(len(ys))])
    pts = [(p[0], y) for p, y in zip(pts, ys)]
    seg = [math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1]) for i in range(len(pts)-1)]
    total = sum(seg); text_w = font.getlength(name)
    s = (total - text_w) / 2                     # centre the text on the path
    def at(d):
        acc = 0.0
        for i, L in enumerate(seg):
            if acc + L >= d or i == len(seg) - 1:
                t = 0 if L == 0 else (d - acc) / L
                return pts[i][0] + (pts[i+1][0]-pts[i][0]) * t, pts[i][1] + (pts[i+1][1]-pts[i][1]) * t
            acc += L
    for ch in name:
        w = font.getlength(ch)
        x, y = at(s + w / 2)
        # tangent from the chord across the glyph (and a little either side), not
        # one pixel of path: single steps are noisy and send letters into each other
        ax, ay = at(max(0.0, s - size * 0.2)); bx_, by_ = at(min(total, s + w + size * 0.2))
        ang = math.degrees(math.atan2(by_ - ay, bx_ - ax))
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
    a = solid_mask(im)
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
    clear = max(5, int(size * 0.15)) | 1              # keep letters this far off the outline
    bird = np.zeros((canvas.height, canvas.width), dtype=bool)
    bird[pad_top:pad_top + im.height, pad_side:pad_side + im.width] = cv2.dilate(a.astype(np.uint8), np.ones((clear, clear), np.uint8)) > 0
    mode = "straight"; font = None

    # Smoothed top outline of the whole bird. Running median first so crests and
    # raised tail-tips do not lift the line, then a moving average.
    cols = [x for x in range(x0, x1 + 1) if top[x] >= 0]
    raw = top[cols].astype(float)
    k = max(4, len(cols) // 14)
    med = np.array([np.median(raw[max(0, i-k):i+k+1]) for i in range(len(raw))])
    sm = smooth(med, k)

    def best_window(sz, tw, extra=0.0):
        """Slide a window the width of the text along the back and pick the
        flattest stretch. Returns lifted path points, or None."""
        need = int(tw * 1.04)
        lift = sz * (0.55 + extra)
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
        for extra in (0.0, 0.3, 0.6):          # lift further if the text would touch the bird
            pts = best_window(sz, f.getlength(name), extra) if len(cols) > 20 else None
            if not pts: break
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            write_along(layer, pts, name, f, sz)
            if overlap(layer, bird) < 0.01:
                canvas.alpha_composite(layer); mode = "curved"; font = f; size = sz; break
        if mode == "curved": break
    if mode == "straight":
        # set above the highest point, and no wider than the bird (plus a little)
        size = int(max(floor, min(size, size * bw * 1.15 / max(1, ImageFont.truetype(str(FONT), size).getlength(name)))))
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
    names = json.loads((ROOT / "names.json").read_text())
    slugs = args or [k for k, v in m.items() if "error" not in v]
    stats = {}
    for s in slugs:
        if s not in m: print("unknown slug", s); continue
        if not (ROOT / "colour" / f"{s}.png").exists(): continue
        r = label(s, names.get(m[s]["scientific"], m[s]["common"]), force); stats[r] = stats.get(r, 0) + 1
        if args: print(s, r)
    print(stats)
