# Eco-Speed Advisor (V0)

Live, fuel-optimal target speeds for a 2026 Kia Sportage (petrol) on I-75 between
Georgia Tech and Marietta, GA. Phone GPS only, no traffic, no backend.

- `pipeline/` — offline Python: route + speed limits (OSRM + OpenStreetMap), elevation
  (USGS EPQS), ~100 m segments, physics fuel model, dynamic-programming speed optimiser,
  speed-limit baseline, JSON export.
- `web/` — static mobile web app (plain ES modules, no build step): GPS, map-matching,
  target + cue, savings, trip history, simulation mode.

## Quick start

```bash
pip install requests numpy scipy pyyaml shapely pyproj pytest matplotlib

# Real data (needs internet; responses are cached in pipeline/cache/)
python -m pipeline.run_all --plot

# Or the built-in offline DEMO route (approximate, no network needed)
python -m pipeline.run_all --offline --plot

pytest                                   # pipeline tests (Milestones 1-4)
node --test tests/web_sim.test.mjs       # web drive-loop tests (Milestone 5 logic)
```

Run the web app locally:

```bash
cd web && python -m http.server 8000
# open http://localhost:8000/?sim=1          simulated drive (no GPS needed)
# open http://localhost:8000/?sim=1&rate=30&profile=limit
```

On the phone the app needs **HTTPS** (Geolocation + Wake Lock). Deploy the `web/` folder to
GitHub Pages, Netlify or Vercel.

## Configuration

| File | What to change |
| --- | --- |
| `config/route.yaml` | Your real on-ramp (`start`) and off-ramp (`end`). Default end is an **assumed** Exit 263. Add `via_northbound` points if the router strays off the I-75 mainline. |
| `config/sportage_2026.yaml` | Vehicle physics (all approximate), fuel price, min speed (45 mph), accel limits, `time_weight` (`null` = auto: most fuel saved within +2 min/trip). |

Re-run `python -m pipeline.run_all` after any config change; it rewrites `web/data/`.

## Simulation mode (`?sim=1`)

| Param | Default | Meaning |
| --- | --- | --- |
| `rate` | 10 | playback speed (x real time) |
| `profile` | `target` | `target` (follow eco target with human wobble), `limit`, `const` |
| `mph` | 60 | speed for `profile=const` |
| `noise` | 3 | GPS position noise (m) |
| `stopat` | — | park for 130 s at this km (tests auto-end) |
| `seed` | 1 | random seed |

Direction in sim follows Settings (Auto drives northbound). Simulated trips are kept
separate from real ones in the monthly total.

## How it works

1. **Route** — OSRM gives one ordered polyline per direction; each point takes `maxspeed`
   from the nearest same-direction I-75 OSM way (express/toll lanes excluded). Missing
   tags default to 55 mph inside I-285 and 65 mph outside (logged).
2. **Segments** — resampled every 25 m (UTM 16N), elevation smoothed over ~200 m
   (Savitzky–Golay), aggregated into ~100 m segments; grade clamped to ±6%.
3. **Fuel model** — tractive force (inertia, drag, rolling, grade) → power → fuel with
   an idle term and fuel cut on overrun. `engine_eff` is calibrated so steady 65 mph on
   flat ground = EPA highway mpg.
4. **Optimiser** — DP over (segment, speed on a 1 mph grid), cost = fuel + `time_weight`
   × time, with limit, min-speed and comfort-acceleration constraints.
5. **App** — map-matches each fix (windowed search, 75 m off-route cutoff), blends the
   target over the last 30% of a segment, cues with a ±2 mph band (with hysteresis),
   integrates your estimated fuel with the same model, and compares against the baseline.

## Safety

Advisory only. The app never advises above the posted limit or below the minimum
speed, needs no input while driving, and ends trips automatically (end of route, or
stopped > 2 min). Test as a passenger first.

## Debugging real drives

Every trip's GPS fixes (with match + advice) are saved on the phone; Settings →
"Export last GPS log (JSON)".
