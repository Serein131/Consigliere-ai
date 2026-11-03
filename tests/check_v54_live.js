// v5.4 headless browser regression. No real audio, model keys or network.
// Verifies authorization, automatic audit triggering, cancellation and session bounds.
const fs=require('fs'),vm=require('vm'),assert=require('assert').strict;
const page=fs.readFileSync('app.py','utf8');
const js=page.match(/<script>([\s\S]*?)<\/script>/);
assert(js,'inline JS exists');
const ids=[...page.matchAll(/\bid="([^"]+)"/g)].map(x=>x[1]);
assert.equal(new Set(ids).size,ids.length,'each DOM id unique');
for(const id of ['live_assist_panel','live_consent','live_mode','live_toggle','live_state','live_alerts'])
  assert(ids.includes(id),'v5.4 DOM id '+id);
class El{
  constructor(id=''){this.id=id;this.value='';this.checked=false;this.disabled=false;
    this.style={};this.className='';this.textContent='';this.innerText='';this.innerHTML='';
    this.children=[];this.options=[{text:''},{text:''},{text:''}];this.attrs={};this.listeners={};
    this.classList={toggle:(k,yes)=>{const s=new Set(this.className.split(/\s+/).filter(Boolean));
      if(yes===true)s.add(k);else if(yes===false)s.delete(k);else s.has(k)?s.delete(k):s.add(k);
      this.className=[...s].join(' ');},add:(k)=>{this.className+=' '+k;},
      remove:(k)=>{this.className=this.className.replace(k,'');}};
  }
  replaceChildren(...v){this.children=v;}append(...v){this.children.push(...v);}
  appendChild(v){this.children.push(v);}
  setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}
  getAttribute(k){return this.attrs[k];}
  addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
  fire(k){for(const cb of this.listeners[k]||[])cb({target:this});}
  scrollIntoView(){}focus(){}
}
const el={};for(const id of ids)el[id]=new El(id);
Object.assign(el.dg_role,{value:'seller'});
el.dg_discount.value='10';el.dg_pay_dir.value='maximum';el.dg_pay_days.value='45';
el.dg_no_exclusive.checked=true;el.voice_lang.value='en-US';el.live_mode.value='rules';
const events={};const document={hidden:false,
  getElementById:id=>{if(!el[id])throw Error('Missing id '+id);return el[id];},
  createElement:tag=>new El(tag),
  addEventListener:(k,cb)=>{(events[k]??=[]).push(cb)}};
const windowEvents={};let domLoaded,recognition;
let speechStarts=0,speechStops=0;
class SpeechRecognition{
  constructor(){recognition=this;this.lang='';}
  start(){speechStarts++}stop(){speechStops++}
}
const timers=new Map();let clock=0;
function fakeTimeout(cb,delay){timers.set(++clock,{cb,delay});return clock;}
function fakeClear(id){timers.delete(id);}
let requests=[];
const ctx=vm.createContext({
  window:{SpeechRecognition,addEventListener:(k,cb)=>{
    if(k==='DOMContentLoaded')domLoaded=cb;
    (windowEvents[k]??=[]).push(cb);}},
  document,navigator:{language:'en-US',clipboard:{writeText:async()=>{}}},
  alert:()=>{},console:{log:()=>{}},setTimeout:fakeTimeout,clearTimeout:fakeClear,
  AbortController,
  fetch:async(url,opts)=>{
    const body=JSON.parse(opts.body);
    requests.push({url,body,signal:opts.signal});
    const audit={assessment:'VIOLATION',configured_checks:3,violation_count:3,
      findings:[{rule:'maximum_discount_pct',status:'VIOLATION',observed:15,
        limit:10,evidence:'15% discount'},
        {rule:'payment_days',status:'VIOLATION',observed:90,limit:45,
          evidence:'payment terms 90 days'},
        {rule:'no_exclusivity',status:'VIOLATION',evidence:'exclusivity'}],
      commercial_risks:[],rule_warnings:[]};
    if(url==='/audit')return {ok:true,status:200,json:async()=>audit};
    if(url==='/hybrid-audit')return {ok:true,status:200,
      json:async()=>({mode:'hybrid',audit,extraction:{terms:[]}})};
    throw Error('Unexpected endpoint '+url);
  }
});
vm.runInContext(js[1],ctx,{filename:'v54-inline',timeout:3000});
function run(s){return vm.runInContext(s,ctx,{timeout:3000});}
async function flush(){
  const values=[...timers.values()];timers.clear();
  for(const entry of values)entry.cb();
  for(let i=0;i<10;i++)await Promise.resolve();
}
async function test(){
  domLoaded();run("setPhase('in_deal')");
  el.input_text.value='Buyer proposes 15% discount and payment terms 90 days with exclusivity.';
  el.input_text.fire('input');
  await flush();assert.equal(requests.length,0,'opt-in default: no automatic requests');
  run('toggleLiveAssist()');
  await flush();assert.equal(requests.length,0,'missing consent blocks start');
  el.live_consent.checked=true;
  run('toggleLiveAssist()');await flush();
  assert.equal(requests.length,1,'start + existing text should auto-audit');
  assert.equal(requests[0].url,'/audit','default mode must be no-Gemini');
  assert.equal(requests[0].body.structured_rules.discount_max_pct,10);
  assert.equal(el.live_alerts.style.display,'block');
  assert(el.live_alerts.className.includes('risk'),'violations appear as risk');
  assert(el.live_alerts.children.length>=4,'citations and all conflicts shown');
  assert(!requests[0].body.consent_to_model_processing);
  // A new edit schedules a check but stopping cancels it.
  el.input_text.value+=' Another term.';el.input_text.fire('input');
  assert(timers.size>0,'scheduled check exists');
  run('toggleLiveAssist()');await flush();
  assert.equal(requests.length,1,'stop cancels queued check');
  assert.equal(el.live_alerts.style.display,'none','stop hides stale alerts');
  // The hybrid mode is never activated by an accidental switch or prior microphone consent.
  el.live_mode.value='hybrid';el.live_mode.fire('change');
  run('toggleLiveAssist()');await flush();
  assert.equal(requests.length,1,'AI separate consent required');
  el.dg_consent.checked=true;
  run('toggleLiveAssist()');await flush();
  assert.equal(requests.length,2);
  assert.equal(requests[1].url,'/hybrid-audit');
  assert.equal(requests[1].body.consent_to_model_processing,true);
  el.dg_consent.checked=false;el.dg_consent.fire('change');
  assert.equal(run('liveAssist.active'),false,'revocation stops live model mode');
  // Revert to rules; partial speech transcription must never transmit.
  el.live_mode.value='rules';el.live_mode.fire('change');
  el.mic_consent.checked=true;
  run('toggleMic()');assert.equal(speechStarts,1);
  run('toggleLiveAssist()');await flush();
  const baseline=requests.length;
  recognition.onresult({results:[{0:{transcript:'proposed 14% discount'},
    isFinal:false}]});
  await flush();assert.equal(requests.length,baseline,'interim speech is not transmitted');
  recognition.onresult({results:[{0:{transcript:'proposed 14% discount'},
    isFinal:true}]});
  await flush();
  assert.equal(requests.length,baseline+1,'finalized speech auto-audited');
  assert(requests.at(-1).body.text.includes('14% discount'));
  run('toggleMic()');const before=requests.length;
  await flush();assert.equal(requests.length,before,'stop mic is not a trigger');
  // No background or cross-stage requests; stop/clear are immediate.
  run("setPhase('post_deal')");assert.equal(run('liveAssist.active'),false);
  el.input_text.value='something';el.input_text.fire('input');await flush();
  assert.equal(requests.length,before,'post-deal is not a monitoring surface');
  run("setPhase('in_deal')");run('toggleLiveAssist()');
  document.hidden=true;
  (events.visibilitychange||[]).forEach(cb=>cb());
  await flush();assert.equal(run('liveAssist.active'),false);
  assert.equal(requests.length,before,'page hidden cancels pending checks');
  document.hidden=false;
  run('toggleLiveAssist()');
  (windowEvents.pagehide||[]).forEach(cb=>cb());
  await flush();assert.equal(requests.length,before,'pagehide cancels pending checks');
  console.log('V54_LIVE_PASS: explicit consent, auto rules, gated Gemini, final speech only, stop/background/stage cancellation');
}
test().catch(e=>{console.error(e.stack||e);process.exit(1)});
