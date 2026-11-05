'use strict';
// Public-place fixtures and mocked local APIs only; no browser GPS/network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../ui/app.js','utf8');
function fragment(start,end){const a=source.indexOf(start),b=source.indexOf(end,a+start.length);assert(a>=0&&b>a);return source.slice(a,b);}
const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function fixture(){
  const nodes=new Map(),events=new Map(),rendered=[],dispatched=[];
  function node(selector){if(!nodes.has(selector))nodes.set(selector,{value:'',checked:false,disabled:false,hidden:true,innerHTML:'',textContent:'',listeners:{},addEventListener(type,fn){this.listeners[type]=fn},querySelector(){return node(selector+' span')},scrollIntoView(){},insertAdjacentHTML(_,html){this.innerHTML+=html}});return nodes.get(selector);}
  for(const [key,value] of Object.entries({date:'2026-11-03',transport:'car',start_time:'09:00',end_time:'18:00',budget_krw:'80000',max_stops:'3',start_lat:'33.506',start_lon:'126.492',end_lat:'33.506',end_lon:'126.492'}))node(`[name=${key}]`).value=value;
  node('#planner-return-to-origin').checked=true;node('#route-mode-saved').checked=true;node('#auto-route-region').value='all';
  const context={$:node,plannerOrigin:null,autoExcludedIDs:new Set(),tripRequest:0,lastRoute:null,lastTripRequest:null,MAX_SAVED:8,FormData:class{get(key){return node(`[name=${key}]`).value}},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}},destinations:[{id:'public-one'},{id:'public-two'}],saved:new Set(['public-one']),itemID:p=>p.id,notify(){},persist(){},renderSaved(){},renderPlaceResults(){},getJSON:async()=>({status:'ok',data_mode:'reference',selection_mode:'manual',stops:[]}),renderRoute:result=>rendered.push(result),setTimeout(){}};
  context.window={JejuLocationContext:{get:()=>null},dispatchEvent:e=>dispatched.push(e),addEventListener:(type,fn)=>{if(!events.has(type))events.set(type,[]);events.get(type).push(fn)}};
  vm.createContext(context);
  vm.runInContext(fragment('function updatePlanningMode()','// V15 planner origin'),context);
  vm.runInContext(fragment('function plannerValidPoint(','// End V15 planner origin.'),context);
  vm.runInContext(fragment('function toggleSaved(','function openDialog('),context);
  vm.runInContext(fragment('$("#planner-form").addEventListener("submit"','// V3 feature declarations'),context);
  context.initPlannerOrigin();node('#planner-confirm-airport').listeners.click();
  return {context,node,rendered,dispatched};
}
const checks=[];
(async()=>{
  {
    const f=fixture(),origin=f.context.plannerOrigin;f.context.lastRoute={status:'ok',selection_mode:'manual',stops:[{poi_id:'public-one'}]};f.context.lastTripRequest={destination_ids:['public-one']};const version=f.context.tripRequest;
    f.context.toggleSaved('public-one');assert.equal(f.context.saved.size,0);assert.equal(f.context.lastRoute,null);assert.equal(f.context.lastTripRequest,null);assert(f.context.tripRequest>version);assert.equal(f.context.plannerOrigin,origin);assert.equal(f.dispatched.at(-1).detail,null);
    f.context.lastRoute={status:'ok',selection_mode:'manual'};f.context.toggleSaved('public-two');assert(f.context.saved.has('public-two'));assert.equal(f.context.lastRoute,null);
    checks.push('removing or adding a saved place invalidates the saved-place route without losing the confirmed origin');
  }
  {
    const f=fixture(),route={status:'ok',selection_mode:'manual'};f.context.lastRoute=route;const version=f.context.tripRequest;
    f.context.toggleSaved('unknown-id');assert.equal(f.context.lastRoute,route);assert.equal(f.context.tripRequest,version);
    f.context.saved=new Set(Array.from({length:8},(_,i)=>'kept-'+i));f.context.toggleSaved('public-two');assert.equal(f.context.lastRoute,route);assert.equal(f.context.tripRequest,version);assert.equal(f.context.saved.size,8);
    checks.push('unknown places and capacity-rejected additions do not discard a valid route');
  }
  {
    const f=fixture();let finish;f.context.getJSON=()=>new Promise(resolve=>finish=resolve);
    const pending=f.node('#planner-form').listeners.submit({preventDefault(){}});assert.equal(f.node('#create-trip').disabled,true);f.context.toggleSaved('public-one');assert.equal(f.node('#create-trip').disabled,false);finish({status:'ok',data_mode:'reference',selection_mode:'manual',stops:[{poi_id:'public-one'}]});await pending;
    assert.equal(f.rendered.length,0);assert.equal(f.context.lastRoute,null);
    checks.push('a late saved-place API response is suppressed when its selected places change');
  }
  {
    const f=fixture();f.node('#route-mode-auto').checked=true;f.node('#route-mode-saved').checked=false;
    const route={status:'ok',selection_mode:'automatic'};f.context.lastRoute=route;f.context.lastTripRequest={query:'해변'};const version=f.context.tripRequest;
    f.context.toggleSaved('public-two');assert.equal(f.context.lastRoute,route);assert.equal(f.context.tripRequest,version);
    let finish;f.context.getJSON=()=>new Promise(resolve=>finish=resolve);const pending=f.node('#planner-form').listeners.submit({preventDefault(){}});f.context.toggleSaved('public-one');finish({status:'ok',data_mode:'reference',selection_mode:'automatic',stops:[]});await pending;assert.equal(f.rendered.length,1);
    checks.push('independent saved-list edits preserve both existing and pending automatic recommendations');
  }
  {
    const f=fixture();f.node('#route-mode-auto').checked=true;f.node('#route-mode-saved').checked=false;
    vm.runInContext(source.slice(source.indexOf('window.JejuTripBridge={')),f.context);let finish;
    f.context.fetch=()=>new Promise(resolve=>finish=resolve);const pending=f.context.window.JejuTripBridge.createMapRoute();f.context.toggleSaved('public-one');finish({ok:true,json:async()=>({status:'ok',data_mode:'reference',selection_mode:'manual',stops:[{poi_id:'public-one'}]})});
    await assert.rejects(pending,/조건이 바뀌어/);assert.equal(f.rendered.length,0);
    checks.push('a map-started saved-place request is invalidated even while the automatic radio option is selected');
  }
  {
    const f=fixture();f.node('#route-mode-auto').checked=true;f.context.autoExcludedIDs.add('public-one');f.context.lastRoute={status:'ok',selection_mode:'automatic'};
    let finish;f.context.getJSON=()=>new Promise(resolve=>finish=resolve);const pending=f.node('#planner-form').listeners.submit({preventDefault(){}});
    f.node('#auto-route-query').value='박물관';f.node('#auto-route-query').listeners.input();assert.equal(f.context.lastRoute,null);assert.equal(f.context.autoExcludedIDs.size,0);assert.equal(f.node('#create-trip').disabled,false);
    finish({status:'ok',data_mode:'reference',selection_mode:'automatic',stops:[]});await pending;assert.equal(f.rendered.length,0);
    checks.push('typing a new theme immediately removes the old result and suppresses a late automatic response');
  }
  {
    const f=fixture();Object.assign(f.context,{escapeHTML,URL,won:String,clock:String,icon:()=>''});f.context.window.JejuPages={reveal(){}};
    vm.runInContext(fragment('function renderRoute(','function updatePlanningMode('),f.context);
    f.context.renderRoute({status:'needs_clarification',data_mode:'reference',selection_mode:'automatic',stops:[],message:'검색 조건 확인',suggestions:['해변 <script>alert(1)</script> 대신 박물관을 선택해 주세요',null,{},''],trace:[{agent:'검색 조건',status:'needs_clarification'}]});
    let html=f.node('#trip-result').innerHTML;assert(html.includes('조건 조정 안내'));assert(html.includes('이렇게 바꿔 보세요'));assert(html.includes('박물관을 선택해 주세요'));assert(html.includes('&lt;script&gt;'));assert(!html.includes('<script>'));assert(!html.includes('[object Object]'));assert(!html.includes('data-download-trip'));assert(html.includes('검색 조건 확인 필요'));
    f.context.renderRoute({status:'ok',data_mode:'reference',selection_mode:'manual',stops:[{poi_id:'public-one',name:'공개 관광지',arrival_minute:600,departure_minute:690,stay_minutes:90,travel_minutes:10}],totals:{},selected_place_evidence:[{id:'public-one',warnings:['명칭 안내 <img>'],sources:[{name:'공식 소개',url:'https://www.visitjeju.net/kr/detail/view?contentsid=PUBLIC',checked_at:'2026-10-29'}]}]});
    html=f.node('#trip-result').innerHTML;assert(html.includes('명칭 안내 &lt;img&gt;'));assert(html.includes('<details class="route-proof">'));assert(html.indexOf('명칭 안내 &lt;img&gt;')<html.indexOf('<details class="route-proof">'));assert(!html.includes('<details class="route-proof" open'));assert(html.includes('visitjeju.net'));assert(html.includes('2026-10-29'));assert(!html.includes('data-exclude-route='));assert(html.includes('data-download-trip'));
    f.context.renderRoute({status:'needs_review',data_mode:'reference',selection_mode:'manual',stops:[],suggestions:['공식 원문의 방문 조건을 확인해 주세요'],exclusions:[{name:'검토 장소',reasons:[{message:'접근 제한 <script>'}],trust:{warnings:['별도 확인 <img>'],sources:[{name:'공식 원문',url:'https://www.visitjeju.net/kr/detail/view?contentsid=REVIEW',checked_at:'2026-10-29',date_kind:'guide_review'},{name:'장소 명부',url:'https://www.jejudatahub.net/data/view/data/1349',checked_at:'2026-10-28 <img>',date_kind:'source_snapshot'},{name:'위험 URL',url:'javascript:alert(1)'}]}}],trace:[{agent:'방문 조건',status:'needs_review'}]});
    html=f.node('#trip-result').innerHTML;assert(html.includes('방문 조건을 먼저 확인'));assert(html.includes('방문 조건 확인 필요'));assert(html.includes('접근 제한 &lt;script&gt;'));assert(html.includes('별도 확인 &lt;img&gt;'));assert(html.includes('contentsid=REVIEW'));assert(html.includes('공식 소개 확인일 2026-10-29'));assert(html.includes('자료 기준·확인일 2026-10-28 &lt;img&gt;'));assert(!html.includes('<img>'));assert(!html.includes('javascript:'));assert(!html.includes('data-download-trip'));
    f.context.renderRoute({status:'ok',data_mode:'reference',selection_mode:'manual',stops:[{poi_id:'public-one',name:'공개 장소 1'},{poi_id:'public-two',name:'공개 장소 2'}],totals:{},selected_place_evidence:[{id:'public-one',warnings:['공통 확인 문구','첫 장소 주의'],sources:[]},{id:'public-two',warnings:['공통 확인 문구','둘째 장소 주의'],sources:[]}]});
    html=f.node('#trip-result').innerHTML;assert.equal((html.match(/공통 확인 문구/g)||[]).length,1);assert(html.includes('첫 장소 주의'));assert(html.includes('둘째 장소 주의'));assert(html.includes('모든 방문 장소에 공통으로 확인할 내용'));
    checks.push('recovery advice and manual trust evidence remain visible and escaped; review/clarification results cannot be exported as successful routes');
  }
  console.log(JSON.stringify({passed:true,checks,real_gps_requested:false,external_network:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
