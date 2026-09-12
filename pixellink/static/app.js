'use strict';
const $ = id => document.getElementById(id);
let token = '', session = null, latest = null, busy = false;
const ctx = $('rx').getContext('2d');
function checker(w, h) {
  $('rx').width = w; $('rx').height = h;
  for (let y = 0; y < h; y += 8) for (let x = 0; x < w; x += 8) {
    ctx.fillStyle = ((x / 8 + y / 8) % 2) ? '#2a2a2a' : '#373737';
    ctx.fillRect(x, y, 8, 8);
  }
}
function plot(id, series, lo, hi) {
  const canvas = $(id), c = canvas.getContext('2d'), w = canvas.width, h = canvas.height;
  c.clearRect(0, 0, w, h); c.strokeStyle = '#2b373c'; c.lineWidth = 1;
  for (let i = 1; i < 6; i++) { c.beginPath(); c.moveTo(0, h*i/6); c.lineTo(w, h*i/6); c.stroke(); }
  for (let i = 1; i < 8; i++) { c.beginPath(); c.moveTo(w*i/8, 0); c.lineTo(w*i/8, h); c.stroke(); }
  series.forEach((values, index) => {
    c.strokeStyle = index ? '#79cbdc' : '#b7f58c'; c.lineWidth = 1.6; c.beginPath();
    values.forEach((v, i) => { const x = i*w/(values.length-1), y = h-(v-lo)*h/(hi-lo); if (i) c.lineTo(x,y); else c.moveTo(x,y); }); c.stroke();
  });
}
function lock(value) {
  busy = value;
  ['send','demo','image','seed','retries','snr'].forEach(id => $(id).disabled = value);
  $('retry').disabled = value || !latest || !latest.missing;
  $('send').firstChild.textContent = value ? 'Processing signal… ' : 'Transmit image ';
}
function progress(n, total) {
  $('verified').textContent = `${n} / ${total}`;
  $('progress').style.width = `${100*n/total}%`;
  $('progress').parentElement.setAttribute('aria-valuenow', String(Math.round(100*n/total)));
}
function ledger(total) {
  $('packets').replaceChildren();
  for (let i=0; i<total; i++) { const p=document.createElement('span'); p.className='packet'; p.title=`Row ${i}: unsent`; $('packets').appendChild(p); }
}
function mark(seq, ok, attempts) {
  const p = $('packets').children[seq];
  p.className = `packet ${ok ? 'good' : 'bad'}`;
  p.title = `Row ${seq}: ${ok ? 'CRC verified' : 'missing'} · ${attempts} attempt(s)`;
}
async function render(result, retry) {
  $('tx').src = result.tx; $('tx').hidden = false; $('txEmpty').hidden = true;
  $('geometry').textContent = `${result.width} × ${result.height} / L8`;
  $('transferId').textContent = result.identity.toUpperCase();
  $('download').hidden = true;
  const accepted = new Set(retry && latest ? latest.accepted : []);
  if (!retry) { checker(result.width,result.height); ledger(result.total); }
  $('status').textContent = 'Simulation finished. Playing verified packet events…';
  const delay = matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : Math.min(12, 1400/Math.max(result.events.length,1));
  for (let i=0; i<result.events.length; i++) {
    const e=result.events[i]; mark(e.seq,e.ok,e.attempt);
    if (e.ok) {
      accepted.add(e.seq); const row=atob(e.row), pixels=ctx.createImageData(result.width,1);
      for(let x=0;x<row.length;x++) { const v=row.charCodeAt(x); pixels.data.set([v,v,v,255],x*4); }
      ctx.putImageData(pixels,0,e.seq);
    }
    progress(accepted.size,result.total);
    if (delay && i%4===0) await new Promise(resolve=>setTimeout(resolve,delay*4));
  }
  // Canonical snapshot reconciliation also repairs a previously lost HTTP response.
  checker(result.width,result.height); ledger(result.total);
  const finalAccepted = new Set(result.accepted);
  result.attempts.forEach((attempts, seq) => { if (attempts) mark(seq, finalAccepted.has(seq), attempts); });
  Object.entries(result.rows).forEach(([seq, encoded]) => {
    const row = atob(encoded), pixels = ctx.createImageData(result.width,1);
    for (let x=0; x<row.length; x++) { const v=row.charCodeAt(x); pixels.data.set([v,v,v,255],x*4); }
    ctx.putImageData(pixels,0,Number(seq));
  });
  progress(result.received,result.total);
  $('ber').textContent = `${(result.ber*100).toFixed(3)}%`;
  $('loss').textContent = `${result.failed} / ${result.sent}`;
  $('integrity').textContent = result.exact ? 'Exact match' : 'Incomplete';
  $('integrity').style.color = result.exact ? '#b7f58c' : '#f89e8d';
  $('rxLabel').textContent = result.exact ? 'PIXELS VERIFIED' : `${result.missing} ROWS MISSING`;
  $('status').textContent = result.exact ? 'Every received pixel matches the normalized source.' : `${result.missing} rows missing. Raise SNR or retry to recover them.`;
  $('summary').textContent = `${result.bitErrors.toLocaleString()} / ${result.bits.toLocaleString()} bit errors · ${(result.packetErrorRate*100).toFixed(1)}% rejected attempts · ${result.rounds} rounds · ${result.signalSeconds.toFixed(2)} s simulated signal time (no gaps or ACK airtime).`;
  $('download').href = result.rx; $('download').hidden = false;
  if(result.trace) { const t=result.trace, limit=Math.max(1,...t.i.map(Math.abs),...t.q.map(Math.abs)); plot('wave',[t.i,t.q],-limit,limit); plot('spectrum',[t.spectrum],-80,10); }
  session=result.session; latest=result;
}
function readUpload(file) {
  return new Promise((resolve,reject)=>{ const r=new FileReader(); r.onload=()=>resolve(String(r.result).split(',')[1]); r.onerror=()=>reject(new Error('Could not read image')); r.readAsDataURL(file); });
}
async function transmit(retry) {
  if(busy) return;
  try {
    const seed=Number($('seed').value), retries=Number($('retries').value);
    if(!Number.isInteger(seed)||seed<0||seed>4294967295||!Number.isInteger(retries)||retries<0||retries>8) throw new Error('Seed must be an integer 0–4294967295; retries 0–8.');
    const file=$('image').files[0]; if(!retry && file && file.size>4*1024*1024) throw new Error('Choose an image no larger than 4 MiB.');
    lock(true); $('status').textContent='Modulating packets, adding noise, and checking received CRCs…';
    const body={snr:Number($('snr').value),seed,retries};
    if(retry) body.session=session; else if(file) body.image=await readUpload(file);
    const response=await fetch(retry?'/api/retry':'/api/transfer',{method:'POST',headers:{'Content-Type':'application/json','X-PixelLink-Token':token},body:JSON.stringify(body)});
    const result=await response.json(); if(!response.ok) throw new Error(result.error || 'Request failed');
    await render(result,retry);
  } catch(error) { $('status').textContent=error.message; }
  finally { lock(false); }
}
$('snr').addEventListener('input',()=> $('snrValue').textContent=`${$('snr').value} dB`);
$('image').addEventListener('change',()=> $('filename').textContent=$('image').files[0]?.name || 'Choose an image');
$('demo').addEventListener('click',()=>{ $('image').value=''; $('filename').textContent='Built-in landscape selected'; });
$('send').addEventListener('click',()=>transmit(false)); $('retry').addEventListener('click',()=>transmit(true));
checker(160,120); plot('wave',[],-1,1); plot('spectrum',[],-80,10);
$('send').disabled=true;
fetch('/api/config').then(r=>{if(!r.ok)throw new Error('Server unavailable');return r.json();}).then(c=>{token=c.token;$('send').disabled=false;}).catch(e=>{$('status').textContent=`Cannot connect: ${e.message}. Reload the page after starting the local server.`;});
