'use strict';
// Tab-only fixtures, mocked local API, and public reference points. No GPS/network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../ui/app.js','utf8');
const html=fs.readFileSync(__dirname+'/../ui/index.html','utf8');
function fragment(start,end){const a=source.indexOf(start),b=source.indexOf(end,a+start.length);assert(a>=0&&b>a,`boundaries ${start}`);return source.slice(a,b);}
const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function fixture(){
  const nodes=new Map(),events=new Map(),calls=[],rendered=[],dispatched=[];let shared=null,nativeCalls=0;
  function node(selector){if(!nodes.has(selector))nodes.set(selector,{value:'',checked:false,disabled:false,hidden:true,innerHTML:'',textContent:'',listeners:{},addEventListener(k,fn){this.listeners[k]=fn},querySelector(){return node(selector+' span')},scrollIntoView(){},insertAdjacentHTML(_,html){this.innerHTML+=html}});return nodes.get(selector);}
  for(const [key,value] of Object.entries({date:'2026-11-01',transport:'car',start_time:'09:00',end_time:'18:00',budget_krw:'80000',max_stops:'3',start_lat:'33.506',start_lon:'126.492',end_lat:'33.506',end_lon:'126.492'}))node(`[name=${key}]`).value=value;
  node('#planner-return-to-origin').checked=true;node('#route-mode-saved').checked=true;node('#auto-route-region').value='all';
  const context={$:node,plannerOrigin:null,autoExcludedIDs:new Set(),tripRequest:0,lastRoute:null,lastTripRequest:null,FormData:class{get(key){return node(`[name=${key}]`).value}},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}},destinations:[{id:'seongsan'}],saved:new Set(['seongsan']),itemID:p=>p.id,notify(){},getJSON:async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return {data_mode:'reference',status:'ok',selection_mode:'automatic',stops:[]}},renderRoute:result=>rendered.push(result)};
  context.window={JejuLocationContext:{get:()=>shared,request(){nativeCalls++;throw new Error('The planner never requests GPS')}},dispatchEvent:e=>dispatched.push(e),addEventListener:(type,fn)=>{if(!events.has(type))events.set(type,[]);events.get(type).push(fn)}};
  vm.createContext(context);
  vm.runInContext(fragment('function updatePlanningMode()','// V15 planner origin'),context);
  vm.runInContext(fragment('function plannerValidPoint(','// End V15 planner origin.'),context);
  context.initPlannerOrigin();
  const emit=type=>(events.get(type)||[]).forEach(fn=>fn({type}));
  return {context,node,calls,rendered,dispatched,emit,setShared:p=>shared=p,nativeCalls:()=>nativeCalls};
}
const checks=[];
(async()=>{
  {
    const f=fixture();assert.throws(()=>f.context.formRequest(),/출발지/);assert.equal(f.nativeCalls(),0);
    f.node('#planner-apply-context').listeners.click();assert.equal(f.context.plannerOrigin,null);assert(f.node('#planner-origin-status').textContent.includes('기준 장소'));
    f.node('#planner-confirm-airport').listeners.click();const req=f.context.formRequest();assert.equal(req.origin_confirmed,true);assert.equal(req.origin_source,'landmark');assert.equal(req.start_lat,33.506);assert.equal(req.end_lat,req.start_lat);
    f.node('[name=start_lat]').value='33.45';f.node('[name=start_lat]').listeners.input();assert.throws(()=>f.context.formRequest(),/출발지/);
    checks.push('an airport default is never a confirmed origin; explicit confirmation and later edits are tracked');
  }
  {
    const f=fixture();const privatePoint={latitude:33.50678123,longitude:126.49217891,source:'device',accuracy_m:75};f.setShared(privatePoint);
    assert.equal(f.context.plannerOrigin,null,'a shared position alone is never applied');f.node('#planner-apply-context').listeners.click();
    assert.equal(f.node('[name=start_lat]').value,'');assert.equal(f.node('[name=start_lon]').value,'');assert.equal(f.node('[name=start_lat]').disabled,true);
    const req=f.context.formRequest();assert.equal(req.origin_source,'device');assert.equal(req.origin_accuracy_m,75);assert(f.node('#planner-origin-status').textContent.includes('약 75 m'));assert(f.node('#planner-origin-status').textContent.includes('수신 시각 미제공'));assert.equal(req.start_lat,privatePoint.latitude);assert.equal(req.end_lon,privatePoint.longitude);assert(!f.node('#planner-origin-status').textContent.includes(String(privatePoint.latitude)));
    f.context.lastRoute={data_mode:'reference'};const before=f.context.tripRequest;f.setShared(null);f.emit('jeju:locationchange');assert.equal(f.context.plannerOrigin,null);assert.equal(f.context.lastRoute,null);assert(f.context.tripRequest>before);assert.throws(()=>f.context.formRequest(),/출발지/);
    f.setShared(privatePoint);f.node('#planner-apply-context').listeners.click();f.emit('pagehide');assert.equal(f.context.plannerOrigin,null);f.setShared({...privatePoint,accuracy_m:6000});f.node('#planner-apply-context').listeners.click();assert(f.node('#planner-origin-status').textContent.includes('오차가 5km 이상'));assert.equal(f.nativeCalls(),0);
    checks.push('device origins are opt-in, hidden in coordinate fields and invalidated on revocation and page exit');
  }
  {
    const f=fixture();f.setShared({latitude:33.543,longitude:126.669,source:'manual',label:'함덕 기준'});f.node('#planner-apply-context').listeners.click();assert.equal(f.context.formRequest().origin_source,'landmark');
    f.setShared({latitude:33.45,longitude:126.56,source:'manual',label:'다른 기준'});f.emit('jeju:locationchange');assert.equal(f.context.plannerOrigin,null);
    f.node('[name=start_lat]').value='37.5';f.node('[name=start_lon]').value='127';f.node('#planner-confirm-coordinates').listeners.click();assert.equal(f.context.plannerOrigin,null);
    f.node('#planner-confirm-airport').listeners.click();f.node('#planner-return-to-origin').checked=false;f.node('#planner-return-to-origin').listeners.change();f.node('[name=end_lat]').value='33.25';f.node('[name=end_lon]').value='126.56';const req=f.context.formRequest();assert.equal(req.end_lat,33.25);assert.equal(f.node('[name=end_lat]').disabled,false);f.node('[name=end_lat]').value='37.5';assert.throws(()=>f.context.formRequest(),/도착지/);
    checks.push('shared manual changes and invalid positions require a new confirmation; the return point is explicit');
  }
  {
    const f=fixture();f.node('#planner-confirm-airport').listeners.click();f.node('#route-mode-auto').checked=true;f.node('#auto-route-query').value='해변';f.node('#auto-route-region').value='north';f.context.autoExcludedIDs.add('hyeopjae');
    vm.runInContext(fragment('$("#planner-form").addEventListener("submit"','// V3 feature declarations'),f.context);
    await f.node('#planner-form').listeners.submit({preventDefault(){}});assert.equal(f.calls[0].path,'/api/agent/plan');assert.equal(f.calls[0].body.origin_confirmed,true);assert.equal(f.calls[0].body.query,'해변');assert.deepEqual(f.calls[0].body.excluded_ids,['hyeopjae']);assert.equal(f.calls[0].body.destination_ids,undefined);
    f.node('#route-mode-auto').checked=false;await f.node('#planner-form').listeners.submit({preventDefault(){}});assert.equal(f.calls[1].path,'/api/plan-destinations');assert.deepEqual(f.calls[1].body.destination_ids,['seongsan']);
    checks.push('automatic and saved-place plans use separate real-data endpoints and exclusions are preserved');
  }
  {
    const f=fixture();f.node('#planner-confirm-airport').listeners.click();f.node('#route-mode-auto').checked=true;let finish;f.context.getJSON=()=>new Promise(resolve=>finish=resolve);
    vm.runInContext(fragment('$("#planner-form").addEventListener("submit"','// V3 feature declarations'),f.context);
    const pending=f.node('#planner-form').listeners.submit({preventDefault(){}});assert.equal(f.node('#create-trip').disabled,true);f.context.invalidatePlannerOrigin();assert.equal(f.node('#create-trip').disabled,false);finish({status:'ok',data_mode:'reference',stops:[]});await pending;assert.equal(f.rendered.length,0);
    f.node('#planner-confirm-airport').listeners.click();f.context.lastRoute={status:'ok'};f.node('[name=budget_krw]').listeners.input();assert.equal(f.context.lastRoute,null);assert.equal(f.context.formRequest().origin_confirmed,true);
    checks.push('changing an origin suppresses a late response and re-enables the button; edited trip conditions invalidate the old route');
  }
  {
    const f=fixture();Object.assign(f.context,{escapeHTML,URL,won:String,clock:String,icon:()=>'',notify(){}});f.context.window.JejuPages={reveal(){}};
    vm.runInContext(fragment('function renderRoute(','function updatePlanningMode('),f.context);
    f.context.renderRoute({status:'ok',data_mode:'reference',selection_mode:'automatic',stops:[{poi_id:'seongsan',name:'성산 <script>',arrival_minute:600,departure_minute:690,stay_minutes:90,travel_minutes:20}],totals:{},selected_place_evidence:[{id:'seongsan',selection_reason:'검색 <img>',warnings:['넥슨뮤지엄 이름 변경 안내 <script>'],sources:[{name:'공식 소개',url:'https://www.visitjeju.net/kr/detail/view?contentsid=FIXTURE',checked_at:'2026-10-29'},{name:'bad',url:'javascript:alert(1)'}]}],exclusions:[{name:'제외 후보',reasons:[{code:'closed',message:'통제 안내 확인 <script>'}]}],planning_assumptions:[{basis:'체류시간은 계획용 가정'}],trace:[{agent:'정보 확인',status:'completed',detail:'공식 출처 연결'}]});
    const html=f.node('#trip-result').innerHTML;assert(html.includes('data-exclude-route="seongsan"'));assert(html.includes('2026-10-29'));assert(html.includes('넥슨뮤지엄 이름 변경 안내 &lt;script&gt;'));assert(html.includes('체류시간은 계획용 가정'));assert(html.includes('통제 안내 확인 &lt;script&gt;'));assert(!html.includes('[object Object]'));assert(!html.includes('javascript:'));assert(!html.includes('<script>'));
    checks.push('structured source evidence, dates, assumptions and exclusion reasons render safely without confidence percentages');
  }
  {
    let blob;const privateLat='33.50678123',privateLon='126.49217891';
    const ctx={lastRoute:{status:'ok',data_mode:'reference',selection_mode:'automatic',request:{date:'2026-11-01',start_lat:Number(privateLat),start_lon:Number(privateLon),origin_label:'PRIVATE'},stops:[{poi_id:'seongsan',name:'성산일출봉',trust:{warnings:['해변 산책·경관 후보이며 수영 가능 여부 미확인 <img>'],sources:[{name:'공식 관광',url:'https://www.visitjeju.net/kr/detail/view?contentsid=PUBLIC',checked_at:'2026-10-29'}]}}],totals:{},warnings:[]},lastTripRequest:null,destinations:[],todayKST:()=> '2026-11-01',escapeHTML,clock:String,won:String,safeLink:v=>/^https?:\/\//.test(v||'')?v:'',itemID:x=>x.id,Blob,URL:{createObjectURL(value){blob=value;return 'blob:fixture'},revokeObjectURL(){}},document:{createElement(){return {click(){},remove(){}}},body:{append(){}}},setTimeout(){},notify(){}};
    vm.createContext(ctx);vm.runInContext(fragment('function saveItinerary()','function resetTrip()')+'\nsaveItinerary();',ctx);const saved=await blob.text();assert(saved.includes('2026-10-29'));assert(saved.includes('visitjeju.net'));assert(saved.includes('수영 가능 여부 미확인 &lt;img&gt;'));assert(!saved.includes('<img>'));assert(!saved.includes(privateLat));assert(!saved.includes(privateLon));assert(!saved.includes('PRIVATE'));
    checks.push('automatic itinerary export retains public provenance and omits private origin coordinates and labels');
  }
  {
    const f=fixture(),discovery=fs.readFileSync(__dirname+'/../ui/discovery.js','utf8');let fetches=0;const routes=[];
    Object.assign(f.context,{geometryRequest:0,routePoints:[],lastGeometry:null,showPlaces(){},map:{clearRoute(){},setRoute:r=>routes.push(r)},fetch:async()=>{fetches++;throw new Error('embedded route must be reused')}});
    const begin=discovery.indexOf('async function routeFor('),end=discovery.indexOf('function updateSaved(',begin);
    vm.runInContext(discovery.slice(begin,end),f.context);
    await f.context.routeFor({status:'ok',data_mode:'reference',request:{start_lat:33.506,end_lat:33.506,start_lon:126.492,end_lon:126.492},stops:[{poi_id:'seongsan',name:'성산일출봉'}],route_geometry:{kind:'road',stops:[{id:'seongsan'}],coordinates:[[126.492,33.506],[126.9,33.4]],distance_km:40,warnings:[]}});
    assert.equal(fetches,0);assert.equal(routes.at(-1).contains_private_location,true);assert.equal(routes.at(-1).origin.private,true);
    checks.push('central route geometry is reused and still marked private when confirmed endpoints are present');
  }
  assert(html.includes('id="planner-confirm-airport"'));assert(html.includes('id="route-mode-auto"'));assert(!source.includes('navigator.geolocation'));
  console.log(JSON.stringify({passed:true,checks,real_gps_requested:false,external_network:false}));
})().catch(error=>{console.error(error);process.exitCode=1});
