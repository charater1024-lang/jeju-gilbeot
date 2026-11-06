// Public-place fixtures and a mocked UI only; no GPS, browser, or network.
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../ui/app.js','utf8');
const html=fs.readFileSync(__dirname+'/../ui/index.html','utf8');
function fragment(start,end){const a=source.indexOf(start),b=source.indexOf(end,a+start.length);assert(a>=0&&b>a);return source.slice(a,b);}
const escapeHTML=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nodes=new Map(),notices=[],events=[];
function node(selector){if(!nodes.has(selector))nodes.set(selector,{hidden:true,innerHTML:'',textContent:'',insertAdjacentHTML(_,value){this.innerHTML+=value},scrollIntoView(){},querySelector(){return node(selector+' span')},addEventListener(type,fn){this[type]=fn}});return nodes.get(selector);}
const context={$:node,lastRoute:null,notify:message=>notices.push(message),escapeHTML,won:v=>String(v),clock:v=>String(v),icon:()=>'',window:{dispatchEvent:e=>events.push(e),JejuPages:{reveal(){}}},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}}};
vm.createContext(context);vm.runInContext(fragment('function renderRoute(','function updatePlanningMode('),context);
context.renderRoute({status:'ok',data_mode:'synthetic',stops:[{name:'must not be displayed'}]});
assert.equal(context.lastRoute,null);assert.equal(events.length,0);assert.equal(notices.length,1);assert.equal(node('#trip-result').innerHTML,'');
context.renderRoute({status:'ok',data_mode:'reference',stops:[{name:'성산일출봉 <script>',arrival_minute:600,departure_minute:660,stay_minutes:60,travel_minutes:30,cost_unknown:true}],totals:{travel_cost_krw:3000,duration_minutes:120,end_arrival_minute:720}});
assert.equal(events.length,1);assert(node('#trip-result').innerHTML.includes('성산일출봉 &lt;script&gt;'));assert(node('#trip-result').innerHTML.includes('data-download-trip'));
assert(!html.includes('name="planning_mode"'));assert(!html.includes('name="avoid_crowds"'));assert(!html.includes('name="interests"'));

const profile={$:node,escapeHTML,periodLabel:()=> '2018.01–2025.06',audience:'tourist'};
vm.createContext(profile);vm.runInContext(fragment('function renderFoodProfile(','async function loadRestaurants('),profile);
profile.renderFoodProfile({model:{selected_serving_model:'recency_weighted_seasonal_ridge',monthly_periodicity:true},categories:[{name:'한식',share:0.5}],observation_period:{}});
assert.equal(node('.food-month-label').hidden,false);assert.equal(node('#food-month').disabled,false);assert(node('#food-insight-summary').innerHTML.includes('최근 실측 자료'));assert(node('#food-category-chips').innerHTML.includes('50.0%'));
profile.renderFoodProfile({model:{selected_serving_model:'audience_mean',monthly_periodicity:false},categories:[]});assert.equal(node('.food-month-label').hidden,true);
const discovery=fs.readFileSync(__dirname+'/../ui/discovery.js','utf8');
const metricStart=discovery.indexOf('  function modelMetricText('),metricEnd=discovery.indexOf('  async function loadModels(',metricStart);
const metrics={};vm.createContext(metrics);vm.runInContext(discovery.slice(metricStart,metricEnd),metrics);
assert(metrics.modelMetricText({mae_share:0.00426111}).includes('0.426%p'));
assert(metrics.modelMetricText({mae_per_hour:80.9194,wape_bucket_counts:0.133081}).includes('13.31%'));

(async()=>{
  const audienceMetrics=JSON.parse(fs.readFileSync(__dirname+'/../models_audience/audience_metrics.json','utf8'));
  const mobilityMetrics=JSON.parse(fs.readFileSync(__dirname+'/../models_mobility/mobility_metrics.json','utf8'));
  const cards=[{id:'audience_distribution',title:'소비',available:true,metrics:{selected_test:audienceMetrics.test.model},split:audienceMetrics.split},{id:'mobility_pattern',title:'승차',available:true,metrics:{selected_test:mobilityMetrics.test.model},split:mobilityMetrics.split},{id:'synthetic_demo',title:'SHOULD_NOT_APPEAR'}];
  const modelUI={$:node,escape:escapeHTML,fetch:async()=>({ok:true,json:async()=>({cards})})};
  vm.createContext(modelUI);vm.runInContext(discovery.slice(metricStart,discovery.indexOf('  async function routeFor(',metricStart)),modelUI);
  await modelUI.loadModels();const cardsHTML=node('#model-cards').innerHTML;
  assert(cardsHTML.includes((audienceMetrics.test.model.mae_share*100).toFixed(3)+'%p'));
  assert(cardsHTML.includes((mobilityMetrics.test.model.wape_bucket_counts*100).toFixed(2)+'%'));
  assert(cardsHTML.includes('평가 기간'));assert(!cardsHTML.includes('SHOULD_NOT_APPEAR'));
  const calls=[],rendered=[];
  const planner={$:node,formRequest:()=>({start_minute:540,end_minute:1080,max_stops:4}),destinations:[{id:'seongsan'}],saved:new Set(['seongsan']),itemID:p=>p.id,getJSON:async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return {status:'ok',data_mode:'reference',stops:[]}},renderRoute:r=>rendered.push(r),updatePlanningMode(){},tripRequest:0,lastTripRequest:null};
  vm.createContext(planner);vm.runInContext(fragment('function addSavedDestinations(', '// V15 planner origin')+fragment('$("#planner-form").addEventListener("submit"','// V3 feature declarations'),planner);
  await node('#planner-form').submit({preventDefault(){}});
  assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/plan-destinations');assert.deepEqual(calls[0].body.destination_ids,['seongsan']);assert.equal(rendered.length,1);
  planner.saved.clear();await node('#planner-form').submit({preventDefault(){}});assert.equal(calls.length,1);assert.equal(node('#planner-error').hidden,false);
  let downloads=0;
  const exporter={lastRoute:{status:'ok',data_mode:'synthetic',stops:[{name:'not public'}]},notify(){},document:{createElement(){downloads++;return {}}}};
  vm.createContext(exporter);vm.runInContext(fragment('function saveItinerary()','function resetTrip()')+'\nsaveItinerary();',exporter);assert.equal(downloads,0);
  console.log(JSON.stringify({passed:true,checks:['real-only planner UI and fixed real-place endpoint','unverified or historical synthetic route cannot render or export','real route rendering and HTML escaping remain available','empty collection never submits a route','month controls follow the serving model and actual metric JSON renders with correct units and evaluation dates'],real_gps:false,external_network:false}));
})().catch(error=>{console.error(error);process.exitCode=1});
