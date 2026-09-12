// Hardware dashboard application-logic tests. No browser or physical radio.
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'pixellink/telemetry_static/index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'pixellink/telemetry_static/telemetry.js'), 'utf8');
let child, base;

before(async () => {
  const local = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  child = spawn(process.env.PIXELLINK_PYTHON || (fs.existsSync(local) ? local : 'python3'),
    ['-m', 'pixellink', 'serve', '--port', '0'], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  base = await new Promise((resolve, reject) => {
    let text = '', error = '';
    const timer = setTimeout(() => reject(new Error('Server startup timeout: ' + error)), 10000);
    child.stderr.on('data', x => {error += x;});
    child.on('error', e => {clearTimeout(timer); reject(e);});
    child.on('exit', code => {clearTimeout(timer); reject(new Error(`Server exited ${code}: ${error}`));});
    child.stdout.on('data', chunk => {
      text += chunk;
      const match = text.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (match) {clearTimeout(timer); resolve(match[0]);}
    });
  });
});
after(async () => {
  if (child && child.exitCode === null) {const ended = once(child, 'exit'); child.kill('SIGTERM'); await ended;}
});

function element() {
  return {textContent: '', hidden: false, width: 800, height: 240, children: [],
    classList: {toggle() {}, add() {}},
    replaceChildren(...nodes) {this.children = nodes;},
    append(...nodes) {this.children.push(...nodes);},
    getContext() {return {clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {},
      stroke() {}, fillText() {}, arc() {}, fill() {}};},
  };
}
async function app() {
  const nodes = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(x => [x[1], element()]));
  const context = vm.createContext({
    document: {getElementById(id) {assert.ok(nodes.has(id), id); return nodes.get(id);}, createElement: element},
    fetch: (route, options) => fetch(base + route, options), AbortSignal,
    setTimeout: () => {}, // Do not run a permanent polling loop in tests.
  });
  vm.runInContext(script, context);
  await vm.runInContext('poll()', context);
  return {nodes, context, run: code => vm.runInContext(code, context)};
}

test('default hardware CLI serves an empty, honest live dashboard', async () => {
  const response = await fetch(base + '/api/state');
  const snapshot = await response.json();
  assert.equal(snapshot.mode, 'hardware-live');
  assert.equal(snapshot.latest, null);
  assert.deepEqual(snapshot.history, []);
  const {nodes: n} = await app();
  assert.equal(n.get('usb').textContent, 'Waiting for setup');
  assert.equal(n.get('age').textContent, 'Never');
  assert.equal(n.get('rssi').textContent, '— dBm');
  assert.equal(n.get('setup').hidden, false);
  const page = await (await fetch(base)).text();
  assert.ok(!page.includes('id="snr"'));
  assert.ok(!page.includes('id="send"'));
});

test('render distinguishes received values, disabled ADC, and stale observations', async () => {
  const state = await (await fetch(base + '/api/state')).json();
  const {nodes: n, context, run} = await app();
  state.serial = {connected: true, state: 'connected', port: 'TEST-FIXTURE-NOT-HARDWARE'};
  state.receiver = {role: 'rx', state: 'receiving', frequency_mhz: 433.5};
  state.receiver_age_s = 1;
  state.latest = {node_id: 9, boot_id: 17, sequence: 4, uptime_ms: 4000,
    adc_valid: false, adc_raw: null, lqi: 35, rssi_dbm: -73.5, classification: 'forward'};
  state.last_packet_age_s = 9;
  state.history = [{elapsed_s: 1, rssi_dbm: -73.5}];
  context.fixture = state;
  run('render(fixture)');
  assert.equal(n.get('rssi').textContent, '-73.5 dBm');
  assert.match(n.get('age').textContent, /stale/);
  assert.ok(n.get('frame').children.some(x => x.textContent === 'Not sampled'));
  state.latest.adc_valid = true;
  state.latest.adc_raw = 2048;
  run('render(fixture)');
  assert.ok(n.get('frame').children.some(x => x.textContent === '2048'));
});

test('HTTP loss changes live status to unknown rather than claiming connected', async () => {
  const {nodes: n, context, run} = await app();
  context.fetch = async () => {throw new Error('Test connection failure');};
  await run('poll()');
  assert.match(n.get('connection').textContent, /Dashboard disconnected/);
  assert.match(n.get('usb').textContent, /Unknown/);
  assert.match(n.get('receiver').textContent, /Unknown/);
  assert.match(n.get('age').textContent, /Unknown/);
});
