# birdpi-illustrations

Woodblock-style illustrations of the birds heard at Monks Hall, Suffolk, for the
BirdPi TRMNL panel and its web page.

- `mono/<slug>.png` — 1-bit, 720 px tall, white ground. Fetched by TRMNL at render time.
- `colour/<slug>.png` — background removed, RGBA, up to 1024 px. For the web page.
- `manifest.json` — one entry per species: names, source, generation date.
- `facts.json` — a short description per species, keyed by slug.
- `species.txt` — the species list (BirdNET-Go range filter for 52.36 N, 1.23 E).

Slugs are the scientific name, lower-case, hyphenated: `erithacus-rubecula`.

Images marked `source: avianvisitors` come from Theodore Warner's
[AvianVisitors](https://github.com/Twarner491/AvianVisitors) set. The rest were
generated with Google's `gemini-2.5-flash-image` using his published prompt, with
a Wikipedia photo of the species as the anatomy reference and Ohara Koson's
*Great Tits on a maple branch* (Rijksmuseum, public domain) as the style reference.
Pipeline: `tools/illustrate.py`.

Licence: CC BY-NC-SA 4.0, matching the AvianVisitors set. Personal, non-commercial.
