"""How addresses work: build docs/<city>/data/addresses.geojson for the "addresses" layer and the card's
Address row, from cities/<city>/addresses.json and the street files already built (streets, collectors).

Two kinds of city, set by "type" in addresses.json:

  - "grid" (Chicago): every address is a distance from two baselines (State St and Madison St are 0).
    "ns" lists east-west streets with the north/south number they sit on ("Fullerton Ave", 2400, "N");
    "ew" lists north-south streets with their east/west number ("Halsted St", 800, "W"). Each street is
    placed at the median of its drawn geometry (the grid is close to true north) and drawn as a straight
    line across the city, clipped to the city outline. Top-level "axes" keeps the positions, so the page
    can interpolate an address number for any spot: {"ns": [[lat, signed number]...], "ew": [[lon, ...]...]}
    (north and east positive).

  - "divide" (Toronto): one street splits the others into East and West ("Yonge St"). Writes the
    dividing street (role "divide") and every drawn street whose name ends in " E" or " W" (role "e"/"w"),
    so the page can show which side a spot is on and an example street. Numbers aren't a grid there:
    each street counts up from its own start, which the card says in words.

Usage: python3 engine/addresses.py <city>
"""
import json, os, statistics, sys
from shapely.geometry import LineString, MultiLineString, shape, mapping
from shapely.ops import unary_union, linemerge

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
city = sys.argv[1]
CFG = json.load(open(os.path.join(ROOT, 'cities', city, 'addresses.json')))
CITY = json.load(open(os.path.join(ROOT, 'cities', city, 'city.json')))
DATA = os.path.join(ROOT, 'docs', city, 'data')
feats = []
for f in CFG.get('files', ['streets', 'collectors']):
    p = os.path.join(DATA, f + '.geojson')
    if os.path.exists(p): feats += json.load(open(p))['features']
by_name = {}
for f in feats:
    n = f['properties'].get('name')
    if n: by_name.setdefault(n, []).append(shape(f['geometry']))
outline = unary_union([shape(f['geometry']).buffer(0) for f in json.load(open(os.path.join(DATA, CITY['footprint'] + '.geojson')))['features']])
minx, miny, maxx, maxy = outline.bounds
rnd = lambda g: [[round(x, 5), round(y, 5)] for x, y in g.coords]
out = []


def coords(name):
    gs = by_name.get(name)
    if not gs: raise SystemExit(f'{city}: no drawn street called {name!r}')
    return [c for g in gs for part in getattr(g, 'geoms', [g]) for c in part.coords]


def lines(g):
    return [l for l in getattr(g, 'geoms', [g]) if l.geom_type == 'LineString' and l.length > 0.002]


if CFG['type'] == 'grid':
    axes = {'ns': [], 'ew': []}
    for axis, rows, base in (('ns', CFG['ns'], CFG['origin']['ns']), ('ew', CFG['ew'], CFG['origin']['ew'])):
        for name, num, d in [[base, 0, '']] + rows:
            pts = coords(name)
            if axis == 'ns':   # an east-west street: its latitude
                v = statistics.median(p[1] for p in pts); line = LineString([(minx - .01, v), (maxx + .01, v)])
            else:               # a north-south street: its longitude
                v = statistics.median(p[0] for p in pts); line = LineString([(v, miny - .01), (v, maxy + .01)])
            signed = num if d in ('N', 'E', '') else -num
            axes[axis].append([round(v, 5), signed])
            label = f'{num} {d}' if num else '0'
            for l in lines(line.intersection(outline)):
                out.append({'type': 'Feature', 'properties': {'role': 'base' if not num else 'mile', 'axis': axis, 'num': num, 'dir': d,
                                                              'street': name, 'label': label},
                            'geometry': {'type': 'LineString', 'coordinates': rnd(l)}})
        axes[axis].sort()
    meta = {'type': 'grid', 'axes': axes}
    print(f"{city}: {len(axes['ns'])} north-south positions, {len(axes['ew'])} east-west, {len(out)} line pieces")
else:
    div = linemerge(unary_union(by_name.get(CFG['street'], [])))
    if div.is_empty: raise SystemExit(f'{city}: no drawn street called {CFG["street"]!r}')
    for l in getattr(div, 'geoms', [div]):
        out.append({'type': 'Feature', 'properties': {'role': 'divide', 'street': CFG['street']}, 'geometry': {'type': 'LineString', 'coordinates': rnd(l)}})
    # Only streets whose East/West comes from the dividing street: some part of the street (either half)
    # within "near" metres of it. That leaves out pairs split by something else (Denison Rd E at Weston Rd,
    # Lakeshore Rd E in Mississauga, the two sides of a divided road).
    near = div.buffer(CFG.get('near', 400) / 111000)
    meets = {name[:-2] for name, gs in by_name.items() if name[-2:] in (' E', ' W') and any(g.intersects(near) for g in gs)}
    n = {'e': 0, 'w': 0}
    for name, gs in sorted(by_name.items()):
        side = 'e' if name.endswith(' E') else 'w' if name.endswith(' W') else None
        if not side or name in CFG.get('skip', []) or name[:-2] not in meets: continue
        n[side] += 1
        for g in gs:
            for l in getattr(g, 'geoms', [g]):
                out.append({'type': 'Feature', 'properties': {'role': side, 'street': name}, 'geometry': {'type': 'LineString', 'coordinates': rnd(l)}})
    meta = {'type': 'divide', 'street': CFG['street']}
    print(f"{city}: {CFG['street']} divides {n['e']} East and {n['w']} West streets")

path = os.path.join(DATA, 'addresses.geojson')
json.dump(dict(meta, type='FeatureCollection', kind=meta['type'], features=out), open(path, 'w'), separators=(',', ':'))
print(f'  addresses.geojson: {len(out)} features · {os.path.getsize(path) // 1024} KB')
