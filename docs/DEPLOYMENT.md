# Deployment: hosted demo

Live: **https://optiflow-dro.vercel.app** (Vercel project `optiflow-dro`).

## Why it is not a normal Vercel backend

The backend keeps one in-memory `WorldState` and advances it in a background thread with `time.sleep`. Vercel's serverless functions are stateless and short-lived, so that design cannot run there. Instead of rewriting it, the hosted build runs the **same backend code in the browser**:

| Piece | Role |
|---|---|
| `frontend/public/demo-worker.js` | SharedWorker (Worker fallback). Loads Pyodide, installs FastAPI, boots the backend. Shared so the Driver View pop-up sees the same simulation. |
| `frontend/public/py/bridge.py` | Dispatches requests straight into the FastAPI ASGI app, replaces the simulation thread with a `tick()` driven by the worker, and shims `requests` with synchronous XHR so OSRM road routing still works (straight-line fallback otherwise). |
| `frontend/src/demoAdapter.js` | axios adapter that sends every API call to the worker; preloads `public/demo-trucks.csv` after each reset. Active only when built with `VITE_DEMO_MODE=true`. |
| `frontend/scripts/copy-backend.mjs` | Copies `backend/main.py` and `route_assignment_algorithm.py` into `public/py/` so the demo runs the real code. |

Code changes made to the backend for this: the loop body was extracted into `simulation_tick()` (the local server still calls it in the same loop), and the random-hub auto-seed of default trucks was fixed (wrong import and missing required `Truck` fields).

## Run the demo build locally

```bash
cd frontend
npm install
npm run dev:demo      # or: npm run build:demo && npx vite preview
```

The normal `npm run dev` + `python backend/main.py` workflow is unchanged.

## Deploy

```bash
cd frontend
vercel deploy --prod
```

`frontend/vercel.json` sets the build to `npm run build:demo` and the output to `dist`. Keep `public/py/*.py` in sync by running `npm run build:demo` (it copies from `backend/`) before committing backend changes.

## Limits

- First load downloads Pyodide (~10 MB) from jsDelivr and FastAPI from PyPI; needs internet.
- State is per browser and lost on reload.
