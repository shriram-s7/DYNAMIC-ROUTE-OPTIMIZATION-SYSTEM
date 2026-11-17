/* OptiFlow DRO - in-browser backend host.
 * Loads Pyodide, installs FastAPI, boots the real backend/main.py (via bridge.py)
 * and answers API requests posted from the page. Runs as a SharedWorker so the
 * manager page and the driver pop-up share one simulation (falls back to a Worker).
 */
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';
importScripts(PYODIDE + 'pyodide.js');

let bridge = null;
let looping = false;
const ports = [];

const ready = (async () => {
  const py = await loadPyodide({ indexURL: PYODIDE });
  await py.loadPackage(['micropip', 'ssl']);
  await py.runPythonAsync(
    "import micropip\nawait micropip.install(['fastapi==0.104.1','python-multipart==0.0.6'])"
  );
  for (const f of ['main.py', 'route_assignment_algorithm.py', 'bridge.py']) {
    const res = await fetch('/py/' + f);
    if (!res.ok) throw new Error('Could not load /py/' + f);
    py.FS.writeFile('/home/pyodide/' + f, await res.text());
  }
  py.runPython("import sys\nsys.path.insert(0, '/home/pyodide')\nimport bridge");
  bridge = py.globals.get('bridge');
})();

function loop() {
  const d = bridge.tick();
  if (d < 0) { looping = false; return; }
  setTimeout(loop, d);
}

async function onMessage(port, e) {
  const { id, method, url, body, contentType } = e.data;
  try {
    await ready;
    const r = await bridge.handle(method, url, body ? new Uint8Array(body) : null, contentType || '');
    const [status, text] = r.toJs();
    r.destroy && r.destroy();
    port.postMessage({ id, status, text });
    if (!looping) { looping = true; setTimeout(loop, 0); }
  } catch (err) {
    port.postMessage({ id, status: 500, text: JSON.stringify({ detail: String(err) }) });
  }
}

function attach(port) {
  ports.push(port);
  port.onmessage = (e) => onMessage(port, e);
  ready.then(() => port.postMessage({ ready: true }),
             (err) => port.postMessage({ fatal: String(err) }));
}

if (typeof SharedWorkerGlobalScope !== 'undefined' && self instanceof SharedWorkerGlobalScope) {
  self.onconnect = (e) => { const p = e.ports[0]; attach(p); p.start && p.start(); };
} else {
  attach(self);
}
