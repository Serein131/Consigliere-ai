// Behavioral regression for the inline v5.3 browser UI. Runs entirely offline.
const fs=require('fs');
const vm=require('vm');
const assert=require('assert').strict;
const page=fs.readFileSync('app.py','utf8');
const match=page.match(/<script>([\s\S]*?)<\/script>/);
assert(match,'inline browser script must exist');
const ids=Array.from(page.matchAll(/\bid="([^"]+)"/g),m=>m[1]);
assert.equal(new Set(ids).size,ids.length,'DOM ids must be unique');
assert.equal((page.match(/<textarea\b/g)||[]).length,1,'only one shared stage editor');
assert(ids.includes('input_text')&&!ids.includes('dg_proposal'),'old duplicate proposal textarea removed');
assert(ids.includes('stage_prepare')&&ids.includes('stage_live_audit'),'three stage UI panels exist');
assert(!page.includes('4500);'),'no timed silence-triggered AI calls');
const elements={};
class Element{
  constructor(id=''){
    this.id=id;this.value='';this.checked=false;this.disabled=false;this.style={};
    this.className='';this.textContent='';this.innerText='';this.innerHTML='';
    this.options=[{text:''},{text:''},{text:''}];this.listeners={};this.children=[];
    this._attrs={};
    this.classList={
      toggle:(key,on)=>{const tokens=new Set(this.className.split(/\s+/).filter(Boolean));
        if(on===true)tokens.add(key);else if(on===false)tokens.delete(key);
        else tokens.has(key)?tokens.delete(key):tokens.add(key);
        this.className=[...tokens].join(' ');},
      add:(key)=>{this.className+=' '+key;},
      remove:(key)=>{this.className=this.className.replace(key,'');}
    };
  }
  setAttribute(k,v){this._attrs[k]=v;}
  removeAttribute(k){delete this._attrs[k];}
  getAttribute(k){return this._attrs[k];}
  addEventListener(k,cb){(this.listeners[k]??=[]).push(cb);}
  fire(k){for(const f of this.listeners[k]||[])f({target:this});}
  replaceChildren(...items){this.children=items;}
  append(...items){this.children.push(...items);}
  appendChild(x){this.children.push(x);}
  focus(){}
  scrollIntoView(){}
}
for(const id of ids)elements[id]=new Element(id);
const doc={
  getElementById:id=>{if(!elements[id])throw Error('Missing DOM id: '+id);return elements[id];},
  createElement:tag=>new Element(tag)
};
const defaults={
 dg_role:'seller',dg_discount:'10',dg_pay_dir:'maximum',dg_pay_days:'45',
 voice_lang:'en-US',user_goal:'Original owner text',
 hard_bottom_line:'Owner notes',risk_preference:'Owner preferences'
};
for(const [id,value] of Object.entries(defaults))elements[id].value=value;
elements.dg_no_exclusive.checked=true;
const network=[];
let recognitionStarted=0,recognitionStopped=0,mostRecentRecognition=null;
class FakeSpeechRecognition{
  constructor(){mostRecentRecognition=this;this.continuous=false;this.interimResults=false;}
  start(){recognitionStarted+=1;}
  stop(){recognitionStopped+=1;}
}
let domLoaded=null;
const ctx=vm.createContext({
  window:{SpeechRecognition:FakeSpeechRecognition,
          addEventListener:(name,cb)=>{if(name==='DOMContentLoaded')domLoaded=cb;}},
  document:doc,
  navigator:{language:'en-US',clipboard:{writeText:async()=>{}}},
  alert:()=>{throw Error('Unexpected alert')},
  console:{log:()=>{}},
  setTimeout,clearTimeout,AbortController,
  fetch:async(url,opts)=>{
    network.push({url,request:JSON.parse(opts.body)});
    if(url==='/audit')return {ok:true,status:200,json:async()=>({
      assessment:'VIOLATION',configured_checks:3,violation_count:3,
      findings:[{rule:'maximum_discount_pct',status:'VIOLATION',observed:15,limit:10}],
      commercial_risks:[],rule_warnings:[]
    })};
    if(url==='/hybrid-audit')return {ok:true,status:200,json:async()=>({
      mode:'hybrid',model_used:'fictional-test',elapsed_ms:5,
      audit:{assessment:'VIOLATION',configured_checks:3,violation_count:3,
        findings:[{rule:'maximum_discount_pct',status:'VIOLATION',observed:15,limit:10}],
        commercial_risks:[],rule_warnings:[]},
      extraction:{terms:[{field:'discount',source_status:'proposed',
        value:15,evidence:'15% discount',quote_verified:true}]}
    })};
    if(url==='/analyze')return {ok:true,status:200,text:async()=>JSON.stringify({
      tactical_advice:{
        trap_or_intent:'Fictional mock',triggered_rule:'10% discount',
        risk_level:'MEDIUM',counter_question:'Can we revisit the terms?',
        draft_reply:'Thank you for the discussion.',box1_text:'Evidence',
        box2_text:'Inference',box3_text:'Unknowns'
      },measured_latency_ms:4,model_used:'mock',
      sanitized_payload_sent_to_llm:'fictional text',
      dealguard_audit:{assessment:'UNKNOWN',findings:[],commercial_risks:[]}
    })};
    throw Error('Unknown mock endpoint: '+url);
  }
});
vm.runInContext(match[1],ctx,{timeout:2000,filename:'consigliere-v53-inline.js'});
function run(code){return vm.runInContext(code,ctx,{timeout:2000});}
async function main(){
  assert(domLoaded,'DOMContentLoaded handler must be registered');
  domLoaded();
  assert.equal(elements.stage_prepare.style.display,'block');
  assert.equal(elements.stage_live_audit.style.display,'none');
  assert.equal(elements.tab_pre_deal.getAttribute('aria-current'),'step');
  // Author-controlled context is retained, never overwritten by translation.
  elements.user_goal.value='My custom objective';
  elements.input_text.value='Preparation draft is unique';
  elements.input_text.fire('input');
  run("setPhase('in_deal')");
  assert.equal(elements.input_text.value,'');
  assert.equal(elements.stage_prepare.style.display,'none');
  assert.equal(elements.stage_live_audit.style.display,'block');
  assert.equal(elements.tab_in_deal.getAttribute('aria-current'),'step');
  elements.input_text.value='Our live deal quote';
  elements.input_text.fire('input');
  run("setPhase('post_deal')");
  elements.input_text.value='Our distinct debrief memo';
  elements.input_text.fire('input');
  run("setPhase('pre_deal')");
  assert.equal(elements.input_text.value,'Preparation draft is unique');
  run("setPhase('in_deal')");
  assert.equal(elements.input_text.value,'Our live deal quote');
  run("setPhase('post_deal')");
  assert.equal(elements.input_text.value,'Our distinct debrief memo');
  run("setLanguage('zh')");
  assert.equal(elements.input_text.value,'Our distinct debrief memo');
  assert.equal(elements.user_goal.value,'My custom objective');
  run("setLanguage('en')");
  // Loading fictional examples is not a model request, and stays in the same editor.
  run("loadDealGuardDemo('violation')");
  assert.equal(elements.stage_live_audit.style.display,'block');
  assert(elements.input_text.value.includes('15% discount'));
  assert.equal(network.length,0);
  // Microphone must respect consent and never infer "stop" as analyze.
  run("toggleMic()");
  assert.equal(recognitionStarted,0);
  assert.equal(network.length,0);
  elements.mic_consent.checked=true;
  run("toggleMic()");
  assert.equal(recognitionStarted,1);
  assert(mostRecentRecognition.onresult,'speech result listener registered');
  const previous=elements.input_text.value;
  mostRecentRecognition.onresult({results:[[{transcript:' Another fictional phrase.'}]]});
  assert(elements.input_text.value.startsWith(previous));
  assert(elements.input_text.value.includes('Another fictional phrase'));
  assert.equal(network.length,0);
  run("toggleMic()");
  assert.equal(recognitionStopped,1);
  assert.equal(network.length,0);
  // Another recording automatically stops on a stage transition. It cannot call AI.
  run("toggleMic()");
  run("setPhase('post_deal')");
  assert.equal(recognitionStopped,2);
  assert.equal(network.length,0);
  run("setPhase('in_deal')");
  // Strategy AI and Gemini audit require two separate, explicit consents.
  await run("runAgent()");
  assert.equal(network.length,0,'strategy must not run without consent');
  await run("runHybridAudit()");
  assert.equal(network.length,0,'hybrid must not run without consent');
  await run("runDealGuardAudit()");
  assert.equal(network.length,1,'explicit rules-only button should work');
  assert.equal(network[0].url,'/audit');
  assert.equal(network[0].request.text,elements.input_text.value);
  elements.dg_consent.checked=true;
  await run("runHybridAudit()");
  assert.equal(network.length,2);
  assert.equal(network[1].url,'/hybrid-audit');
  assert.equal(network[1].request.consent_to_model_processing,true);
  assert.equal(network[1].request.text,elements.input_text.value);
  elements.agent_consent.checked=true;
  await run("runAgent()");
  assert.equal(network.length,3);
  assert.equal(network[2].url,'/analyze');
  assert.equal(network[2].request.phase,'in_deal');
  assert.equal(network[2].request.text,elements.input_text.value);
  // All three systems use Stage 1 structured limits, with no duplicated input.
  for(const item of network){
    assert.equal(item.request.structured_rules.discount_max_pct,10);
    assert.equal(item.request.structured_rules.payment_days,45);
  }
  console.log('V53_UI_BEHAVIOR_PASS: one editor, preserved drafts, bilingual, consent, no speech auto-analysis, shared rules');
}
main().catch(err=>{process.stderr.write(String(err.stack||err)+'\n');process.exit(1);});
