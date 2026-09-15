#!/usr/bin/env python3
"""Generate woodblock-style bird illustrations with Gemini, then cut out and dither.

  python3 tools/illustrate.py "Erithacus rubecula|European Robin" ...
  python3 tools/illustrate.py --all            # everything in species.txt not yet done
  python3 tools/illustrate.py --post-only SLUG # redo cutout/mono from raw/

Outputs per species slug (lowercase latin, hyphenated):
  raw/<slug>.png     Gemini output as received (cream paper background)
  colour/<slug>.png  background removed, trimmed, RGBA, max 1024 px (for the web)
  mono/<slug>.png    1-bit Floyd-Steinberg, 720 px tall, white ground (for TRMNL)
Needs GEMINI_API_KEY in the environment. Style reference: refs/style-koson-great-tits.jpg
(Ohara Koson, Great Tits on a maple branch, Rijksmuseum, public domain).
"""
import base64, io, json, os, sys, time, urllib.request, urllib.parse, argparse
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
MODEL = "gemini-2.5-flash-image"
API = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
STYLE = ROOT / "refs" / "style-koson-great-tits.jpg"
MANIFEST = ROOT / "manifest.json"

PROMPT = """Generate a perched {com_name} ({sci_name}) in the style of an Edo-period Japanese kachō-e woodblock print, matching the painting technique of IMAGE 2 closely. Look at IMAGE 2: the bird is rendered with VERY FEW MARKS. The body is essentially 2-4 flat color zones with sharp boundaries. There is almost no internal texture on the body - no feather-by-feather rendering, no pen-line stippling, no gradient shading. The bird in IMAGE 2 looks like it was painted with maybe 30 brush strokes total. YOUR output should look the same: a few flat color zones, a few confident outline strokes, an accent stroke or two for major wing or tail markings, and that's it.

Confident sumi-e ink linework with soft watercolor washes. Earthy, restrained palette: burnt umber, ochre, indigo, vermillion, muted greens. The body should look like flat painted paper - not a textured surface, not shaded volume. If the species has subtle plumage variation (streaking, mottling, fine barring), ABSTRACT it into 2-3 broad zones rather than rendering it literally. Eye, beak, and feet drawn with crisp ink - these are the only places where confident dark line is appropriate.

The bird sits on a CONSISTENT WARM CREAM tonal background - like aged Japanese mulberry paper, a soft warm buff cream color. The cream ground fills the entire frame and is identical across every print. This is the only background element: NO branch, NO twig, NO perch, NO leaves, NO foliage, NO substrate, NO scenery, NO sky, NO moon, NO water - only the bird floating against the cream paper ground. The perch is purely implied by toe posture - it is NEVER rendered. NO border or frame, NO text or signature.

Composition: the bird occupies one-third to one-half of the frame. Leave generous negative space around it. The ENTIRE bird must fit within the frame: head, wings, full tail, both legs, both feet, beak. Do NOT crop any body part at the edge. Leave generous padding on all sides.

Reference handling:
- IMAGE 1 (positive, anatomy) IS {com_name}. Match its proportions, head color, throat, wing pattern, back color, tail pattern, leg color. If the reference shows non-breeding or worn plumage, render the brightest BREEDING (adult) plumage instead - the most diagnostic, recognizable version of the species.
- IMAGE 2 (positive, style) is a real Edo-period kachō-e woodblock print by Ohara Koson. The birds in IMAGE 2 are a DIFFERENT species - IGNORE their species, only borrow the painting style. DO NOT copy any compositional elements from IMAGE 2 (branches, leaves, scenery).
Treat IMAGE 1 for anatomy and color ONLY. Treat IMAGE 2 for style ONLY.

Anatomy: EXACTLY TWO wings, EXACTLY TWO legs, EXACTLY ONE head, ONE beak, ONE tail. Pay attention to species-specific patterns; do NOT add generic markings (no crest, wingbars or face mask unless the reference has them). For close relatives (tits, finches, warblers, gulls), render the diagnostic differences clearly.

Feet: BOTH FEET visible at the bottom of the body. Songbird feet are SMALL relative to the body: tarsi roughly 10-15% of body height for finches, tits and warblers, 15-20% for thrushes; larger birds match the reference, usually under 25%. Slim tarsi, small delicate toes; do NOT exaggerate feet or claws.

Pose, PERCHED: one wing folded against the body, the other tucked behind. Both feet visible, toes curled gently forward as if grasping a thin perch that is NOT drawn. The bird floats in space.

Output: render at high resolution. No shadow, no paper texture, no caption."""


def slugify(sci):
    return sci.lower().replace(" ", "-")


def http(url, data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers


def wiki_reference(sci, com):
    """Wikipedia article image for the species (originalimage preferred)."""
    for title in (sci, com):
        try:
            b, _ = http("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_")),
                        headers={"User-Agent": "birdpi-illustrations/1.0 (personal project)"})
            d = json.loads(b)
            src = (d.get("originalimage") or d.get("thumbnail") or {}).get("source")
            if src:
                img, _ = http(src, headers={"User-Agent": "birdpi-illustrations/1.0 (personal project)"})
                return img
        except Exception as e:
            print("   wiki miss", title, e, file=sys.stderr)
    return None


def shrink(img_bytes, long_side):
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    im.thumbnail((long_side, long_side))
    out = io.BytesIO(); im.save(out, "JPEG", quality=88); return out.getvalue()


def generate(sci, com, key, sleep=6.0):
    ref = wiki_reference(sci, com)
    parts = [{"text": PROMPT.format(sci_name=sci, com_name=com)}]
    if ref:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(shrink(ref, 384)).decode()}})
    else:
        print("   no reference photo found; generating from name only", file=sys.stderr)
        parts[0]["text"] = parts[0]["text"].replace("IMAGE 2", "IMAGE 1").replace("IMAGE 1 (positive, anatomy) IS", "(no anatomy photo attached) The bird IS")
    parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(shrink(STYLE.read_bytes(), 768)).decode()}})
    body = json.dumps({"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}).encode()
    backoff = 4.0
    for attempt in range(4):
        try:
            b, _ = http(API, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key}, timeout=180)
            d = json.loads(b)
            for p in d.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                if "inlineData" in p:
                    return base64.b64decode(p["inlineData"]["data"]), bool(ref)
            raise RuntimeError("no image in response: " + json.dumps(d)[:300])
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                print(f"   HTTP {e.code}, retry in {backoff}s", file=sys.stderr); time.sleep(backoff); backoff *= 2; continue
            raise
    raise RuntimeError("gave up")


def cutout(raw_png: Path, colour_png: Path, mono_png: Path):
    im = Image.open(raw_png).convert("RGBA")
    # imported cutouts arrive with transparent corners: lay them on cream first
    if np.asarray(im)[0, 0, 3] < 10:
        cream = Image.new("RGBA", im.size, (245, 236, 215, 255)); cream.alpha_composite(im); im = cream
    a = np.asarray(im).astype(np.int16)
    rgb = a[..., :3]
    h, w = rgb.shape[:2]
    # paper model: the paper has a vignette, so fit a smooth plane per channel
    # to the border pixels and measure each pixel against the plane, not one colour
    band = 10
    yy, xx = np.mgrid[0:h, 0:w]
    border = np.zeros((h, w), dtype=bool); border[:band, :] = border[-band:, :] = True; border[:, :band] = border[:, -band:] = True
    A = np.stack([np.ones(border.sum()), xx[border] / w, yy[border] / h, (xx[border] / w) ** 2, (yy[border] / h) ** 2], axis=1)
    coef, *_ = np.linalg.lstsq(A, rgb[border].astype(float), rcond=None)
    full = np.stack([np.ones(h * w), (xx / w).ravel(), (yy / h).ravel(), ((xx / w) ** 2).ravel(), ((yy / h) ** 2).ravel()], axis=1)
    plane = (full @ coef).reshape(h, w, 3)
    dist = np.abs(rgb - plane).sum(axis=2)
    passable = dist < 48          # within the paper's own texture of the fitted surface
    # flood from the border through passable pixels
    mask = np.zeros((h, w), dtype=bool)
    from collections import deque
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if passable[y, x] and not mask[y, x]: mask[y, x] = True; q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if passable[y, x] and not mask[y, x]: mask[y, x] = True; q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
            if 0 <= ny < h and 0 <= nx < w and passable[ny, nx] and not mask[ny, nx]:
                mask[ny, nx] = True; q.append((ny, nx))
    fg = ~mask
    fg = keep_main_components(fg)
    alpha = Image.fromarray((fg * 255).astype(np.uint8))
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    out = im.copy(); out.putalpha(alpha)
    bbox = alpha.getbbox()
    if bbox:
        pad = int(0.03 * max(w, h)); bbox = (max(0, bbox[0]-pad), max(0, bbox[1]-pad), min(w, bbox[2]+pad), min(h, bbox[3]+pad))
        out = out.crop(bbox)
    out.thumbnail((1024, 1024)); out.save(colour_png, optimize=True)
    make_mono(out, mono_png)


def keep_main_components(fg, keep_ratio=0.04):
    """Drop stray blobs: keep the largest connected region and anything at least
    keep_ratio of its area (detached tail-tips, feet)."""
    h, w = fg.shape
    labels = np.zeros((h, w), dtype=np.int32)
    sizes = []
    from collections import deque
    cur = 0
    ys, xs = np.nonzero(fg)
    for y0, x0 in zip(ys, xs):
        if labels[y0, x0]: continue
        cur += 1; n = 0; q = deque([(y0, x0)]); labels[y0, x0] = cur
        while q:
            y, x = q.popleft(); n += 1
            for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
                if 0 <= ny < h and 0 <= nx < w and fg[ny, nx] and not labels[ny, nx]:
                    labels[ny, nx] = cur; q.append((ny, nx))
        sizes.append(n)
    if not sizes: return fg
    big = max(sizes)
    keep = {i+1 for i, n in enumerate(sizes) if n >= keep_ratio * big}
    return np.isin(labels, list(keep))


def make_mono(rgba, mono_png, levels=5):
    """1-bit for e-ink: composite on white, stretch contrast, flatten to a few
    tones (woodblock flats), then Floyd-Steinberg at 720 px tall."""
    from PIL import ImageOps
    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255)); bg.alpha_composite(rgba)
    g = bg.convert("L")
    scale = 720 / g.height; g = g.resize((max(1, int(g.width * scale)), 720), Image.LANCZOS)
    g = ImageOps.autocontrast(g, cutoff=1)
    a = np.asarray(g).astype(np.float32) / 255.0
    a = np.round(a * (levels - 1)) / (levels - 1)          # posterise
    g = Image.fromarray((a * 255).astype(np.uint8))
    g.convert("1").save(mono_png, optimize=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("species", nargs="*", help='"Latin name|Common name"')
    ap.add_argument("--all", action="store_true"); ap.add_argument("--post-only", action="store_true")
    ap.add_argument("--force", action="store_true"); ap.add_argument("--sleep", type=float, default=6.0)
    args = ap.parse_args()
    key = os.environ.get("GEMINI_API_KEY")
    items = [l.strip().split("|", 1) for l in (ROOT / "species.txt").read_text().splitlines() if "|" in l] if args.all else [s.split("|", 1) for s in args.species]
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    for sci, com in items:
        slug = slugify(sci); raw = ROOT / "raw" / f"{slug}.png"; col = ROOT / "colour" / f"{slug}.png"; mono = ROOT / "mono" / f"{slug}.png"
        if raw.exists() and not args.force and not args.post_only and col.exists():
            continue
        print(f"{com} ({sci})", flush=True)
        try:
            if not args.post_only:
                if not key: sys.exit("GEMINI_API_KEY not set")
                png, had_ref = generate(sci, com, key)
                raw.write_bytes(png)
                manifest[slug] = {"scientific": sci, "common": com, "reference_photo": had_ref, "generated": time.strftime("%Y-%m-%d"), "model": MODEL}
                time.sleep(args.sleep)
            cutout(raw, col, mono)
            manifest.setdefault(slug, {}).update({"scientific": sci, "common": com})
            MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True))
            print(f"   ok  {col.name}  {mono.name}", flush=True)
        except Exception as e:
            print(f"   FAILED {slug}: {e}", file=sys.stderr, flush=True)
            manifest[slug] = {"scientific": sci, "common": com, "error": str(e)[:200]}
            MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
