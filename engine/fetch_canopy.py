"""Tree canopy share for each unit (neighbourhood / community area), from open land-cover rasters.
Runs in GitHub Actions (fetch-canopy.yml): the sources are large downloads the sandbox can't reach.

Sources, set per city in cities/<city>/canopy.json ("sources", in order of preference; the first that
works is the one the map uses, the others are kept for comparison):
  - "worldcover": ESA WorldCover 2021 v200, 10 m (CC BY 4.0), classes 10 (tree cover) and 80 (water).
    Satellite land cover at 10 m misses some street trees, so it reads lower than city studies.

Canopy share = tree cells / land cells (water left out of the denominator) inside each unit, at WorldCover's
own 10 m. (Toronto's 2018 Tree Canopy Study land cover was tried first, October 11, 2026: its file
geodatabase raster wouldn't open with Ubuntu's GDAL 3.8. WorldCover's citywide 30.5% sits inside that
study's 28-31%, and Chicago's 15.5% matches the 16% of the 2020 Chicago Region Tree Census, so the one
open source serves both cities alike.)

Writes cities/<city>/raw/canopy/canopy.json: {used, sources: {name: {year, licence, cell, units: {code:
pct}, city: pct, note}}}, and prints what it found (classes, sizes, citywide share) to the log.

Usage: python3 engine/fetch_canopy.py <city>
"""
import json, os, subprocess, sys, time, urllib.request
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely.geometry import shape, mapping
import shapely
from pyproj import Transformer

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
city = sys.argv[1]
CFG = json.load(open(os.path.join(ROOT, 'cities', city, 'canopy.json')))
CITY = json.load(open(os.path.join(ROOT, 'cities', city, 'city.json')))
OUT = os.path.join(ROOT, 'cities', city, 'raw', 'canopy'); os.makedirs(OUT, exist_ok=True)
WORK = os.path.join(ROOT, 'cities', city, 'tmp', 'canopy'); os.makedirs(WORK, exist_ok=True)
UA = {'User-Agent': 'city-layers-pipeline (github.com/noumanmkhan/city-layers)'}

units_file = os.path.join(ROOT, 'docs', city, 'data', CFG['units'] + '.geojson')
UNITS = [(str(f['properties']['code']), shape(f['geometry']).buffer(0)) for f in json.load(open(units_file))['features']]
minx = min(g.bounds[0] for _, g in UNITS); miny = min(g.bounds[1] for _, g in UNITS)
maxx = max(g.bounds[2] for _, g in UNITS); maxy = max(g.bounds[3] for _, g in UNITS)
print(city, len(UNITS), 'units, bounds', round(minx, 3), round(miny, 3), round(maxx, 3), round(maxy, 3))


def download(url, path, tries=4):
    if os.path.exists(path) and os.path.getsize(path) > 0: return path
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=900) as r, open(path, 'wb') as f:
                while True:
                    b = r.read(1 << 22)
                    if not b: break
                    f.write(b)
            print('  got', url, os.path.getsize(path) // (1 << 20), 'MB'); return path
        except Exception as e:
            print('  retry', i + 1, url, e); time.sleep(20 * (i + 1))
    raise RuntimeError('download failed: ' + url)


def sh(*args):
    print('  $', ' '.join(args)[:300])
    r = subprocess.run(args, capture_output=True, text=True)
    if r.stdout: print(r.stdout[-6000:])
    if r.returncode: print(r.stderr[-4000:]); raise RuntimeError('command failed')
    return r.stdout


def zonal(tif, tree_vals, water_vals, nodata_vals):
    """Canopy % per unit and for all units together."""
    out, T, Lnd = {}, 0, 0
    with rasterio.open(tif) as src:
        to = Transformer.from_crs('EPSG:4326', src.crs, always_xy=True).transform
        for code, g in UNITS:
            gg = shapely.transform(g, lambda c: np.column_stack(to(c[:, 0], c[:, 1])))
            win = from_bounds(*gg.bounds, transform=src.transform).round_offsets().round_lengths()
            a = src.read(1, window=win, boundless=True, fill_value=nodata_vals[0] if nodata_vals else 0)
            inside = ~geometry_mask([mapping(gg)], out_shape=a.shape, transform=src.window_transform(win))
            land = inside & ~np.isin(a, list(water_vals) + list(nodata_vals))
            tree = land & np.isin(a, list(tree_vals))
            nl, nt = int(land.sum()), int(tree.sum())
            out[code] = round(100 * nt / nl) if nl else None
            T += nt; Lnd += nl
    return out, (round(100 * T / Lnd, 1) if Lnd else None)


def worldcover(spec):
    tiles = []
    for lat in range(int(np.floor(miny / 3) * 3), int(np.floor(maxy / 3) * 3) + 1, 3):
        for lon in range(int(np.floor(minx / 3) * 3), int(np.floor(maxx / 3) * 3) + 1, 3):
            name = f"ESA_WorldCover_10m_2021_v200_{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}_Map.tif"
            tiles.append(download('https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/' + name, os.path.join(WORK, name)))
    vrt = os.path.join(WORK, 'wc.vrt'); sh('gdalbuildvrt', '-overwrite', vrt, *tiles)
    tif = os.path.join(WORK, 'worldcover_clip.tif')
    sh('gdalwarp', '-overwrite', '-te', str(minx - .01), str(miny - .01), str(maxx + .01), str(maxy + .01), '-r', 'near', '-co', 'COMPRESS=DEFLATE', vrt, tif)
    units, whole = zonal(tif, {10}, {80}, [0])
    return {'year': 2021, 'licence': 'CC BY 4.0 (ESA WorldCover 2021 v200)', 'cell': '10 m', 'units': units, 'city': whole, 'source': 'https://esa-worldcover.org'}


FN = {'worldcover': worldcover}
res, used = {}, None
for spec in CFG['sources']:
    try:
        r = FN[spec['type']](spec)
        res[spec['type']] = r
        print(spec['type'], 'citywide canopy', r['city'], '% · units with a value', sum(v is not None for v in r['units'].values()))
        used = used or spec['type']
    except Exception as e:
        print(spec['type'], 'FAILED:', e)
if not used: raise SystemExit('no canopy source worked')
json.dump({'used': used, 'sources': res}, open(os.path.join(OUT, 'canopy.json'), 'w'), indent=1)
print('using', used)
if len(res) > 1:
    a, b = list(res.values())[:2]
    d = [a['units'][k] - b['units'][k] for k in a['units'] if a['units'][k] is not None and b['units'].get(k) is not None]
    print('difference first - second source: mean', round(sum(d) / len(d), 1), 'min', min(d), 'max', max(d))
