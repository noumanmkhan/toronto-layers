"""Scouting (October 11, 2026): what does Metrolinx's GO GTFS hold for GO buses?

For the "GO buses" idea (regional bus routes linking Toronto to the rest of the GTA). Downloads the
GO Transit GTFS (Metrolinx Open Data, Open Government Licence - Ontario - Metrolinx) and writes, into
raw/scouting/go_buses/:
  - summary.json: feed dates, route types, every bus route (number, name, colour), and per route its
    weekday trips, a typical midday wait, first/last departures, shapes in use, stops, stops inside
    Toronto, and how many of those Toronto stops are pick-up only / drop-off only;
  - shapes.geojson: each bus route's busiest pattern per direction (simplified ~20 m), for a look;
  - toronto_stops.geojson: every GO bus stop inside Toronto with its routes and pick-up/drop-off rules.
Nothing here feeds the map.
"""
import collections, csv, datetime as dt, io, json, os, time, urllib.request, zipfile
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union
from shapely.prepared import prep

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'raw', 'scouting', 'go_buses'); os.makedirs(OUT, exist_ok=True)
URL = 'https://assets.metrolinx.com/raw/upload/Documents/Metrolinx/Open%20Data/GO-GTFS.zip'
UA = {'User-Agent': 'city-layers-pipeline (github.com/noumanmkhan/city-layers)'}
ZIP = os.path.join(HERE, 'tmp', 'go_gtfs.zip'); os.makedirs(os.path.dirname(ZIP), exist_ok=True)

for i in range(4):
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=600) as r, open(ZIP, 'wb') as f:
            f.write(r.read())
        break
    except Exception as e:
        print('retry', i + 1, e); time.sleep(15 * (i + 1))
z = zipfile.ZipFile(ZIP)
print('files:', z.namelist())


def rows(name):
    if name not in z.namelist(): return
    with z.open(name) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig'))
        head = [h.strip() for h in next(r)]
        for row in r:
            yield {h: (row[i].strip() if i < len(row) else '') for i, h in enumerate(head)}


agencies = list(rows('agency.txt'))
routes = {r['route_id']: r for r in rows('routes.txt')}
types = collections.Counter(r.get('route_type') for r in routes.values())
bus = {k: r for k, r in routes.items() if r.get('route_type') in ('3', '700', '701', '702', '704', '715')}
print('route types', dict(types), '· bus routes', len(bus))

D = lambda s: dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))
cal, extra = {}, collections.defaultdict(dict)
for r in rows('calendar.txt'):
    cal[r['service_id']] = (D(r['start_date']), D(r['end_date']), [r[d] == '1' for d in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')])
for r in rows('calendar_dates.txt'):
    extra[r['service_id']][D(r['date'])] = r['exception_type'] == '1'
def active(sid, day):
    if day in extra.get(sid, {}): return extra[sid][day]
    c = cal.get(sid)
    return bool(c and c[0] <= day <= c[1] and c[2][day.weekday()])
alld = [c[0] for c in cal.values()] + [c[1] for c in cal.values()] + [d for e in extra.values() for d in e]
first, last = min(alld), max(alld)
day = max(dt.date.today() + dt.timedelta(days=1), first)
day += dt.timedelta(days=(2 - day.weekday()) % 7)          # next Wednesday
sat = day + dt.timedelta(days=3)
print('feed', first, '-', last, '· weekday', day, '· saturday', sat)

trips = {}
for r in rows('trips.txt'):
    if r['route_id'] not in bus: continue
    w, s = active(r['service_id'], day), active(r['service_id'], sat)
    if w or s:
        trips[r['trip_id']] = dict(route=r['route_id'], dir=r.get('direction_id') or '0', shape=r.get('shape_id', ''),
                                   head=r.get('trip_headsign', ''), wk=w, sat=s)
print('bus trips on those days', len(trips))

city = unary_union([shape(f['geometry']).buffer(0) for f in json.load(open(os.path.join(HERE, 'raw', 'city_bundle1.json')))['formermun']['features']])
city_p = prep(city)
stops = {r['stop_id']: r for r in rows('stops.txt')}

first_dep, last_dep = {}, {}
stop_info = collections.defaultdict(lambda: {'routes': set(), 'pick': collections.Counter(), 'drop': collections.Counter()})
route_stops = collections.defaultdict(set)
for r in rows('stop_times.txt'):
    t = trips.get(r['trip_id'])
    if not t: continue
    seq = int(r['stop_sequence']); tm = r.get('departure_time') or r.get('arrival_time')
    tid = r['trip_id']
    if tm:
        if tid not in first_dep or seq < first_dep[tid][0]: first_dep[tid] = (seq, tm)
    route_stops[t['route']].add(r['stop_id'])
    si = stop_info[r['stop_id']]
    si['routes'].add(t['route'])
    si['pick'][r.get('pickup_type') or '0'] += 1
    si['drop'][r.get('drop_off_type') or '0'] += 1

inside = {sid for sid in stop_info if sid in stops and stops[sid].get('stop_lat') and
          city_p.contains(Point(float(stops[sid]['stop_lon']), float(stops[sid]['stop_lat'])))}

shape_use = collections.defaultdict(collections.Counter)
per_route = collections.defaultdict(lambda: {'wk': 0, 'sat': 0, 'mid': collections.Counter(), 'deps': [], 'heads': collections.Counter()})
for tid, t in trips.items():
    pr = per_route[t['route']]
    if t['wk']:
        pr['wk'] += 1
        shape_use[(t['route'], t['dir'])][t['shape']] += 1
        if tid in first_dep:
            tm = first_dep[tid][1]; pr['deps'].append(tm)
            h = int(tm.split(':')[0])
            if 10 <= h < 15: pr['mid'][t['dir']] += 1
    if t['sat']: pr['sat'] += 1
    pr['heads'][t['head']] += 1

need = {max(c, key=c.get) for c in shape_use.values() if c}
pts = collections.defaultdict(list)
for r in rows('shapes.txt'):
    if r['shape_id'] in need:
        pts[r['shape_id']].append((int(r['shape_pt_sequence']), float(r['shape_pt_lon']), float(r['shape_pt_lat'])))

out, feats = [], []
for rid, r in sorted(bus.items(), key=lambda kv: (len(kv[1].get('route_short_name', '')), kv[1].get('route_short_name', ''))):
    pr = per_route.get(rid, {'wk': 0, 'sat': 0, 'mid': {}, 'deps': [], 'heads': {}})
    tor = route_stops[rid] & inside
    mid = max(pr['mid'].values()) if pr['mid'] else 0
    deps = sorted(pr['deps'])
    km_in = km = 0
    for d in ('0', '1'):
        c = shape_use.get((rid, d))
        if not c: continue
        sh = max(c, key=c.get); p = [(x, y) for _, x, y in sorted(pts.get(sh, []))]
        if len(p) < 2: continue
        g = LineString(p)
        if d == '0':
            km = round(g.length * 85, 1); km_in = round(g.intersection(city).length * 85, 1)
        g = g.simplify(0.0002)
        feats.append({'type': 'Feature', 'properties': {'route': r.get('route_short_name'), 'name': r.get('route_long_name'), 'dir': d,
                                                        'shape': sh, 'trips': c[sh], 'toronto': bool(tor)},
                      'geometry': {'type': 'LineString', 'coordinates': [[round(x, 5), round(y, 5)] for x, y in g.coords]}})
    out.append({'id': rid, 'short': r.get('route_short_name'), 'long': r.get('route_long_name'), 'type': r.get('route_type'),
                'color': r.get('route_color'), 'agency': r.get('agency_id'),
                'weekday_trips': pr['wk'], 'saturday_trips': pr['sat'],
                'midday_wait_min': round(300 / mid) if mid else None,
                'first_dep': deps[0] if deps else None, 'last_dep': deps[-1] if deps else None,
                'shapes_used_weekday': {d: len(shape_use.get((rid, d), {})) for d in ('0', '1')},
                'headsigns': dict(collections.Counter(pr['heads']).most_common(6)),
                'stops': len(route_stops[rid]), 'toronto_stops': len(tor), 'km_dir0': km, 'km_in_toronto_dir0': km_in,
                'toronto_pickup_only': sum(1 for s in tor if stop_info[s]['drop'].get('1', 0) >= sum(stop_info[s]['drop'].values()) * 0.9),
                'toronto_dropoff_only': sum(1 for s in tor if stop_info[s]['pick'].get('1', 0) >= sum(stop_info[s]['pick'].values()) * 0.9)})

tstops = []
for sid in sorted(inside):
    s = stops[sid]; si = stop_info[sid]
    tstops.append({'type': 'Feature', 'properties': {'id': sid, 'name': s.get('stop_name'), 'code': s.get('stop_code'),
                                                     'parent': s.get('parent_station'), 'loc_type': s.get('location_type'),
                                                     'routes': sorted(bus[x].get('route_short_name', x) for x in si['routes']),
                                                     'pickup': dict(si['pick']), 'dropoff': dict(si['drop'])},
                   'geometry': {'type': 'Point', 'coordinates': [float(s['stop_lon']), float(s['stop_lat'])]}})

summary = {'source': URL, 'fetched': dt.date.today().isoformat(), 'feed': [str(first), str(last)], 'weekday': str(day), 'saturday': str(sat),
           'files': z.namelist(), 'agencies': agencies, 'route_types': dict(types),
           'bus_routes': len(bus), 'bus_routes_running': sum(1 for x in out if x['weekday_trips'] or x['saturday_trips']),
           'bus_routes_touching_toronto': sum(1 for x in out if x['toronto_stops']),
           'bus_stops_in_toronto': len(inside), 'routes': out}
json.dump(summary, open(os.path.join(OUT, 'summary.json'), 'w'), indent=1)
json.dump({'type': 'FeatureCollection', 'features': feats}, open(os.path.join(OUT, 'shapes.geojson'), 'w'), separators=(',', ':'))
json.dump({'type': 'FeatureCollection', 'features': tstops}, open(os.path.join(OUT, 'toronto_stops.geojson'), 'w'), separators=(',', ':'))
print(json.dumps({k: v for k, v in summary.items() if k not in ('routes', 'files', 'agencies')}, indent=1))
for x in out:
    print(f"{x['short']:>5} {x['long'][:44]:44} wk {x['weekday_trips']:4} sat {x['saturday_trips']:4} mid {x['midday_wait_min']} "
          f"stops {x['stops']:3} TO {x['toronto_stops']:3} km {x['km_dir0']:6} inTO {x['km_in_toronto_dir0']:5} "
          f"pickOnly {x['toronto_pickup_only']} dropOnly {x['toronto_dropoff_only']} {x['first_dep']}-{x['last_dep']}")
