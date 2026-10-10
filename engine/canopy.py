"""Add tree canopy to a city's profile file, for the canopy lens, the card's Tree canopy row and the facts.
Reads cities/<city>/raw/canopy/canopy.json (engine/fetch_canopy.py, fetch-canopy.yml) and the tier cuts
in cities/<city>/canopy.json. Run after the city's profiles.py and before engine/facts.py.

Fields written per unit: "canopy" (share of land under tree cover, %, water left out) and "canopyBand"
(c1 under the first cut, c2, c3, c4 at or over the last). Tree cover is a description of the place, not
of the people, so it may feed the "what stands out" facts (high end only: "Among the leafiest").

Usage: python3 engine/canopy.py <city>
"""
import json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
city = sys.argv[1]
CFG = json.load(open(os.path.join(ROOT, 'cities', city, 'canopy.json')))
CITY = json.load(open(os.path.join(ROOT, 'cities', city, 'city.json')))
RAW = os.path.join(ROOT, 'cities', city, 'raw', 'canopy', 'canopy.json')
PROF = os.path.join(ROOT, 'docs', city, 'data', CITY['lens']['file'])
if not os.path.exists(RAW): sys.exit(f'{city}: no canopy fetched yet (fetch-canopy.yml); skipped')
raw = json.load(open(RAW)); src = raw['sources'][raw['used']]
prof = json.load(open(PROF))
cuts = CFG['cuts']
band = lambda v: 'c' + str(1 + sum(v >= c for c in cuts))
n = 0
for code, d in prof.items():
    v = src['units'].get(code)
    if v is None: d.pop('canopy', None); d.pop('canopyBand', None); continue
    d['canopy'], d['canopyBand'] = v, band(v); n += 1
json.dump(prof, open(PROF, 'w'), separators=(',', ':'))
from collections import Counter
print(f"{city}: canopy for {n} of {len(prof)} units from {raw['used']} ({src['year']}), citywide {src['city']}%;",
      dict(sorted(Counter(d.get('canopyBand') for d in prof.values()).items(), key=lambda kv: str(kv[0]))))
