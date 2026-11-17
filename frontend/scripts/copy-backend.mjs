// Copies the real backend sources next to bridge.py so the in-browser demo runs the same code.
import { copyFileSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, '..', 'public', 'py');
mkdirSync(out, { recursive: true });
const src = path.join(here, '..', '..', 'backend');
if (!existsSync(src)) { console.log('backend/ not found; using committed copies in public/py'); process.exit(0); }
for (const f of ['main.py', 'route_assignment_algorithm.py'])
  copyFileSync(path.join(src, f), path.join(out, f));
copyFileSync(path.join(here, '..', '..', 'sample_data', 'trucks.csv'), path.join(here, '..', 'public', 'sample-trucks.csv'));
console.log('Copied backend sources to public/py');
