"""
Browser bridge for the OptiFlow DRO demo.

Runs the REAL FastAPI backend (backend/main.py) inside Pyodide (WebAssembly) so the
hosted demo behaves exactly like the local app, with no separate server.

- Requests are dispatched straight into the FastAPI ASGI app (no network).
- The simulation thread is replaced by `tick()`, driven by the JS worker.
- `requests` is shimmed with a synchronous XHR so OSRM road routing still works,
  falling back to straight-line routes exactly as the backend already does.
"""
import sys, types, json


# ---- 1. `requests` shim (OSRM over synchronous XHR; only available in a worker) ----
class _RequestException(Exception):
    pass


class _Timeout(_RequestException):
    pass


class _Response:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text

    def json(self):
        return json.loads(self.text)


def _get(url, params=None, timeout=10, **kw):
    from urllib.parse import urlencode
    from js import XMLHttpRequest
    if params:
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    try:
        xhr = XMLHttpRequest.new()
        xhr.open("GET", url, False)
        xhr.send()
        return _Response(int(xhr.status), str(xhr.responseText))
    except Exception as e:  # network error / CORS / offline
        raise _RequestException(str(e))


_requests = types.ModuleType("requests")
_requests.get = _get
_requests.exceptions = types.SimpleNamespace(Timeout=_Timeout, RequestException=_RequestException)
sys.modules["requests"] = _requests


# ---- 2. FastAPI without worker threads (Pyodide has none): run sync endpoints inline ----
async def _inline(func, *args, **kwargs):
    return func(*args, **kwargs)


import starlette.concurrency as _sc
import fastapi.routing as _fr
_sc.run_in_threadpool = _inline
_fr.run_in_threadpool = _inline

import main  # backend/main.py, copied next to this file at build time

# The backend starts a Thread for the simulation; the demo drives it via tick() instead.
main.Thread = lambda *a, **k: types.SimpleNamespace(start=lambda: None)


async def handle(method, url, body, content_type):
    """Dispatch one HTTP request into the FastAPI app. Returns (status, json_text)."""
    from urllib.parse import urlsplit
    sp = urlsplit(url)
    body = bytes(body) if body is not None else b""
    headers = [(b"host", b"demo"), (b"content-length", str(len(body)).encode())]
    if content_type:
        headers.append((b"content-type", content_type.encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method.upper(), "scheme": "http", "path": sp.path,
        "raw_path": sp.path.encode(), "query_string": sp.query.encode(),
        "headers": headers, "server": ("demo", 80), "client": ("demo", 0), "root_path": "",
    }
    sent = {"done": False}
    out = {"status": 500, "body": b""}

    async def receive():
        if not sent["done"]:
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"")

    await main.app(scope, receive, send)
    return out["status"], out["body"].decode("utf-8")


def tick():
    """One simulation step. Returns the delay (ms) before the next one, or -1 when idle."""
    ws = main.world_state
    if not ws.simulation_running:
        return -1
    if ws.simulation_paused:
        return 200
    main.simulation_tick()
    return max(1.0, 100.0 / ws.simulation_speed)
