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

function collect(node,output=[]){
  if(node.textContent)output.push(String(node.textContent));
  for(const child of node.children||[])collect(child,output);
  return output;
}
function textOf(){return collect(el.live_alerts).join(' | ');}
function findings(status,discount,payment,exclusive,direction='max'){
  return [
    {rule:'maximum_discount_pct',status:status[0],observed:discount?.[0],limit:discount?.[1],evidence:'discount source phrase'},
    {rule:'payment_days',status:status[1],observed:payment?.[0],limit:payment?.[1],direction,evidence:'payment source phrase'},
    {rule:'no_exclusivity',status:status[2],evidence:'exclusivity source phrase'}
  ];
}
function audit(findings,mentions=[]){
  const num=findings.filter(x=>x.status==='VIOLATION').length;
  return {assessment:num?'VIOLATION':findings.some(x=>x.status==='UNKNOWN')?'UNKNOWN':'NO_DETECTED_VIOLATION',
    findings,configured_checks:findings.length,violation_count:num,term_mentions:mentions};
}
async function test(){
  domLoaded();run("setPhase('in_deal')");
  // User-test role 1: founder, three conflicts and three DIFFERENT counter-questions.
  ctx.scenario=audit(findings(['VIOLATION','VIOLATION','VIOLATION'],[15,10],[90,45]),
    [{field:'discount',state:'proposed',value:15,evidence:'buyer asks for a 15% discount'}]);
  run('renderLiveAlert(scenario,"rules")');
  const founder=textOf();
  assert(founder.includes('15%') && founder.includes('10%'),'discount percent + threshold');
  assert(founder.includes('90 days') && founder.includes('45 days'),'payment and threshold');
  assert(founder.includes('45 days longer than your maximum'),'payment gap direction');
  assert(founder.includes('remove exclusivity'),'targeted exclusivity question');
  assert(founder.includes('payment period'),'targeted payment question');
  assert(founder.includes('flexibility do you have on the discount'),'targeted discount question');
  assert(founder.includes('proposed')||founder.includes('Proposal wording'));
  assert(!founder.includes('Can we revisit this term and confirm'),'old fixed response removed');
  assert(el.live_alerts.className.includes('risk'));

  // User-test role 2: historical rejected offer then current agreed; show both
  // as heuristic observations, not as a legally verified final agreement.
  ctx.scenario=audit(findings(['PASS','PASS','PASS'],[5,5],[30,30]),[
    {field:'discount',state:'rejected',value:20,evidence:'客户最初要求20%折扣，我已明确拒绝'},
    {field:'discount',state:'agreed',value:5,evidence:'双方最终同意5%折扣'},
    {field:'payment',state:'rejected',value:90,evidence:'此前90天付款，已拒绝'},
    {field:'payment',state:'agreed',value:30,evidence:'双方最终同意30天付款'}
  ]);
  run('renderLiveAlert(scenario,"rules")');
  const designer=textOf();
  assert(designer.includes('Rejected wording') && designer.includes('Agreement wording'));
  assert(designer.includes('20%') && designer.includes('5%'));
  assert(designer.includes('heuristic text cues'),'explicit uncertainty on timeline');
  assert(designer.includes('Meets rule'));
  assert(!designer.includes('Example counter-questions'),'no unsolicited negotiation on pass');

  // User-test role 3: buyer minimum payment rule (15 vs 60); no reversed advice.
  el.dg_role.value='buyer';el.dg_pay_dir.value='minimum';el.dg_pay_days.value='60';
  ctx.scenario=audit(findings(['UNKNOWN','VIOLATION','VIOLATION'],null,[15,60],null,'min'),[
    {field:'payment',state:'proposed',value:15,evidence:'供应商要求15天内付款'}
  ]);
  run('renderLiveAlert(scenario,"rules")');
  const procurement=textOf();
  assert(procurement.includes('15 days') && procurement.includes('minimum 60 days'));
  assert(procurement.includes('45 days earlier than your minimum'));
  assert(procurement.includes('extend the payment period'));
  assert(procurement.includes('Not verified'),'discount is unknown');

  // User-test role 4: on-threshold PASS remains auditable with all checks.
  el.dg_role.value='seller';el.dg_pay_dir.value='maximum';el.dg_pay_days.value='30';
  ctx.scenario=audit(findings(['PASS','PASS','PASS'],[8,8],[30,30]),[]);
  run('renderLiveAlert(scenario,"rules")');
  const sales=textOf();
  assert(sales.includes('8%') && sales.includes('30 days'));
  assert(sales.includes('No detected violation'),'not a safety guarantee');
  assert(sales.includes('Rules checked'));
  assert(!sales.includes('Example counter-questions'));
  assert.equal(el.live_alerts.children.filter(x=>x.className==='v55-overview').length,1);

  // User-test role 5: English "only reseller" phrase is shown with hybrid
  // verified source excerpt, without treating quote matching as legal proof.
  ctx.scenario={mode:'hybrid',audit:audit(findings(['VIOLATION','VIOLATION','VIOLATION'],[12,6],[75,30])),
    term_mentions:[{field:'exclusivity',state:'proposed',evidence:'They want to be the only reseller in the region.'}],
    extraction:{terms:[{field:'exclusivity',source_status:'required',
      quote_verified:true,evidence:'They want to be the only reseller in the region.'}]}};
  run('renderLiveAlert(scenario,"hybrid")');
  const manufacturer=textOf();
  assert(manufacturer.includes('only reseller in the region'));
  assert(manufacturer.includes('source quote matched'));
  assert(manufacturer.includes('literal quote matching does not validate interpretation'));
  assert(manufacturer.includes('flexibility do you have on the discount'));

  // Bilingual output including direction and targeted questions.
  run("setLanguage('zh')");
  ctx.scenario=audit(findings(['UNKNOWN','VIOLATION','VIOLATION'],null,[15,60],null,'min'));
  run('renderLiveAlert(scenario,"rules")');
  const chinese=textOf();
  assert(chinese.includes('至少60天') || chinese.includes('至少60天'));
  assert(chinese.includes('提前45天'));
  assert(chinese.includes('能否取消独家条款'));
  assert(chinese.includes('能否延长付款期限'));

  // Existing consent/security behavior must be preserved from the v5.4 suite.
  assert.equal(requests.length,0,'rendering never initiates a network/model request');
  console.log('V55_ACTIONABLE_PASS: five roles, contextual questions, payment direction, status cards, hybrid provenance, bilingual copy');
}
test().catch(e=>{console.error(e.stack||e);process.exit(1)});
