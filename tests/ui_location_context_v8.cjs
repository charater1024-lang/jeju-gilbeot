// Fake providers only. No browser, native geolocation, network or storage is used.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const contextSource=fs.readFileSync(__dirname+'/../ui/location-context.js','utf8');
const serviceSource=fs.readFileSync(__dirname+'/../ui/location-service.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(options={}){
  const nodes=[],events=new Map(),requests=[],timers=new Map();let timer=0,deviceCalls=0;
  class Element{
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attributes={};this.textContent='';this.open=false;this.isConnected=true;nodes.push(this);}
    append(...items){for(const item of items){this.children.push(item);item.parentElement=this;}}
    setAttribute(key,value){this.attributes[key]=value;}
    addEventListener(key,fn){(this.listeners[key]??=[]).push(fn);}
    fire(key){for(const fn of this.listeners[key]||[])fn({preventDefault(){}});}
    click(){if(!this.disabled)this.fire('click');}
    focus(){}showModal(){this.open=true;}close(){this.open=false;}remove(){this.isConnected=false;}
  }
  const body=new Element('body'),button=new Element('button'),status=new Element('p'),host=new Element('div');button.textContent='내 위치';
  const permission={state:'prompt',onchange:null};
  const document={body,createElement:tag=>new Element(tag)};
  const blocked=new Proxy({}, {get(){throw new Error('storage not allowed');},set(){throw new Error('storage not allowed');}});
  const sandbox={document,navigator:{permissions:{query:async()=>permission}},isSecureContext:options.secure!==false,location:{origin:'http://127.0.0.1:8765'},
    CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail;}},
    addEventListener(type,fn){(events.get(type)||events.set(type,[]).get(type)).push(fn);},dispatchEvent(event){for(const fn of events.get(event.type)||[])fn(event);},
    setTimeout(fn,delay){const id=++timer;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},sessionStorage:blocked,localStorage:blocked,fetch(){throw new Error('network not allowed');},Promise,Number,Object,Array,Math,String,Set,Date,Intl};
  if(options.api!==false)sandbox.navigator.geolocation={getCurrentPosition(success,error,settings){deviceCalls++;requests.push({success,error,settings});}};
  sandbox.window=sandbox;vm.createContext(sandbox);vm.runInContext(serviceSource,sandbox);vm.runInContext(contextSource,sandbox);
  const store=sandbox.JejuLocationContext;
  const controller=sandbox.JejuLocation.mount({button,statusElement:status,host,onStart(){store.clear('request-start',{cancelRequest:false});},onSuccess:point=>store.setDevice(point),onRevoked:()=>store.clear('revoked')});store.bind(controller);
  const node=id=>nodes.find(n=>n.id===id);
  return {sandbox,store,controller,node,nodes,requests,permission,timers,events,get deviceCalls(){return deviceCalls;},agree(){node('location-consent-agree').click();},decline(){nodes.find(n=>n.textContent==='기준 장소로 찾기').click();}};
}
(async()=>{
  const checks=[];
  {
    const f=fixture();await tick();assert.equal(f.deviceCalls,0);assert.equal(f.store.get(),null);const result=f.store.request();assert.equal(f.node('location-consent-dialog').open,true);assert.equal(f.deviceCalls,0);f.decline();assert.equal((await result).status,'cancelled');assert.equal(f.store.get(),null);checks.push('asking for a location opens consent only; declining settles the awaiting chat without calling the provider');
  }
  {
    const f=fixture();const requested=f.store.request();const again=f.store.request();assert.equal(requested,again);f.agree();assert.equal(f.deviceCalls,1);f.requests[0].success({coords:{latitude:33.506,longitude:126.492,accuracy:50}});const result=await requested;assert.equal(result.status,'success');assert.equal(result.location.source,'device');assert.equal(result.location.accuracy_m,50);const copy=f.store.get();copy.latitude=0;assert.equal(f.store.get().latitude,33.506);assert.equal(f.store.get().source,'device');checks.push('one explicit native request serves simultaneous consumers and shares a copied device origin');
  }
  {
    const f=fixture();f.store.setManual({latitude:33.51,longitude:126.49,name:'제주공항'});assert.equal(f.deviceCalls,0);assert.equal(f.store.get().source,'manual');assert.equal(f.store.get().label,'제주공항');assert.equal(f.store.setManual({latitude:NaN,longitude:126.49}),false);assert.equal(f.store.get(),null);checks.push('manual references work without native permission and invalid coordinates cannot enter the shared origin');
  }
  {
    const f=fixture();const promised=f.store.request();f.agree();f.store.setManual({latitude:33.51,longitude:126.49,label:'공항'});f.requests[0].success({coords:{latitude:33.4,longitude:126.3}});assert.equal((await promised).status,'cancelled');assert.equal(f.store.get().label,'공항');checks.push('a manually selected landmark invalidates a pending GPS response and cannot be overwritten');
  }
  {
    const f=fixture();const promised=f.store.request();f.agree();f.requests[0].success({coords:{latitude:37.5665,longitude:126.9780,accuracy:30}});const result=await promised;assert.equal(result.status,'outside-jeju');assert.equal(f.store.get(),null);assert.equal(result.location,undefined);assert.equal(result.position,undefined);checks.push('a position outside Jeju never becomes the nearby origin or leaks through a chat request result');
  }
  {
    for(const code of [1,2,3]){const f=fixture();const promised=f.store.request();f.agree();f.requests[0].error({code});assert.equal((await promised).status,'error');assert.equal(f.store.get(),null);}checks.push('denied, unavailable and timeout responses settle the waiting chat with an explicit failure');
  }
  {
    for(const options of [{secure:false},{api:false}]){const f=fixture(options);const promised=f.store.request();f.agree();assert.equal((await promised).status,'unavailable');assert.equal(f.deviceCalls,0);}checks.push('unsupported environments settle the request rather than leaving chat waiting indefinitely');
  }
  {
    const f=fixture();const promised=f.store.request();f.node('location-consent-dialog').fire('cancel');assert.equal((await promised).status,'cancelled');const second=f.store.request();f.nodes.find(n=>n.attributes['aria-label']==='위치 사용 안내 닫기').click();assert.equal((await second).status,'cancelled');assert.equal(f.deviceCalls,0);checks.push('Escape and the close button both settle consent without any native request');
  }
  {
    const f=fixture();const first=f.store.request();f.agree();f.store.clear('reset');const second=f.store.request();f.agree();f.requests[0].success({coords:{latitude:33.4,longitude:126.3}});f.requests[1].success({coords:{latitude:33.51,longitude:126.49}});assert.equal((await first).status,'cancelled');assert.equal((await second).status,'success');assert.equal(f.store.get().latitude,33.51);checks.push('reset permits a fresh request immediately and suppresses the prior provider callback');
  }
  {
    const f=fixture();f.store.setManual({latitude:33.51,longitude:126.49});f.sandbox.dispatchEvent(new f.sandbox.CustomEvent('pagehide',{}));assert.equal(f.store.get(),null);assert.equal(f.deviceCalls,0);checks.push('tab exit clears the in-memory origin without any provider or storage call');
  }
  {
    const f=fixture();await tick();f.permission.state='granted';const promised=f.store.request();assert.equal(f.deviceCalls,0);f.agree();f.requests[0].success({coords:{latitude:33.51,longitude:126.49}});await promised;f.permission.state='denied';f.permission.onchange();assert.equal(f.store.get(),null);checks.push('remembered permission still requires app consent and native permission revocation clears the shared device origin');
  }
  {
    const f=fixture();const initial=f.store.request();f.agree();f.requests[0].success({coords:{latitude:33.51,longitude:126.49}});await initial;f.store.cancel('chat-reset');assert.equal(f.store.get().source,'device');f.permission.state='denied';f.permission.onchange();assert.equal(f.store.get(),null);checks.push('cancelling chat preserves an existing device origin while later native permission revocation still clears it');
  }
  {
    const f=fixture();f.store.setManual({latitude:33.51,longitude:126.49,label:'공항'});const promised=f.store.request();f.store.cancel('chat-reset');assert.equal((await promised).status,'cancelled');assert.equal(f.store.get().label,'공항');assert.equal(f.deviceCalls,0);checks.push('cancelling a chat consent prompt settles it and preserves a previously chosen manual reference');
  }
  console.log(JSON.stringify({passed:true,checks,real_device_location_requested:false,external_network:false,storage_used:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
