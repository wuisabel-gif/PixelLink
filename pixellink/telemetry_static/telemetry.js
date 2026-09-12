'use strict';
const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value; };
function table(id, pairs) {
  const nodes = [];
  for (const [key, value] of pairs) {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = key; dd.textContent = value == null ? '—' : String(value);
    nodes.push(dt, dd);
  }
  $(id).replaceChildren(...nodes);
}
function chart(history) {
  const canvas = $('chart'), c = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height, left = 48, top = 16, bottom = h - 28;
  c.clearRect(0, 0, w, h); c.font = '12px monospace';
  for (const dbm of [-140, -100, -60, -20, 20]) {
    const y = bottom - (dbm + 140) / 160 * (bottom - top);
    c.strokeStyle = '#2b3c45'; c.beginPath(); c.moveTo(left,y); c.lineTo(w,y); c.stroke();
    c.fillStyle = '#a2b4bd'; c.fillText(String(dbm), 0, y + 4);
  }
  if (!history.length) {c.fillStyle = '#a2b4bd'; c.fillText('Waiting for real packets — no generated trace', left + 12, h / 2); return;}
  c.strokeStyle = '#78e1bf'; c.lineWidth = 2; c.beginPath();
  history.forEach((point, i) => {
    const x = left + i / Math.max(1, history.length - 1) * (w-left-8);
    const y = bottom - (point.rssi_dbm + 140) / 160 * (bottom-top);
    if (i) c.lineTo(x,y); else c.moveTo(x,y);
  }); c.stroke();
  if (history.length === 1) { const y = bottom - (history[0].rssi_dbm+140)/160*(bottom-top); c.fillStyle='#78e1bf'; c.beginPath(); c.arc(left,y,4,0,Math.PI*2); c.fill(); }
  c.fillStyle='#a2b4bd'; c.fillText('Older observations → latest',left,bottom+22);
}
function render(s) {
  const connected = s.serial.connected;
  text('usb', connected ? 'Connected' : s.serial.state === 'waiting' ? 'Waiting for setup' : 'Disconnected');
  text('port', s.serial.port || 'No explicit serial port selected');
  const receiver = s.receiver;
  text('receiver', receiver ? receiver.state : 'Unknown');
  text('radio-detail', receiver ? `${receiver.role.toUpperCase()} · ${receiver.frequency_mhz || 'unset'} MHz · status ${s.receiver_age_s.toFixed(1)}s ago` : 'Awaiting firmware status; USB is not proof of radio readiness');
  const age = s.last_packet_age_s;
  text('age', age == null ? 'Never' : `${age.toFixed(1)}s ago${age > 5 ? ' · stale' : ''}`);
  text('tx-detail', s.latest ? `Node ${s.latest.node_id} · boot ${s.latest.boot_id}` : 'No validated RF frames received');
  $('setup').hidden = connected && receiver && receiver.state !== 'unconfigured';
  text('connection', s.serial.error || (!connected ? 'Waiting / disconnected. No hardware samples are being generated.' : !receiver ? 'USB connected. Waiting for receiver firmware status.' : receiver.state === 'unconfigured' ? 'Receiver is unconfigured. Set frequency explicitly using a serial monitor; this host does not configure radios.' : 'Read-only hardware stream. Receiver status and transmitter observations are tracked independently.'));
  $('connection').classList.toggle('error', Boolean(s.serial.error));
  text('rssi', s.latest ? `${s.latest.rssi_dbm.toFixed(1)} dBm` : '— dBm');
  const f = s.latest;
  table('frame', f ? [['Node / boot', `${f.node_id} / ${f.boot_id}`], ['Sequence', f.sequence], ['TX uptime', `${f.uptime_ms} ms`], ['ADC raw', f.adc_valid ? f.adc_raw : 'Not sampled'], ['LQI (raw)', f.lqi], ['Observation', f.classification]] : [['Frame', 'Awaiting hardware']]);
  const counts = Object.entries(s.counts).map(([key,value]) => {const node=document.createElement('div');node.className='count';const strong=document.createElement('strong'),span=document.createElement('span');strong.textContent=value;span.textContent=key.replaceAll('_',' ');node.append(strong,span);return node;});
  $('counts').replaceChildren(...counts); text('gap-note',s.gap_note);
  table('diagnostics', [['Host uptime',`${s.host_uptime_s.toFixed(1)} s`],['Serial error',s.serial.error || 'None'],['Receiver error',s.serial.receiver_error ? `${s.serial.receiver_error.code}: ${s.serial.receiver_error.message}` : 'None'],['Logging',s.log.state],['Original USB bytes logged',s.log.bytes],['Log error',s.log.error || 'None'],['Tracked node/boot sessions',s.sessions_tracked]]);
  chart(s.history);
}
async function poll() {
  try {const response=await fetch('/api/state',{cache:'no-store',signal:AbortSignal.timeout(4000)}); if(!response.ok)throw new Error(`HTTP ${response.status}`);render(await response.json());}
  catch(error){text('connection',`Dashboard disconnected: ${error.message}. Displayed observations may be stale.`);$('connection').classList.add('error');text('usb','Unknown · dashboard offline');text('receiver','Unknown · dashboard offline');text('age','Unknown · dashboard offline');}
  finally {setTimeout(poll,1000);}
}
poll();
