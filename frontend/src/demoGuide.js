// Demo-only interactive walkthrough. Loaded only when built with VITE_DEMO_MODE=true;
// it never ships in (or touches) the normal prototype. It highlights the real buttons,
// tells the visitor what to click, and advances automatically as they do it.

function install() {
  const STORE = 'dro-demo-guide-seen';
  // Page text without the guide's own card, so step wording can never satisfy a step.
  const text = () => {
    const c = document.querySelector('.dg-card');
    return (document.body.innerText || '').replace(c ? c.innerText : '', '');
  };
  const btn = (label) =>
    [...document.querySelectorAll('button')].find(
      (b) => !b.closest('.dg-card') && !b.classList.contains('dg-pill') && b.textContent.replace(/\s+/g, ' ').trim().includes(label));
  const byText = (needle, sel = 'div,span,p,h3,h4,label') =>
    [...document.querySelectorAll(sel)].find((e) => e.children.length < 6 && (e.textContent || '').trim().startsWith(needle));

  const state = () => {
    const t = text();
    // The role switcher (Manager / Driver Follow) only exists while a simulation is running,
    // so this also holds in the driver panel where 'System Active' is not shown.
    const started = t.includes('System Active') || t.includes('Driver Follow');
    return {
      hubs: /\(\d+ units/.test(t) || started,
      started,
      failed: t.includes('Commit Failed'),
      sensorOpen: t.includes('Select Impact Type'),
      placing: t.includes('PLACING RAIN') || t.includes('PLACING TRAFFIC'),
      driverPanel: t.includes('Your Truck'),
    };
  };

  // Arms the rain tool if needed, then sends the same map click a visitor would make, on a truck.
  async function placeRain() {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    if (!state().placing) {
      if (!state().sensorOpen) { const a = btn('Add Impact'); if (a) { a.click(); await wait(400); } }
      const r = btn('Add Rain'); if (r) { r.click(); await wait(400); }
    }
    // Widen the rain zone so it is clearly visible at this zoom (React-controlled range input).
    const slider = [...document.querySelectorAll('input[type=range]')].find((x) => x.max === '15');
    if (slider) {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      set.call(slider, '15');
      slider.dispatchEvent(new Event('input', { bubbles: true }));
      await wait(1500); // the app re-binds its map click handler on its next state refresh
    }
    const canvas = document.querySelector('.maplibregl-canvas-container') || document.querySelector('.maplibregl-canvas');
    if (!canvas) return;
    // The canvas container itself has no height; measure the actual canvas.
    const cr = (document.querySelector('.maplibregl-canvas') || canvas).getBoundingClientRect();
    // Truck markers are the 56px wrappers. The map may still be flying in after Start, so wait
    // until the truck stops moving on screen before reading its position.
    const findTruck = () => {
      const trucks = [...document.querySelectorAll('.maplibregl-marker')].filter((m) => m.style.width === '56px' || (m.firstElementChild && m.firstElementChild.style.width === '56px'));
      const rects = trucks.map((m) => m.getBoundingClientRect()).filter((q) => q.left > 440 && q.top > 90 && q.right < cr.right && q.bottom < cr.bottom - 80);
      return rects[0];
    };
    let r = findTruck();
    for (let k = 0; k < 20; k++) {
      await wait(250);
      const n = findTruck();
      const still = r && n && Math.abs(n.left - r.left) < 1 && Math.abs(n.top - r.top) < 1;
      r = n;
      if (still) break;
    }
    const x = r ? r.left + r.width / 2 : cr.left + cr.width * 0.62;
    const y = r ? r.top + r.height / 2 : cr.top + cr.height * 0.5;
    const o = { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, view: window };
    ['mousedown', 'mouseup', 'click'].forEach((t) => canvas.dispatchEvent(new MouseEvent(t, o)));
  }

  // needs: what must be true for the step to make sense (we step back if the visitor hits Reset).
  const steps = [
    {
      title: 'Welcome to OptiFlow DRO',
      body: 'A live simulator where a fleet of trucks delivers from the <b>Trichy Central Depot</b> to hubs under strict deadlines, and the plan is re-evaluated when things go wrong. This short tour (about 2 minutes) shows you exactly what to click.',
      next: 'Start the tour',
    },
    {
      title: '1. Your fleet is already loaded',
      body: 'In a normal run you upload a trucks CSV here. For the demo, <b>3 trucks (TRUCK001 to TRUCK003)</b> are preloaded, so you can skip the upload.',
      target: () => byText('Demo: 3 trucks'),
      next: 'Next',
    },
    {
      title: '2. Create the delivery hubs',
      body: 'Click <b>📍 Create Fixed Hubs</b> in the left panel. A pop-up will say the hubs were created. Click <b>OK</b> on it.',
      target: () => btn('Create Fixed Hubs'),
      done: (s) => s.hubs,
      doIt: () => btn('Create Fixed Hubs'),
    },
    {
      title: '3. Hubs are ready',
      body: 'The <b>📦 boxes on the map</b> are delivery hubs around the depot, and the left list shows each hub with its demand and distance. Next, we start the plan.',
      target: () => byText('📍 Hubs', 'h2,h3,h4,div,span'),
      needs: 'hubs',
      next: 'Next',
    },
    {
      title: '4. Start the simulation',
      body: 'Click the green <b>Start</b> button. The system assigns hubs to trucks so deadlines, driving time and fuel limits all hold, then trucks start moving.',
      target: () => btn('Start'),
      needs: 'hubs',
      done: (s) => s.started,
      doIt: () => btn('Start'),
      hint: (s) => (s.failed ? 'The commit was rejected by the deadline rules. Click <b>Reset</b>, then create hubs and Start again.' : ''),
    },
    {
      title: '5. Watch the trucks',
      body: 'The map zooms in for you. Trucks leave the depot and follow <b>real road routes</b> (the blue lines) to their hubs. Each truck commits to a destination and only re-plans at safe decision points, like a real dispatcher would. Scroll or drag the map to look closer.',
      needs: 'started',
      next: 'Next',
    },
    {
      title: '6. Speed it up',
      body: 'Drag the <b>Speed</b> slider (top right) to the right to run the day faster. You can also <b>Pause</b> and resume there.',
      target: () => {
        const r = document.querySelector('input[type=range]');
        return r ? r.closest('div') : null;
      },
      needs: 'started',
      next: 'Next',
    },
    {
      title: '7. Inject a disruption',
      body: 'Click <b>Add Impact</b> (bottom right) to open the disruption tools.',
      target: () => btn('Add Impact'),
      needs: 'started',
      done: (s) => s.sensorOpen,
      doIt: () => btn('Add Impact'),
    },
    {
      title: '8. Choose rain',
      body: 'Click <b>🌧 Add Rain</b>. This only <b>arms</b> the tool (the button turns blue and says ON); the rain itself is created in the next step when you click the map. Optionally drag the radius slider first to widen the rain area.',
      target: () => btn('Add Rain'),
      needs: 'started',
      done: (s) => s.placing,
      doIt: () => btn('Add Rain'),
    },
    {
      title: '9. Drop the rain on the map',
      body: 'Now <b>click on the map</b>, ideally on a moving truck or its blue route. A pop-up confirms the weather sensor; click <b>OK</b>. A <b>pale blue circle</b> marks the rain zone, and trucks inside it slow down (see <i>Active Environment Impacts</i> in the decisions panel). Not sure where? Press <b>Place it for me</b>: it drops a 15 km rain zone on a truck.',
      needs: 'started',
      next: 'Next',
      doIt: placeRain,
      doLabel: 'Place it for me',
      advanceAfterDo: true,
    },
    {
      title: '10. See the decisions',
      body: 'Open <b>⚡ Live Impacts &amp; Decisions</b> (bottom left). It lists every dispatch decision with its explanation: moving, delivered, re-planned, blocked.',
      target: () => byText('⚡', 'div') || byText('Live Impacts', 'div'),
      needs: 'started',
      next: 'Next',
    },
    {
      title: '11. Change a deadline or demand',
      body: 'In the left panel, scroll to <b>Delivery Deadlines</b>. Edit a hub\'s deadline or demand, and the plan re-evaluates at the truck\'s next safe decision point.',
      target: () => byText('Delivery Deadlines', 'h3,h4,div,span'),
      needs: 'started',
      next: 'Next',
    },
    {
      title: '12. Switch to the driver side',
      body: 'Click <b>Driver View</b> at the top of the left panel. Pick a truck under <b>Your Truck</b> to see its status, fuel and current task. (Click <b>Manager</b> to come back; <b>🛰 Fleet Dashboard</b> shows every truck.)',
      target: () => btn('Driver View'),
      needs: 'started',
      done: (s) => s.driverPanel,
      doIt: () => btn('Driver View'),
    },
    {
      title: '13. Open the navigation screen',
      body: 'Choose a truck, then click the green <b>Open in Driver View</b> button. A <b>separate window</b> opens with the Google-Maps-style turn-by-turn screen: your truck on the road, the red route, remaining distance, ETA and manager instructions. Keep both windows visible, as they update together. <b>If nothing opens, allow pop-ups for this site</b> (icon in the address bar) and click again.',
      target: () => btn('Open in Driver View'),
      needs: 'started',
      next: 'Next',
      doIt: () => btn('Open in Driver View'),
    },
    {
      title: 'You are all set',
      body: 'That is the full workflow. Click <b>Reset</b> in the left panel to start over, or keep exploring (roadblocks, instructions to a truck, demand changes). You can reopen this guide any time with the <b>🧭 Guide</b> button.',
      next: 'Finish',
    },
  ];

  // Pop-up blockers silently kill the driver window; detect it and tell the visitor what to do.
  const nativeOpen = window.open.bind(window);
  window.open = (...a) => {
    const w = nativeOpen(...a);
    if (!w && typeof a[0] === 'string' && a[0].includes('driver.html')) {
      const url = a[0];
      const t = document.createElement('div');
      t.style.cssText = 'position:fixed;z-index:100000;left:50%;top:70px;transform:translateX(-50%);background:#7f1d1d;color:#fee2e2;border-radius:10px;padding:10px 14px;font:13px system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.4);max-width:380px';
      t.innerHTML = 'Your browser blocked the driver window. Allow pop-ups for this site, or <a href="' + url + '" target="_blank" style="color:#fff;font-weight:700">open the driver view in a new tab</a>.';
      document.body.appendChild(t);
      setTimeout(() => t.remove(), 12000);
    }
    return w;
  };

  // ---------- UI ----------
  const css = document.createElement('style');
  css.textContent = `
  .dg-ring{position:fixed;z-index:99997;pointer-events:none;border:3px solid #f59e0b;border-radius:10px;
    box-shadow:0 0 0 4px rgba(245,158,11,.25),0 0 24px rgba(245,158,11,.6);animation:dgp 1.4s ease-in-out infinite;display:none}
  @keyframes dgp{50%{box-shadow:0 0 0 9px rgba(245,158,11,.12),0 0 30px rgba(245,158,11,.8)}}
  .dg-card{position:fixed;z-index:99999;top:12px;left:50%;transform:translateX(-50%);width:min(380px,calc(100vw - 24px));
    background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:14px;padding:14px 16px;
    font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;box-shadow:0 12px 40px rgba(0,0,0,.45)}
  .dg-card h4{margin:0 0 6px;font-size:15px;color:#fff}
  .dg-card p{margin:0 0 10px}
  .dg-card b{color:#fbbf24}
  .dg-hint{background:#7f1d1d;color:#fee2e2;border-radius:8px;padding:6px 8px;margin:0 0 10px;font-size:13px}
  .dg-wait{color:#94a3b8;font-size:12.5px;margin:0 0 10px}
  .dg-row{display:flex;gap:8px;align-items:center}
  .dg-row .sp{flex:1}
  .dg-b{border:1px solid #475569;background:#1e293b;color:#e2e8f0;border-radius:8px;padding:6px 12px;font:inherit;font-size:13px;cursor:pointer}
  .dg-b:hover{background:#334155}
  .dg-pri{background:#f59e0b;border-color:#f59e0b;color:#111827;font-weight:600}
  .dg-pri:hover{background:#fbbf24}
  .dg-link{background:none;border:none;color:#94a3b8;font-size:12.5px;cursor:pointer;text-decoration:underline;padding:0}
  .dg-dots{display:flex;gap:4px;margin-bottom:8px}
  .dg-dot{height:4px;flex:1;border-radius:2px;background:#334155}.dg-dot.on{background:#f59e0b}
  .dg-pill{position:fixed;z-index:99999;top:12px;left:50%;transform:translateX(-50%);background:#0f172a;color:#fbbf24;
    border:1px solid #475569;border-radius:999px;padding:6px 14px;font:600 13px system-ui,sans-serif;cursor:pointer;
    box-shadow:0 6px 20px rgba(0,0,0,.35)}
  @media (max-width:700px){.dg-card{top:auto;bottom:12px}}
  `;
  document.head.appendChild(css);

  const ring = document.createElement('div');
  ring.className = 'dg-ring';
  const card = document.createElement('div');
  card.className = 'dg-card';
  const pill = document.createElement('button');
  pill.className = 'dg-pill';
  pill.textContent = '🧭 Guide';
  pill.style.display = 'none';
  document.body.append(ring, card, pill);

  let i = 0;
  let open = true;
  let lastScrolled = null;

  const save = () => { try { localStorage.setItem(STORE, '1'); } catch (_) { /* optional */ } };
  const close = () => { open = false; save(); render(); };
  pill.onclick = () => { open = true; render(); };

  const stepFor = (key) => steps.findIndex((s) => (key === 'hubs' ? s.title.startsWith('2.') : s.title.startsWith('4.')));

  function render() {
    pill.style.display = open ? 'none' : 'block';
    card.style.display = open ? 'block' : 'none';
    if (!open) { ring.style.display = 'none'; return; }
    const s = steps[i];
    const st = state();
    const hint = s.hint ? s.hint(st) : '';
    const dots = steps.map((_, k) => `<div class="dg-dot ${k <= i ? 'on' : ''}"></div>`).join('');
    card.innerHTML = `
      <div class="dg-dots">${dots}</div>
      <h4>${s.title}</h4>
      <p>${s.body}</p>
      ${hint ? `<div class="dg-hint">${hint}</div>` : ''}
      ${s.done && !s.next ? '<div class="dg-wait">Waiting for you to do this step... it moves on automatically.</div>' : ''}
      <div class="dg-row">
        ${i > 0 ? '<button class="dg-b" data-a="back">Back</button>' : ''}
        <span class="sp"></span>
        <button class="dg-link" data-a="skip">${i === steps.length - 1 ? '' : 'Skip tour'}</button>
        ${s.doIt ? `<button class="dg-b" data-a="do">${s.doLabel || 'Do it for me'}</button>` : ''}
        ${s.next ? `<button class="dg-b dg-pri" data-a="next">${s.next}</button>` : ''}
      </div>`;
  }

  card.addEventListener('click', (e) => {
    const a = e.target.getAttribute && e.target.getAttribute('data-a');
    if (!a) return;
    if (a === 'back') { i = Math.max(0, i - 1); render(); }
    else if (a === 'next') { if (i === steps.length - 1) close(); else { i++; render(); } }
    else if (a === 'skip') close();
    else if (a === 'do') {
      const st = steps[i];
      const el = st.doIt();
      if (el && el.click) el.click();
      if (st.advanceAfterDo) Promise.resolve(el).then(() => setTimeout(() => { if (steps[i] === st) { i = Math.min(steps.length - 1, i + 1); render(); } }, 1500));
    }
  });

  // Keep the highlight on the target and auto-advance when the visitor completes the action.
  let lastKey = '';
  setInterval(() => {
    if (!open) return;
    const s = steps[i];
    const st = state();

    // Visitor hit Reset (or state otherwise regressed): step back to where it makes sense.
    if (s.needs === 'started' && !st.started) { i = stepFor(st.hubs ? 'start' : 'hubs'); render(); return; }
    if (s.needs === 'hubs' && !st.hubs) { i = stepFor('hubs'); render(); return; }

    if (s.done && s.done(st)) { i = Math.min(steps.length - 1, i + 1); render(); return; }

    const key = i + '|' + (s.hint ? s.hint(st) : '');
    if (key !== lastKey) { lastKey = key; render(); }

    const el = s.target ? s.target() : null;
    if (!el) { ring.style.display = 'none'; return; }
    if (el !== lastScrolled) {
      lastScrolled = el;
      try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (_) { /* ignore */ }
    }
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) { ring.style.display = 'none'; return; }
    Object.assign(ring.style, {
      display: 'block',
      left: r.left - 6 + 'px', top: r.top - 6 + 'px',
      width: r.width + 12 + 'px', height: r.height + 12 + 'px',
    });
  }, 300);

  let seen = false;
  try { seen = localStorage.getItem(STORE) === '1'; } catch (_) { /* ignore */ }
  open = !seen;
  render();
}

if (import.meta.env.VITE_DEMO_MODE === 'true') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
}
