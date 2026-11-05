// Isolated location UI tests: fake browser permissions/provider, never real GPS.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const SOURCE=fs.readFileSync(__dirname+'/../ui/location-service.js','utf8');

function fixture(options={}){
  const all=[],windowEvents=new Map(),documentEvents=new Map(),pending=[],started=[],succeeded=[],revoked=[],network=[],timers=new Map();let sequence=0;
  class Element{
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.attributes={};this.listeners={};this.className='';this.textContent='';this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.open=false;this.parentElement=null;this.type='';all.push(this);}
    append(...items){for(let item of items){if(typeof item==='string')item=new Text(item);item.parentElement=this;this.children.push(item);}}
    prepend(...items){for(const item of items.reverse()){item.parentElement=this;this.children.unshift(item);}}
    replaceChildren(...items){for(const child of this.children)child.parentElement=null;this.children=[];this.append(...items);}
    remove(){if(this.parentElement){this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null;}}
    setAttribute(key,value){this.attributes[key]=String(value);if(key==='open')this.open=true;if(key==='id')this.id=String(value);}
    getAttribute(key){return this.attributes[key]??null;}
    removeAttribute(key){delete this.attributes[key];if(key==='open')this.open=false;}
    addEventListener(type,callback){(this.listeners[type]??=[]).push(callback);}
    removeEventListener(type,callback){this.listeners[type]=(this.listeners[type]||[]).filter(fn=>fn!==callback);}
    dispatch(type,event={}){for(const callback of this.listeners[type]||[])callback({target:this,preventDefault(){},...event});}
    click(){if(!this.disabled)this.dispatch('click');}
    focus(){document.activeElement=this;}
    showModal(){this.open=true;}
    close(){this.open=false;this.dispatch('close');}
    contains(item){return item===this||this.children.some(child=>child.contains?.(item));}
    get isConnected(){return this===document.body||Boolean(this.parentElement?.isConnected);}
    get classList(){return {add:(...names)=>{this.className=[...new Set([...this.className.split(/\s+/).filter(Boolean),...names])].join(' ');},remove:(...names)=>{this.className=this.className.split(/\s+/).filter(name=>!names.includes(name)).join(' ');},toggle:(name,value)=>{const active=value??!this.className.split(/\s+/).includes(name);active?this.classList.add(name):this.classList.remove(name);return active;},contains:name=>this.className.split(/\s+/).includes(name)};}
    querySelectorAll(selector){const result=[];const visit=node=>{for(const child of node.children){if(match(child,selector))result.push(child);visit(child);}};visit(this);return result;}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    scrollIntoView(){}
  }
  class Text extends Element{constructor(value){super('#text');this.textContent=value;}}
  function match(node,selector){
    if(selector.startsWith('#'))return node.id===selector.slice(1);
    if(selector.startsWith('.'))return node.className.split(/\s+/).includes(selector.slice(1));
    const typed=selector.match(/^([a-z]+)\[type=["']?([^\]"']+)["']?\]$/i);if(typed)return node.tagName===typed[1].toUpperCase()&&node.type===typed[2];
    return node.tagName===selector.toUpperCase();
  }
  const body=new Element('body'),button=new Element('button'),status=new Element('p'),host=new Element('div');button.id='use-location';status.id='location-status';host.className='shared-origin';host.append(button,status);body.append(host);
  const document={body,activeElement:button,visibilityState:'visible',createElement:tag=>new Element(tag),createTextNode:value=>new Text(value),getElementById:id=>all.find(node=>node.id===id&&node.isConnected)||null,querySelector:selector=>all.find(node=>match(node,selector)&&node.isConnected)||null,querySelectorAll:selector=>all.filter(node=>match(node,selector)&&node.isConnected),addEventListener(type,fn){(documentEvents.get(type)||documentEvents.set(type,[]).get(type)).push(fn);},removeEventListener(type,fn){documentEvents.set(type,(documentEvents.get(type)||[]).filter(callback=>callback!==fn));}};
  if(options.policy!==undefined)document.permissionsPolicy={allowsFeature:()=>options.policy};
  const permission={state:options.permission||'prompt',listeners:[],addEventListener(type,fn){if(type==='change')this.listeners.push(fn);},removeEventListener(type,fn){this.listeners=this.listeners.filter(callback=>callback!==fn);},emit(value){this.state=value;this.listeners.forEach(fn=>fn());this.onchange?.();}};
  const unavailableStorage=new Proxy({}, {get(){throw new Error('location must not use browser storage');},set(){throw new Error('location must not use browser storage');}});
  const navigator={userAgent:'Fake Chromium Windows fixture'};
  if(options.api!==false)navigator.geolocation={getCurrentPosition(ok,bad,settings){if(options.throwProvider)throw new Error('mock provider unavailable');pending.push({ok,bad,settings});}};
  if(options.permissions!==false)navigator.permissions={query:async()=>{if(options.rejectPermissions)throw new Error('mock query unsupported');return permission;}};
  const context={document,navigator,location:{origin:'http://127.0.0.1:8765',hostname:'127.0.0.1',host:'127.0.0.1:8765',protocol:'http:',href:'http://127.0.0.1:8765/'},isSecureContext:options.secure!==false,URL,Intl,JSON,Number,String,Array,Object,Set,Map,Promise,Math,Date,Error,
    setTimeout(callback,delay){const id=++sequence;timers.set(id,{callback,delay});return id;},clearTimeout(id){timers.delete(id);},
    addEventListener(type,fn){(windowEvents.get(type)||windowEvents.set(type,[]).get(type)).push(fn);},removeEventListener(type,fn){windowEvents.set(type,(windowEvents.get(type)||[]).filter(callback=>callback!==fn));},
    fetch(...args){network.push(args);throw new Error('location UI may not call external services');},sessionStorage:unavailableStorage,localStorage:unavailableStorage};
  context.window=context;context.top=context;context.parent=context;vm.createContext(context);vm.runInContext(SOURCE,context);
  const controller=context.JejuLocation.mount({button,statusElement:status,host,onStart:()=>started.push(true),onSuccess:value=>succeeded.push(value),onRevoked:()=>revoked.push(true)});
  const node=id=>document.getElementById(id),text=node=>[node?.textContent||'',...(node?.children||[]).map(text)].join('\n');
  const agree=()=>{const current=node('location-consent-agree');assert(current,'consent agree button exists');current.click();};
  const fireWatchdog=()=>{const found=[...timers.entries()].find(([,value])=>value.delay>=35000);assert(found,'request watchdog exists');timers.delete(found[0]);found[1].callback();};
  return {context,controller,all,body,button,status,host,pending,permission,started,succeeded,revoked,network,timers,node,text,agree,fireWatchdog,windowEvents,documentEvents};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const checks=[];
  {
    const f=fixture();await tick();await f.controller.refresh();assert.equal(f.pending.length,0);assert.equal(f.succeeded.length,0);f.controller.open();await tick();assert.equal(f.node('location-consent-dialog').open,true);assert.equal(f.pending.length,0);assert.match(f.text(f.node('location-consent-dialog')),/동의|위치/);f.controller.cancel();assert.equal(f.pending.length,0);checks.push('page load, refresh and the consent explanation never request a device location');
  }
  {
    const f=fixture();f.controller.open();const decline=f.all.find(node=>node.tagName==='BUTTON'&&node.textContent==='기준 장소로 찾기');assert(decline);decline.click();assert.equal(f.node('location-consent-dialog').open,false);assert.equal(f.pending.length,0);assert.equal(f.started.length,0);assert.match(f.status.textContent,/요청하지|기준 장소/);checks.push('choosing a manual reference instead of consent closes the explanation without reading a location');
  }
  {
    const f=fixture();f.controller.open();f.agree();assert.equal(f.pending.length,1);assert.equal(f.pending[0].settings.enableHighAccuracy,false);assert.equal(f.pending[0].settings.timeout,20000);assert.equal(f.pending[0].settings.maximumAge,60000);assert.equal(f.started.length,1);f.pending[0].ok({coords:{latitude:33.506,longitude:126.492,accuracy:75}});assert.equal(f.succeeded.length,1);assert.equal(f.succeeded[0].latitude,33.506);assert.equal(f.succeeded[0].longitude,126.492);assert.equal(f.succeeded[0].accuracy_m,75);assert.equal(f.button.disabled,false);assert.equal(f.network.length,0);checks.push('explicit consent starts one bounded request and returns only the provider coordinates');
  }
  {
    const f=fixture();f.controller.open();f.node('location-precise').checked=true;f.agree();assert.equal(f.pending[0].settings.enableHighAccuracy,true);assert.equal(f.pending[0].settings.timeout,30000);assert([...f.timers.values()].some(timer=>timer.delay===45000));f.controller.open();f.agree();assert.equal(f.pending.length,1,'pending requests must not be duplicated');f.pending[0].ok({coords:{latitude:33.506,longitude:126.492,accuracy:5}});f.pending[0].ok({coords:{latitude:33.55,longitude:126.55,accuracy:4}});assert.equal(f.succeeded.length,1);checks.push('explicit precision choice uses the longer bound while duplicate requests and callbacks are ignored');
  }
  {
    const f=fixture({permission:'denied'});await tick();f.controller.open();f.agree();if(f.pending.length)f.pending[0].bad({code:1});assert.equal(f.succeeded.length,0);assert.match(f.text(f.host)+' '+f.status.textContent,/차단|권한|설정/);assert.equal(f.button.disabled,false);checks.push('remembered denial gives recovery guidance without producing a location');
  }
  {
    for(const options of [{secure:false},{api:false},{policy:false}]){const f=fixture(options);await tick();f.controller.open();f.agree();assert.equal(f.pending.length,0);assert.equal(f.succeeded.length,0);assert.equal(f.button.disabled,false);}checks.push('insecure origins, missing location API and policy denial do not invoke the provider');
  }
  {
    for(const options of [{permissions:false},{rejectPermissions:true}]){const f=fixture(options);await tick();f.controller.open();f.agree();assert.equal(f.pending.length,1);f.pending[0].bad({code:2});assert.equal(f.succeeded.length,0);assert.equal(f.button.disabled,false);}checks.push('unsupported permission inspection does not prevent an explicit location request');
  }
  {
    for(const code of [1,2,3]){const f=fixture();f.controller.open();f.agree();f.pending[0].bad({code});assert.equal(f.succeeded.length,0);assert.equal(f.button.disabled,false);assert(f.status.textContent.length>0);}checks.push('denied, unavailable and timeout callbacks all leave a usable fallback');
  }
  {
    const f=fixture();f.controller.open();f.agree();f.controller.cancel();f.pending[0].ok({coords:{latitude:33.506,longitude:126.492,accuracy:10}});assert.equal(f.succeeded.length,0);assert.equal(f.button.disabled,false);checks.push('cancel invalidates callbacks that arrive after a reset or manual-place selection');
  }
  {
    const f=fixture();f.controller.open();f.agree();f.fireWatchdog();assert.equal(f.button.disabled,false);assert.match(f.status.textContent,/응답|시간|초과/);f.pending[0].ok({coords:{latitude:33.506,longitude:126.492,accuracy:10}});assert.equal(f.succeeded.length,0);checks.push('an unresponsive embedded provider is stopped by the watchdog and its late callback is ignored');
  }
  {
    const f=fixture({permission:'granted'});await tick();f.controller.open();f.agree();f.pending[0].ok({coords:{latitude:33.506,longitude:126.492,accuracy:10}});f.permission.emit('denied');await tick();assert.equal(f.revoked.length,1);assert.equal(f.button.disabled,false);checks.push('revoking a previously granted permission clears the active location through the integration callback');
  }
  {
    const f=fixture({permission:'granted'});await tick();f.controller.open();f.agree();f.pending[0].ok({coords:{latitude:33.506,longitude:126.492,accuracy:10}});f.controller.cancel();f.permission.emit('denied');await tick();assert.equal(f.revoked.length,0,'revocation after the device origin was cleared must not clear a newly selected manual reference');checks.push('permission changes after cancellation do not emit a stale device-origin clear event');
  }
  {
    for(const coords of [{latitude:NaN,longitude:126.492},{latitude:33.506,longitude:Infinity},{latitude:91,longitude:126.492},null]){const f=fixture();f.controller.open();f.agree();f.pending[0].ok({coords});assert.equal(f.succeeded.length,0);assert.equal(f.button.disabled,false);}checks.push('nonfinite or globally invalid provider coordinates are never returned to the search integration');
  }
  {
    const f=fixture({throwProvider:true});f.controller.open();assert.doesNotThrow(()=>f.agree());assert.equal(f.button.disabled,false);assert.equal(f.succeeded.length,0);checks.push('synchronous host-provider failure is handled without leaving the request pending');
  }
  {
    const f=fixture();f.controller.open();f.agree();f.controller.destroy();f.pending[0].ok({coords:{latitude:33.506,longitude:126.492,accuracy:10}});assert.equal(f.succeeded.length,0);assert.equal(f.network.length,0);checks.push('destroy invalidates a pending request and performs no network or storage operation');
  }
  console.log(JSON.stringify({passed:true,checks,real_device_location_requested:false,external_network:false,storage_used:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
