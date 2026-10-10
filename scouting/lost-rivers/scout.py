"""Scouting (October 11, 2026): which buried / lost waterways does OpenStreetMap (ODbL) map in Toronto
and Chicago? For a curated "Lost rivers" layer: geometry may only come from openly licensed data, so a
creek not mapped here is left out rather than traced from a historical map.

Asks Overpass for, in each city's box: waterways named after known lost creeks; any waterway in a
tunnel (culverted); and ways tagged as historic, was:, disused:, removed: or abandoned: waterways.
Writes scouting/lost-rivers/out/<city>.geojson (every way, with its tags) and summary.json (per name:
ways, length in km, length in a tunnel, tag mix). Nothing here feeds the map."""
import json, math, os, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'city-layers-scouting (github.com/noumanmkhan/city-layers)'}
SERVERS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']
CITIES = {
    'toronto': ((43.57, -79.65, 43.87, -79.10), 'Garrison|Taddle|Castle Frank|Russell|Mud Creek|Yellow Creek|Walmsley|Wendigo|Lavender|Small|Brewery|Burke|Cudmore|Spring Creek|Dufferin Creek|Rosedale|Chaplin|Mimico|Black Creek|Silverthorn|Wilket|Massey|Highland|Westlake|Ashbridge|Taylor'),
    'chicago': ((41.62, -87.96, 42.04, -87.50), 'Mud Lake|Chicago River|Bubbly|Calumet|Skokie|Crawford|Hubbard|Portage|Ogden|Stickney|Kedzie|Wolf|Grand Calumet|Lake Calumet|Sauganash|Indian Boundary'),
}


def overpass(q):
    for i in range(6):
        url = SERVERS[i % 2]
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({'data': q}).encode(), headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r: return json.loads(r.read())
        except Exception as e:
            print('  retry', i + 1, url, e); time.sleep(20 * (i + 1))
    raise RuntimeError('overpass failed')


def km(coords):
    t = 0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        t += math.hypot((x2 - x1) * 111.32 * math.cos(math.radians(y1)), (y2 - y1) * 110.57)
    return t


summary = {}
for city, ((s, w, n, e), names) in CITIES.items():
    b = f'{s},{w},{n},{e}'
    q = f'''[out:json][timeout:240];
(
  way["waterway"]["name"~"{names}",i]({b});
  way["waterway"]["tunnel"]({b});
  way["historic:waterway"]({b}); way["was:waterway"]({b}); way["disused:waterway"]({b});
  way["removed:waterway"]({b}); way["abandoned:waterway"]({b}); way["historic"="waterway"]({b});
  way["historic"]["name"~"Creek|River|Brook|Lake",i]({b});
);
out tags geom;'''
    d = overpass(q)
    feats, per = [], {}
    for el in d['elements']:
        if el['type'] != 'way' or 'geometry' not in el: continue
        c = [[p['lon'], p['lat']] for p in el['geometry']]
        t = el.get('tags', {})
        feats.append({'type': 'Feature', 'properties': dict(t, _id=el['id']), 'geometry': {'type': 'LineString', 'coordinates': c}})
        nm = t.get('name') or t.get('old_name') or '(unnamed ' + (t.get('waterway') or 'other') + ')'
        p = per.setdefault(nm, {'ways': 0, 'km': 0, 'km_tunnel': 0, 'tags': {}})
        L = km(c); p['ways'] += 1; p['km'] += L
        if t.get('tunnel') or t.get('layer', '0').startswith('-'): p['km_tunnel'] += L
        for k in ('waterway', 'tunnel', 'historic', 'historic:waterway', 'was:waterway', 'disused:waterway', 'removed:waterway', 'intermittent', 'location'):
            if k in t: p['tags'][k + '=' + t[k]] = p['tags'].get(k + '=' + t[k], 0) + 1
    for p in per.values(): p['km'] = round(p['km'], 2); p['km_tunnel'] = round(p['km_tunnel'], 2)
    summary[city] = dict(sorted(per.items(), key=lambda kv: -kv[1]['km']))
    json.dump({'type': 'FeatureCollection', 'features': feats}, open(os.path.join(OUT, city + '.geojson'), 'w'))
    print(city, len(feats), 'ways')
    for nm, p in summary[city].items():
        if not nm.startswith('(unnamed'): print(f"  {nm:40} ways {p['ways']:4} km {p['km']:7} tunnel {p['km_tunnel']:6} {p['tags']}")
    un = {k: v for k, v in summary[city].items() if k.startswith('(unnamed')}
    print('  unnamed:', {k: (v['ways'], v['km'], v['km_tunnel']) for k, v in un.items()})
    time.sleep(10)
json.dump(summary, open(os.path.join(OUT, 'summary.json'), 'w'), indent=1)
