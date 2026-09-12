// Application logic integration tests, not a browser/layout test.
// Runs the real JS and Python HTTP server with minimal DOM/canvas stand-ins.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { spawn } = require('node:child_process');
const { once } = require('node:events');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'pixellink/static/index.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'pixellink/static/app.js'), 'utf8');
let child, base;

before(async () => {
  const localPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const python = process.env.PIXELLINK_PYTHON || (fs.existsSync(localPython) ? localPython : 'python3');
  child = spawn(python, ['-m', 'pixellink', 'simulate', '--port', '0'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  base = await new Promise((resolve, reject) => {
    let out = '', err = '';
    const timer = setTimeout(() => reject(new Error('Server did not start: ' + err)), 10000);
    child.stderr.on('data', data => { err += data; });
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('exit', code => { clearTimeout(timer); reject(new Error(`Server exited ${code}: ${err}`)); });
    child.stdout.on('data', data => {
      out += data;
      const match = out.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (match) { clearTimeout(timer); resolve(match[0]); }
    });
  });
});
after(async () => {
  if (child && child.exitCode === null) {
    const stopped = once(child, 'exit');
    child.kill('SIGTERM');
    await stopped;
  }
});

function element() {
  return {
    width: 600, height: 180, value: '', files: [], disabled: false, hidden: false,
    style: {}, children: [], firstChild: { textContent: '' }, textContent: '',
    parentElement: { setAttribute() {} }, listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
    replaceChildren() { this.children = []; },
    appendChild(child) { this.children.push(child); },
    getContext() {
      if (!this.context) this.context = {
        rows: new Map(), fillRect() {}, clearRect() {}, beginPath() {},
        moveTo() {}, lineTo() {}, stroke() {},
        createImageData(w, h) { return { data: new Uint8ClampedArray(w * h * 4) }; },
        putImageData(image, x, y) { this.rows.set(y, Array.from(image.data)); },
      };
      return this.context;
    },
  };
}

async function app() {
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], element()]));
  for (const id of ['snr', 'seed', 'retries']) {
    const tag = html.match(new RegExp('<input[^>]*id="' + id + '"[^>]*>'))[0];
    elements.get(id).value = tag.match(/\bvalue="([^"]*)"/)[1];
  }
  const sandbox = vm.createContext({
    document: {
      getElementById(id) { assert.ok(elements.has(id), 'Unknown DOM id: ' + id); return elements.get(id); },
      createElement: element,
    },
    fetch: (route, options) => fetch(base + route, options),
    matchMedia: () => ({ matches: true }),
    setTimeout, atob: value => Buffer.from(value, 'base64').toString('binary'),
    FileReader: class {
      readAsDataURL(file) { this.result = 'data:image/png;base64,' + file.bytes.toString('base64'); this.onload(); }
    },
  });
  vm.runInContext(source, sandbox, { filename: 'app.js' });
  const deadline = Date.now() + 10000;
  while (elements.get('send').disabled && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.equal(elements.get('send').disabled, false, elements.get('status').textContent);
  return { elements, sandbox, run: code => vm.runInContext(code, sandbox) };
}

test('real demo paints verified rows and clean retry reconstructs all rows', async () => {
  const { elements: e, run } = await app();
  e.get('snr').value = '0';
  await run('transmit(false)');
  const initial = run('JSON.parse(JSON.stringify(latest))');
  assert.ok(initial.received > 0 && initial.missing > 0);
  assert.equal(e.get('packets').children.length, initial.total);
  assert.equal(e.get('rx').context.rows.size, initial.received);
  assert.equal(e.get('retry').disabled, false);
  assert.equal(e.get('send').disabled, false);
  assert.equal(e.get('download').href, initial.rx);
  for (const event of initial.events.filter(event => event.ok)) {
    const expected = [...Buffer.from(event.row, 'base64')].flatMap(v => [v, v, v, 255]);
    assert.deepEqual(e.get('rx').context.rows.get(event.seq), expected);
  }
  e.get('snr').value = '20';
  await run('transmit(true)');
  assert.equal(run('latest.exact'), true);
  assert.equal(e.get('rx').context.rows.size, initial.total);
  assert.equal(e.get('integrity').textContent, 'Exact match');
  assert.equal(e.get('retry').disabled, true);
  assert.ok(e.get('packets').children.every(packet => packet.className === 'packet good'));
});

test('uploaded PNG is read and sent through the same real signal path', async () => {
  const { elements: e, run } = await app();
  e.get('snr').value = '20';
  await run('transmit(false)');
  const bytes = Buffer.from(run('latest.tx').split(',')[1], 'base64');
  e.get('image').files = [{ name: 'roundtrip.png', size: bytes.length, bytes }];
  await run('transmit(false)');
  assert.equal(run('latest.exact'), true);
  assert.equal(e.get('download').hidden, false);
  assert.equal(e.get('tx').hidden, false);
});

test('invalid input and expired sessions show errors and release controls', async () => {
  const { elements: e, run } = await app();
  e.get('seed').value = '-1';
  await run('transmit(false)');
  assert.match(e.get('status').textContent, /Seed must be an integer/);
  assert.equal(e.get('send').disabled, false);
  e.get('seed').value = '7';
  run("session = 'expired'");
  await run('transmit(true)');
  assert.match(e.get('status').textContent, /Session expired/);
  assert.equal(e.get('send').disabled, false);
  assert.equal(e.get('retry').disabled, true);
});

test('a lost retry response is reconciled from authoritative receiver state', async () => {
  const { elements: e, sandbox, run } = await app();
  e.get('snr').value = '0';
  await run('transmit(false)');
  const originalCount = run('latest.received');
  const total = run('latest.total');
  assert.ok(originalCount < total);
  const workingFetch = sandbox.fetch;
  sandbox.fetch = async (route, options) => {
    const response = await workingFetch(route, options);
    await response.arrayBuffer(); // The server committed the successful retry.
    throw new Error('Simulated response lost after server processing');
  };
  e.get('snr').value = '20';
  await run('transmit(true)');
  assert.match(e.get('status').textContent, /response lost/);
  assert.equal(run('latest.received'), originalCount);
  sandbox.fetch = workingFetch;
  await run('transmit(true)');
  assert.equal(run('latest.events.length'), 0);
  assert.equal(run('latest.exact'), true);
  assert.equal(e.get('rx').context.rows.size, total);
  assert.ok(e.get('packets').children.every(packet => packet.className === 'packet good'));
  assert.equal(e.get('integrity').textContent, 'Exact match');
});
