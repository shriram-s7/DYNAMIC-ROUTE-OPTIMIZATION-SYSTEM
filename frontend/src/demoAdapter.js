// Demo mode: route every axios call to the real FastAPI backend running in the browser
// (Pyodide inside a worker). Enabled only when built with VITE_DEMO_MODE=true.
import axios, { AxiosError } from 'axios';

function install() {
let port = null;
let nextId = 1;
const pending = new Map();
let setStatus = () => {};

const ready = new Promise((resolve, reject) => {
  const onMsg = (e) => {
    const m = e.data;
    if (m.ready) return resolve();
    if (m.fatal) return reject(new Error(m.fatal));
    const p = pending.get(m.id);
    if (p) { pending.delete(m.id); p(m); }
  };
  try {
    const w = typeof SharedWorker !== 'undefined'
      ? new SharedWorker('/demo-worker.js') : null;
    if (w) { port = w.port; port.onmessage = onMsg; port.start(); }
    else { const dw = new Worker('/demo-worker.js'); port = dw; dw.onmessage = onMsg; }
  } catch (err) { reject(err); }
});

function banner() {
  const el = document.createElement('div');
  el.style.cssText = 'position:fixed;z-index:99999;left:50%;transform:translateX(-50%);bottom:12px;' +
    'background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:999px;padding:6px 14px;' +
    'font:12px/1.4 system-ui,sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.35);pointer-events:none';
  document.addEventListener('DOMContentLoaded', () => document.body.appendChild(el));
  if (document.body) document.body.appendChild(el);
  setStatus = (t) => { el.textContent = t; el.style.display = t ? 'block' : 'none'; };
  setStatus('Starting in-browser backend (first load takes ~15-30s)...');
}
banner();
ready.then(() => { setStatus('Live demo: backend running in your browser. Sample fleet of 5 trucks preloaded'); setTimeout(() => setStatus(''), 4000); },
           (e) => setStatus('Demo failed to start: ' + e.message));

const inflightGets = new Map();
// The app polls GET /state on a timer. While the in-browser backend is busy (e.g. fetching
// road routes) polls would queue up and then flood the page, so share one in-flight request.
function adapter(config) {
  if ((config.method || 'get').toLowerCase() === 'get') {
    const key = config.url + JSON.stringify(config.params || {});
    if (inflightGets.has(key)) return inflightGets.get(key);
    const p = doRequest(config).finally(() => inflightGets.delete(key));
    inflightGets.set(key, p);
    return p;
  }
  return doRequest(config);
}

async function doRequest(config) {
  await ready;
  let url = new URL(config.url, 'http://demo');
  if (config.params) Object.entries(config.params).forEach(([k, v]) => url.searchParams.set(k, v));
  let body = null, contentType = '';
  const d = config.data;
  if (d instanceof FormData) {
    const req = new Request('http://demo/', { method: 'POST', body: d });
    contentType = req.headers.get('content-type');
    body = await req.arrayBuffer();
  } else if (d != null) {
    const s = typeof d === 'string' ? d : JSON.stringify(d);
    body = new TextEncoder().encode(s).buffer;
    contentType = 'application/json';
  }
  const m = await new Promise((resolve) => {
    const id = nextId++;
    pending.set(id, resolve);
    port.postMessage({ id, method: config.method, url: url.pathname + url.search, body, contentType });
  });
  // Demo convenience: after a reset, preload the 5-truck sample fleet so Start works immediately.
  if (config.method === 'post' && url.pathname === '/simulation/reset' && m.status === 200) {
    try {
      const csv = await (await fetch('/sample-trucks.csv')).text();
      const fd = new FormData();
      fd.append('file', new File([csv], 'trucks.csv', { type: 'text/csv' }));
      await adapter({ method: 'post', url: '/upload/trucks', data: fd });
    } catch (_) { /* demo still works with a manual CSV upload */ }
  }
  let data = m.text;
  try { data = JSON.parse(m.text); } catch (_) { /* keep text */ }
  const response = { data, status: m.status, statusText: String(m.status), headers: {}, config, request: {} };
  if (m.status >= 200 && m.status < 300) return response;
  throw new AxiosError('Request failed with status code ' + m.status, AxiosError.ERR_BAD_REQUEST, config, {}, response);
}

axios.defaults.adapter = adapter;
}

if (import.meta.env.VITE_DEMO_MODE === 'true') install();
