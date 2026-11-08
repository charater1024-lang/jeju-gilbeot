const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class N{
  constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.value='';this.attrs={};this.listeners={};this.style={setProperty:(k,v)=>this.attrs[k]=v};this.classList={toggle(){}};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,fn){this.listeners[k]=fn;}
}
const ids=['hub-insights','hub-place','hub-audience','hub-visitor-panel','hub-visitor-result','hub-visitor-form','official-guide-query','official-guide-form'];
const nodes=Object.fromEntries(ids.map(id=>[id,new N()]));
nodes['hub-audience'].value='domestic';
const events={},pending=[],requests=[],navigations=[];let guideSubmits=0;
nodes['official-guide-form'].requestSubmit=()=>guideSubmits++;
const context={document:{getElementById:id=>nodes[id],createElement:tag=>new N(tag)},URL,URLSearchParams,Intl,Number,Math,fetch:url=>{requests.push(url);return new Promise(resolve=>pending.push(resolve));},location:{pathname:'/planner'},JejuPages:{navigate:path=>navigations.push(path)},addEventListener:(k,fn)=>events[k]=fn};context.window=context;
vm.runInNewContext(fs.readFileSync(__dirname+'/../ui/hub-insights.js','utf8'),context);
const flatten=node=>[node.textContent||'',...node.children.map(flatten)].join(' ');
const find=(node,predicate)=>predicate(node)?node:node.children.map(child=>find(child,predicate)).find(Boolean);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const answer=(data,ok=true)=>({ok,json:async()=>data});
const visitor=(name='비자림')=>({kind:'visitor',available:true,ml_applied:false,audience:'domestic',period:{start_month:'2009-01',end_month:'2024-12'},places:[{key:name,name}],selected:{key:name,name,monthly_series:[{month:'2024-12',count:0}],seasonality:[{month:1,mean:10,count_years:7}],seasonality_period:{start_month:'2018-01',end_month:'2024-12'},forecast:{available:false}},limitations:['현재 혼잡 아님'],sources:[{id:189,url:'https://www.jejudatahub.net/data/view/data/189'},{id:'unsafe',url:'javascript:alert(1)'}]});
(async()=>{
  assert.equal(requests.length,0,'hidden page does not fetch');
  events['jeju:pagechange']({detail:{path:'/insights'}});assert.equal(requests.length,1);
  nodes['hub-visitor-form'].listeners.submit({preventDefault(){}});assert.equal(requests.length,2);
  pending[1](answer(visitor('새 결과')));await flush();
  pending[0](answer(visitor('오래된 응답')));await flush();
  assert.match(flatten(nodes['hub-visitor-result']),/새 결과/);assert.doesNotMatch(flatten(nodes['hub-visitor-result']),/오래된 응답/);
  assert.match(flatten(nodes['hub-visitor-result']),/0명/,'observed zero remains zero');
  assert.match(flatten(nodes['hub-visitor-result']),/운영 미적용/);
  assert.equal(nodes['hub-visitor-result'].attrs['aria-busy'],'false');
  assert.equal(context.JejuHubInsights.count(null),'관측 없음');assert.equal(context.JejuHubInsights.count(0),'0');
  assert.equal(context.JejuHubInsights.safeSource('https://www.jejudatahub.net/data/view/data/189'),'https://www.jejudatahub.net/data/view/data/189');
  for(const bad of ['javascript:alert(1)','http://www.jejudatahub.net/','https://www.jejudatahub.net.evil.test/'])assert.equal(context.JejuHubInsights.safeSource(bad),null);
  assert.match(flatten(nodes['hub-visitor-result']),/2018-01 — 2024-12/,'calendar period stays explicit');
  events['jeju:pagechange']({detail:{path:'/planner'}});events['jeju:pagechange']({detail:{path:'/insights'}});
  assert.equal(requests.length,2,'returning to a loaded visitor page keeps the selected result');
  const guide=find(nodes['hub-visitor-result'],node=>Boolean(node.dataset.hubGuide));assert.ok(guide);
  nodes['hub-insights'].listeners.click({target:{closest:selector=>selector==='[data-hub-guide]'?guide:null}});
  assert.equal(nodes['official-guide-query'].value,'새 결과');assert.equal(guideSubmits,1);
  assert.deepEqual(navigations,['/planner#official-guide']);
  nodes['hub-place'].value='천지연폭포';nodes['hub-audience'].value='foreign';
  nodes['hub-visitor-form'].listeners.submit({preventDefault(){}});
  assert.equal(new URL(requests[2],'http://127.0.0.1').searchParams.get('place'),'천지연폭포');
  assert.equal(new URL(requests[2],'http://127.0.0.1').searchParams.get('audience'),'foreign');
  pending[2](answer({error:'출처 검증 실패'},false));await flush();
  assert.match(flatten(nodes['hub-visitor-result']),/출처 검증 실패/);assert.doesNotMatch(flatten(nodes['hub-visitor-result']),/새 결과/,'failed validation removes stale results');
  assert.equal(nodes['hub-visitor-result'].attrs['aria-busy'],'false');
  nodes['hub-visitor-form'].listeners.submit({preventDefault(){}});const foreign=visitor('천지연폭포');foreign.audience='foreign';
  pending[3](answer(foreign));await flush();assert.match(flatten(nodes['hub-visitor-result']),/천지연폭포/);assert.match(flatten(nodes['hub-visitor-result']),/외국인/);
  nodes['hub-visitor-form'].listeners.submit({preventDefault(){}});pending[4](answer({kind:'regional',available:true,selected:{key:'지역',name:'지역'}}));await flush();
  assert.match(flatten(nodes['hub-visitor-result']),/이 자료를 지금 확인할 수 없습니다/,'other data kinds cannot appear in the visitor page');
  assert.ok(requests.every(url=>new URL(url,'http://127.0.0.1').pathname==='/api/hub-visitor-patterns'),'only visitor data is requested');
  const html=fs.readFileSync(__dirname+'/../ui/index.html','utf8');const start=html.indexOf('<section data-page="/insights"');const section=html.slice(start,html.indexOf('</section>',start));
  assert.match(section,/hub-visitor-form/);assert.doesNotMatch(section,/hub-regional|hub-region|data-hub-tab|지역 먹거리 비교|소비패턴/,'retired regional controls are absent');
  console.log(JSON.stringify({pass:true,checks:['visitor-only lazy page','latest response wins','observed zero and missing differ','ML non-adoption and calendar period visible','source protocol and host allowlist','exact place and audience filters','official-guide transition','error recovery and response kind guard','no regional API or controls','no GPS or remote runtime calls']}));
})().catch(err=>{console.error(err);process.exitCode=1;});
