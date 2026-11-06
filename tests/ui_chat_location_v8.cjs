// Location-aware chatbot DOM integration. All positions/consents are synthetic.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const SOURCE=fs.readFileSync(__dirname+'/../ui/chatbot.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const DEVICE={latitude:33.50123456,longitude:126.49123456,accuracy_m:75,source:'device'};
function fixture({initialLocation=null,pathname='/',chatRequested=false}={}){
  const all=[],listeners=new Map(),requests=[],posted=[],held=[],consents=[],navigated=[];let current=initialLocation?{...initialLocation}:null,hold=false,scripted=[],cancelled=0;
  class Element{
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attributes={};this.className='';this.textContent='';this.value='';this.disabled=false;this.hidden=false;this.open=false;this.parentElement=null;this.isConnected=true;this.scrollTop=0;this.scrollHeight=200;all.push(this);}
    append(...items){for(const item of items){this.children.push(item);item.parentElement=this;}}
    prepend(...items){for(const item of items.reverse()){this.children.unshift(item);item.parentElement=this;}}
    setAttribute(key,value){this.attributes[key]=String(value);if(key==='open')this.open=true;}getAttribute(key){return this.attributes[key]??null;}removeAttribute(key){delete this.attributes[key];if(key==='open')this.open=false;}
    addEventListener(key,fn){this.listeners[key]=fn;}
    focus(){document.activeElement=this;}showModal(){this.open=true;}close(){this.open=false;}
    contains(node){return node===this||this.children.some(child=>child.contains(node));}
    getBoundingClientRect(){return {top:this.className==='jc-log'?100:this.parentElement?.className==='jc-log'?100+this.parentElement.children.indexOf(this)*500-this.parentElement.scrollTop:0};}
    replaceChildren(...items){for(const item of this.children)item.parentElement=null;this.children=[];this.append(...items);}
    remove(){if(this.parentElement){this.parentElement.children=this.parentElement.children.filter(item=>item!==this);this.parentElement=null;}}
    querySelectorAll(selector){const found=[];function visit(node){for(const item of node.children){if(selector.startsWith('.')&&item.className.split(/\s+/).includes(selector.slice(1)))found.push(item);visit(item);}}visit(this);return found;}
    get firstElementChild(){return this.children[0];}scrollIntoView(){}
    click(){if(!this.disabled)return this.listeners.click?.({target:this,preventDefault(){}});}
  }
  const body=new Element('body'),planner=new Element('section'),explore=new Element('section'),landmark=new Element('select');planner.id='planner';explore.id='map-explorer';landmark.id='origin-landmark';body.append(planner,explore,landmark);
  const document={body,activeElement:null,createElement:tag=>new Element(tag),getElementById:id=>all.find(n=>n.id===id)};
  const blocked=new Proxy({}, {get(){throw new Error('storage forbidden');},set(){throw new Error('storage forbidden');}});
  const response={reply:'가까운 해변 기록입니다.',cards:[{id:'test_beach',plan_place_id:'test_beach',name:'시험 해변',latitude:33.51,longitude:126.5,distance_km:1.25,category:'해변'}],quick_replies:[],state:{topic:'tourism',region:'all',nearby:true,choice_ids:['test_beach'],latitude:DEVICE.latitude,longitude:DEVICE.longitude,location:{latitude:DEVICE.latitude}},intent:'tourism_nearby'};
  const needsLocation={reply:'주변 검색에 위치가 필요합니다.',needs_location:true,state:{nearby:true},cards:[]};
  function emit(type,detail){for(const fn of listeners.get(type)||[])fn({detail});}
  function setLocation(point){current=point?{...point}:null;emit('jeju:locationchange',{location:current?{...current}:null});}
  const locationContext={get:()=>current?{...current}:null,request(){return new Promise(resolve=>consents.push({resolve,done:false}));},clear(){setLocation(null);},cancel(){cancelled++;for(const consent of consents)if(!consent.done){consent.done=true;consent.resolve({status:'cancelled'});}}};
  const location=new Proxy({pathname,origin:'http://127.0.0.1:8765',href:'http://127.0.0.1:8765'+pathname},{set(){throw new Error('chat must not put location in URL');}});
  const sandbox={document,location,URL,JSON,Number,String,Array,Object,Set,Map,Math,Promise,AbortController,setTimeout,clearTimeout,localStorage:blocked,sessionStorage:blocked,JejuLocationContext:locationContext,
    navigator:{geolocation:{getCurrentPosition(){throw new Error('chat must use consent service rather than native GPS');}}},
    addEventListener(type,fn){(listeners.get(type)||listeners.set(type,[]).get(type)).push(fn);},
    JejuPages:{navigate:path=>navigated.push(path),reveal:node=>navigated.push(node.id==='planner'?'/planner':'/explore'),consumeChatRequest(){const requested=chatRequested;chatRequested=false;return requested;}},JejuTripBridge:{getRoute:()=>null,openPlace(){},addPlace:()=>true},JejuExplore:{showPlaces(){},showRoute(){}},
    async fetch(url,options){requests.push({url,options});if(url==='/api/chat/status')return {ok:true,json:async()=>({prepared_answers:33585,faq_count:26})};assert.equal(url,'/api/chat');const body=JSON.parse(options.body);posted.push(body);const nearby=/주변|가까운|다른 곳/.test(body.message);
      const next=scripted.length ? scripted.shift()
        : !body.location&&!body.location_declined&&nearby ? needsLocation
        : {...response,location_used:!!body.location,state:{...response.state,nearby:!!body.location,radius_km:5,result_limit:2}};
      if(hold&&body.location)return new Promise(resolve=>held.push(()=>resolve({ok:true,json:async()=>next})));return {ok:true,json:async()=>next};}};
  sandbox.window=sandbox;vm.createContext(sandbox);vm.runInContext(SOURCE,sandbox);
  const node=id=>document.getElementById(id),text=node=>[node?.textContent||'',...(node?.children||[]).map(text)].join('\n');
  async function submit(message){if(!node('jeju-chat-dialog').open)sandbox.JejuChat.open();node('jeju-chat-input').value=message;all.find(n=>n.className==='jc-form').listeners.submit({preventDefault(){}});await tick();}
  async function consent(status,point=DEVICE){const waiting=consents.find(item=>!item.done);assert(waiting,'consent is waiting');waiting.done=true;if(status==='success')setLocation(point);waiting.resolve(status==='success'?{status,location:{...current}}:{status});await tick();}
  return {sandbox,all,node,text,requests,posted,consents,navigated,held,response,submit,consent,emit,setLocation,context:locationContext,get cancelled(){return cancelled;},set hold(value){hold=value;},set scripted(value){scripted=value;}};
}
(async()=>{
  const checks=[];
  {
    const f=fixture();await tick();assert.equal(f.node('jeju-chat-dialog').tagName,'DIALOG');assert.equal(f.node('jeju-chat-dialog').parentElement.tagName,'BODY');assert.equal(f.node('jeju-chat-dialog').open,false);assert.equal(f.consents.length,0);assert.equal(f.posted.length,0);assert.equal(f.requests.length,0);await f.submit('함덕해수욕장 주소');assert.equal(f.requests[0].url,'/api/chat/status');assert.equal(f.node('jeju-chat-dialog').open,true);assert.equal(f.consents.length,0);assert.equal(f.posted.length,1);assert.equal(f.posted[0].location,undefined);checks.push('floating dialog stays closed on load and opening/status/details never request device position or consent');
  }
  {
    const f=fixture();await f.submit('북부 해변 추천');await f.submit('성산일출봉 근처 카페');assert.equal(f.consents.length,0);assert.equal(f.posted.length,2);assert(f.posted.every(body=>!body.location));checks.push('regional and named-place queries reach the server without a location prompt');
  }
  {
    const f=fixture();await f.submit('내 주변 관광지 추천');assert.equal(f.consents.length,1);assert.equal(f.posted.length,1);assert.equal(f.posted[0].location,undefined);assert.equal(f.node('jeju-chat-input').disabled,true);await f.consent('success');assert.equal(f.posted.length,2);assert.equal(f.posted[1].location.latitude,DEVICE.latitude);assert.equal(f.posted[1].location.longitude,DEVICE.longitude);assert.equal(f.posted[1].state.latitude,undefined);assert.match(f.text(f.node('jeju-chat-log')),/직선 1\.3km/);assert(!f.text(f.node('jeju-chat-log')).includes(String(DEVICE.latitude)));const moved={...DEVICE,latitude:33.55123456};f.setLocation(moved);await f.submit('영업시간 알려줘');assert.equal(f.posted.at(-1).state.latitude,undefined);assert.equal(f.posted.at(-1).state.longitude,undefined);assert.equal(f.posted.at(-1).state.location,undefined);assert.equal(f.posted.at(-1).location,undefined);assert(f.requests.every(row=>row.url==='/api/chat'||row.url==='/api/chat/status'));checks.push('only server-confirmed nearby searches request consent; conversation state omits private coordinates');
  }
  {
    for(const status of ['cancelled','error','unavailable','outside-jeju']){const f=fixture();await f.submit('가까운 맛집 추천');await f.consent(status);assert.equal(f.posted[1].location,undefined);assert.equal(f.posted[1].location_declined,true);await f.submit('관광지도 추천');assert.equal(f.consents.length,1);assert.equal(f.posted.at(-1).location,undefined);assert.equal(f.posted.at(-1).location_declined,true);}checks.push('decline, failure and outside-Jeju positions continue without location and do not repeatedly prompt on every recommendation');
  }
  {
    const f=fixture();await f.submit('가까운 맛집 추천');await f.consent('cancelled');const retry=f.node('chat-use-location').click();await tick();assert.equal(f.consents.length,2);await f.consent('success');await retry;assert.equal(f.posted.length,2,'toolbar consent should not invent a question');await f.submit('내 주변 맛집 추천');assert.equal(f.consents.length,2);assert.equal(f.posted.at(-1).location.latitude,DEVICE.latitude);assert.equal(f.posted.at(-1).location_declined,undefined);checks.push('the location toolbar explicitly retries after a decline and successful retry enables subsequent nearby recommendations');
  }
  {
    const manual={latitude:33.506,longitude:126.492,source:'manual',label:'제주공항'};const f=fixture({initialLocation:manual});await f.submit('남부 해변 추천');
    assert.equal(f.posted[0].location,undefined);
    await f.submit('내 주변 관광지 추천');
    assert.equal(f.consents.length,0);
    assert.equal(f.posted[1].location,undefined);
    assert.equal(f.posted[2].location.latitude,manual.latitude);
    f.setLocation({...manual,latitude:33.2468});
    await f.submit('다른 곳 보기');
    assert.equal(f.posted[3].location,undefined);
    assert.equal(f.posted[4].location.latitude,33.2468);
    assert.equal(f.posted[4].restart_page,true);
    assert.equal(f.posted[4].state.radius_km,5);
    assert.equal(f.posted[4].state.result_limit,2);assert.match(f.text(f.node('chat-location-status')),/제주공항.*실제 내 위치가 아닙니다/);checks.push('a shared manual landmark is reused without GPS and clearly labelled as a reference rather than device position');
  }
  {
    for(const reason of ['clear','revoke']){const f=fixture({initialLocation:DEVICE});f.hold=true;await f.submit('내 주변 관광지 추천');assert.equal(f.held.length,1);const signal=f.requests.at(-1).options.signal;f.context.clear(reason);assert.equal(signal.aborted,true);f.held.shift()();await tick();assert.equal(f.node('jeju-chat-log').children.length,2,'late private-origin reply must not be appended');assert.equal(f.node('jeju-chat-input').disabled,false);}checks.push('clearing or revoking the active origin aborts a pending request and ignores a late reply');
  }
  {
    const f=fixture();await f.submit('가까운 관광지 추천');assert.equal(f.consents.length,1);f.sandbox.JejuChat.reset();await tick();assert.equal(f.cancelled,1);assert.equal(f.posted.length,1);assert.equal(f.posted[0].location,undefined);assert.equal(f.node('jeju-chat-log').children.length,1);assert.equal(f.node('jeju-chat-input').disabled,false);checks.push('reset during consent cancels the shared request and prevents replay of the abandoned question');
  }
  {
    const f=fixture();f.scripted=[{reply:'주변 검색에 위치가 필요합니다.',needs_location:true,state:{nearby:true},cards:[]},f.response];await f.submit('여기 어때');assert.equal(f.posted.length,1);assert.equal(f.consents.length,1);await f.consent('success');assert.equal(f.posted.length,2);assert.equal(f.posted[0].location,undefined);assert.equal(f.posted[1].location.latitude,DEVICE.latitude);assert.equal(f.posted[0].message,f.posted[1].message);assert.equal(f.node('jeju-chat-log').children.filter(n=>n.className==='jc-turn jc-user').length,1);assert.equal(f.node('jeju-chat-log').children.length,3);checks.push('server needs_location metadata opens consent and replays the same question once without duplicating the user turn');
  }
  {
    const f=fixture({pathname:'/explore'});await tick();assert.equal(f.requests.length,0);assert.equal(f.consents.length,0);f.sandbox.JejuChat.open();await tick();assert.equal(f.navigated.length,0);assert.equal(f.node('jeju-chat-dialog').open,true);assert.equal(f.consents.length,0);assert.equal(f.requests.length,1);await f.submit('함덕해수욕장 주소');const count=f.node('jeju-chat-log').children.length;f.sandbox.JejuChat.close();assert.equal(f.node('jeju-chat-dialog').open,false);assert.equal(f.node('jeju-chat-launcher').getAttribute('aria-expanded'),'false');f.sandbox.JejuChat.open();assert.equal(f.node('jeju-chat-log').children.length,count);assert.equal(f.navigated.length,0);checks.push('opening and closing the floating chatbot preserve the underlying page and conversation');
  }
  {
    const f=fixture({chatRequested:true});await tick();assert.equal(f.node('jeju-chat-dialog').open,true);assert.equal(f.navigated.length,0);assert.equal(f.consents.length,0);assert.equal(f.requests.length,1);checks.push('a deferred direct chat entry opens the same popup without requesting location');
  }
  {
    const f=fixture();
    const item=f.response.cards[0];
    const visit_review={required:true,reasons:[{message:'기록된 접근 통제'}],source_url:'https://www.visitjeju.net/'};
    f.scripted=[{...f.response,cards:[{...item,visit_review}]}];
    await f.submit('남부 해변 추천');
    assert.match(f.text(f.node('jeju-chat-log')),/기록된 접근 통제/);
    assert.equal(f.node('jeju-chat-log').querySelectorAll('.jc-place-add').length,0);
    assert(f.node('jeju-chat-log').querySelectorAll('.jc-place-source').some(node=>node.href===visit_review.source_url));
    checks.push('visit restrictions show source and block itinerary add on the recommendation card');
  }
  {
    const f=fixture();
    await f.submit('해변 추천');
    const add=f.node('jeju-chat-log').querySelectorAll('.jc-place-add')[0];
    f.emit('jeju:saved',{items:[{id:f.response.cards[0].id}]});
    assert.equal(add.disabled,true);
    f.emit('jeju:saved',{items:[]});
    assert.equal(add.disabled,false);
    checks.push('saving or removing a place elsewhere updates the existing chat card');
  }
  console.log(JSON.stringify({passed:true,checks,real_device_location_requested:false,external_network:false,storage_used:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
