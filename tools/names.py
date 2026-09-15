#!/usr/bin/env python3
"""Build names.json: scientific name -> British everyday display name.

  python3 tools/names.py

BirdNET-Go labels are IOC English names ("European Robin", "Common Woodpigeon").
The rule drops a leading European / Eurasian / Common / Northern / Western where
what is left is the name people use in Britain. KEEP lists the birds where the
qualifier is part of the British name; RENAME covers everything the rule cannot.
Alias slugs (renamed genera) get an entry under their own scientific name too.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUALIFIERS = ("European ", "Eurasian ", "Common ", "Northern ", "Western ")

KEEP = {"Common Gull", "Common Tern", "Common Sandpiper", "Common Crane", "Common Scoter"}

RENAME = {
    "Eurasian/Green-winged Teal": "Teal",
    "Pied Wagtail/White Wagtail": "Pied Wagtail",
    "Ring-necked Pheasant": "Pheasant",
    "Western Cattle-Egret": "Cattle Egret",
    "Great Bittern": "Bittern",
    "Great Cormorant": "Cormorant",
    "Greater White-fronted Goose": "White-fronted Goose",
    "Ruddy Turnstone": "Turnstone",
    "Red Knot": "Knot",
    "Rock Dove": "Feral Pigeon",
    "White-throated Dipper": "Dipper",
    "Peregrine Falcon": "Peregrine",
    "Black-legged Kittiwake": "Kittiwake",
    "Pied Avocet": "Avocet",
    "Red-billed Chough": "Chough",
    "Barn Swallow": "Swallow",
    "European Honey-buzzard": "Honey Buzzard",
}


def display(common):
    if common in RENAME: return RENAME[common]
    if common in KEEP: return common
    for q in QUALIFIERS:
        if common.startswith(q): return common[len(q):]
    return common


def main():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    pairs = {}
    for line in (ROOT / "species.txt").read_text().splitlines():
        if "|" in line:
            sci, com = line.strip().split("|", 1); pairs[sci] = com
    for slug, v in manifest.items():
        if v.get("scientific") and v.get("common"):
            pairs.setdefault(v["scientific"], v["common"])
            # alias slug: BirdNET's own scientific name for the same bird
            alias_sci = slug.replace("-", " ").capitalize()
            pairs.setdefault(alias_sci, v["common"])
    names = {sci: display(com) for sci, com in sorted(pairs.items())}
    (ROOT / "names.json").write_text(json.dumps(names, indent=1, ensure_ascii=False) + "\n")
    changed = sum(1 for s, c in pairs.items() if names[s] != c)
    print(f"{len(names)} names, {changed} changed from IOC")


if __name__ == "__main__":
    main()
