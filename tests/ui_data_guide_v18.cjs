'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');
class Node {
  constructor(tag) { this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.textContent='';this.value='';this.attributes={};this.open=false;this.hidden=false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children=[]; }
  setAttribute(key,value) { this.attributes[key]=value; }
  addEventListener(type,handler) { this.listeners[type]=handler; }
  fire(type) { return this.listeners[type]?.({preventDefault(){}}); }
  all() { return this.children.flatMap(child=>[child,...child.all()]); }
  visible() { return this.hidden?[]:[this,...this.children.flatMap(child=>this.tagName==='details'&&!this.open&&child.tagName!=='summary'?[]:child.visible())]; }
}
function fixture(foodBridge) {
  const ids=['data-guide-form','guide-query','guide-date','guide-month','guide-duration','guide-result','guide-status','guide-submit','guide-date-field','guide-month-field','guide-duration-field','guide-query-label','guide-scope'];
  const nodes=Object.fromEntries(ids.map(id=>[id,new Node(id)]));
  const tabs=['route','dining','walk','beach','accessible','amenity'].map(kind=>{const tab=new Node('button');tab.dataset.guideKind=kind;return tab;});
  const requests=[],responses=[],events={};
  const context={document:{getElementById:id=>nodes[id],createElement:tag=>new Node(tag),querySelectorAll:()=>tabs},window:{addEventListener:(type,handler)=>{events[type]=handler;}},
    Date,Intl,URL,URLSearchParams,AbortController,setTimeout,clearTimeout,fetch:async(url,options)=>{requests.push({url,options});const data=await responses.shift();return {ok:true,json:async()=>data};}};
  if (foodBridge) context.window.JejuExplore=foodBridge;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../ui/data-guide.js'),'utf8'),context);
  return {nodes,tabs,requests,responses,events,dataGuide:context.window.JejuDataGuide,select:kind=>tabs.find(tab=>tab.dataset.guideKind===kind).fire('click'),submit:()=>nodes['data-guide-form'].fire('submit'),text:()=>nodes['guide-result'].all().map(node=>node.textContent).join(' ')};
}
async function main() {
  const f=fixture();
  assert.equal(f.requests.length,0,'do not predict before explicit submit');
  assert.match(f.nodes['guide-date'].value,/^\d{4}-\d{2}-\d{2}$/);
  f.responses.push({title:'노선',columns:['코드','승차'],rows:[['202-14','59.9명']],metrics:[{label:'관측값±20% 이내',value:'47.0%'}],notes:['과거 자료'],sources:[{name:'실제자료',url:'javascript:alert(1)'}]});
  await f.submit();assert.match(f.requests[0].url,/kind=route/);assert.match(f.text(),/47.0%/);
  assert(!f.nodes['guide-result'].all().some(node=>node.href?.startsWith('javascript:')));
  f.select('walk');f.nodes['guide-duration'].value='120';
  f.responses.push({title:'걷기',columns:['이름'],rows:[['가파도']],notes:['배편 제외']});await f.submit();
  assert.match(f.requests[1].url,/max_minutes=120/);assert.match(f.text(),/배편 제외/);
  f.select('beach');f.responses.push({title:'해변',columns:['이름'],rows:[['협재']]});await f.submit();
  assert(!f.requests[2].url.includes('max_minutes'));
  assert.match(f.text(),/협재/);
  f.select('dining');f.nodes['guide-month'].value='6';
  f.responses.push({title:'업종',columns:['이름'],rows:[['<script>unsafe()</script>']]});await f.submit();
  assert.match(f.requests[3].url,/month=6/);assert(f.text().includes('<script>unsafe()</script>'));
  assert(!f.nodes['guide-result'].all().some(node=>node.tagName==='script'));
  let finish;
  f.responses.push(new Promise(resolve=>{finish=resolve;}));const loading=f.submit();
  assert(f.nodes['guide-submit'].disabled);f.select('amenity');assert(!f.nodes['guide-submit'].disabled);
  finish({title:'old',columns:['old'],rows:[['OLD RESPONSE']]});await loading;
  assert(!f.text().includes('OLD RESPONSE'));
  f.responses.push({title:'새 결과',columns:['이름'],rows:[['주차장']]});await f.submit();
  f.nodes['guide-query'].fire('input');assert.equal(f.text(),'');
  f.events.pagehide();
  const compact=fixture();
  compact.responses.push({title:'요약',columns:['코드','승차'],rows:Array.from({length:12},(_,i)=>['202-'+i,i+'명']),
    metrics:[{label:'평균오차',value:'4.9명'},{label:'WAPE',value:'26.9%'},{label:'±20% 이내 · 13200/28092건',value:'47.0%'},{label:'오차 감소',value:'6.4%'}],
    notes:['학습 원자료 관측 기간 2019-01-01 ~ 2025-10-19','평가는 250개 코드로 전체 관측 셀의 43.7%를 포함합니다.','긴 기술 설명'],sources:[{name:'원본',url:'https://www.jejudatahub.net/data/view/data/561'}]});
  await compact.submit();
  const getRows=()=>compact.nodes['guide-result'].all().filter(node=>node.tagName==='tbody')[0].children;
  const getVisible=()=>compact.nodes['guide-result'].visible().map(node=>node.textContent).join(' ');
  assert.equal(getRows().filter(row=>!row.hidden).length,5,'default only five records');
  assert(getVisible().includes('47.0%'),'low tolerance-hit rate stays visible');
  assert(getVisible().includes('13200/28092'),'metric denominator stays visible');
  assert(getVisible().includes('43.7%'),'evaluation coverage stays visible');
  assert(getVisible().includes('2019-01-01'),'observed period stays visible');
  assert(!getVisible().includes('긴 기술 설명'),'long methodology is collapsed');
  assert(!getVisible().includes('WAPE'),'secondary metric is collapsed');
  const more=compact.nodes['guide-result'].all().find(node=>node.tagName==='button'&&node.textContent.includes('나머지'));
  assert.equal(more.attributes['aria-expanded'],'false');more.fire('click');
  assert.equal(getRows().filter(row=>!row.hidden).length,12);assert.equal(more.attributes['aria-expanded'],'true');
  more.fire('click');assert.equal(getRows().filter(row=>!row.hidden).length,5);
  assert(compact.nodes['guide-result'].all().filter(node=>node.tagName==='details').every(node=>!node.open));
  compact.select('walk');compact.responses.push({title:'걷기',columns:['코스·시설','기록된 항목','자료 기준일','설명과 확인할 내용'],
    rows:[['가파도','코스번호 · 10-1\n거리(km) · 4.2\n제공 소요시간 · 1~2시간\n시작점 · 상동포구','2021-11-02','원문상세 좌표 및 확인사항']],
    notes:['올레는 2021년 공개 미리보기 19코스만 포함합니다. 전 코스 목록이 아닙니다.','시간 제한은 이동·복귀·배편을 포함하지 않습니다.'],
    sources:[{name:'올레',url:'https://www.jejudatahub.net/data/view/data/871',source_date:'2021-11-02'}]});
  await compact.submit();
  assert(getVisible().includes('19코스'),'partial coverage remains visible');
  assert(getVisible().includes('배편'),'ferry exclusion remains visible');
  assert(getVisible().includes('1~2시간'),'provided course duration remains visible');
  assert(getVisible().includes('2021-11-02'),'record date remains visible');
  assert(!getVisible().includes('원문상세 좌표'),'raw record evidence stays behind a closed disclosure');
  assert(compact.text().includes('원문상세 좌표'),'evidence is preserved in DOM');
  compact.select('walk');compact.responses.push({status:'unsupported',title:'조건 확인',rows:[],columns:[],empty_message:'최소시간 조건은 지원하지 않습니다.'});
  await compact.submit();assert(getVisible().includes('최소시간 조건은 지원하지 않습니다.'));
  const foodTasks=[];
  const linked=fixture({searchFoodFromQuery:word=>{foodTasks.push(word);return true;}});
  linked.select('dining');linked.nodes['guide-month'].value='6';
  linked.responses.push({title:'6월 외식',columns:['세부 업종','중분류','추정 구성비'],rows:[['커피전문점','커피/음료','22.5%']],notes:['관측 기간 2019~2024']});
  await linked.submit();
  assert.equal(foodTasks.length,0,'analysis results never auto-search places');
  const action=linked.nodes['guide-result'].all().find(node=>node.tagName==='button'&&node.textContent==='관련 음식점 찾기');
  assert(action);assert.equal(action.attributes['aria-label'],'커피전문점 관련 음식점 찾기');action.fire('click');
  assert.deepEqual(foodTasks,['커피']);assert(linked.nodes['guide-status'].textContent.includes('개별 음식점'));
  assert(linked.text().includes('22.5%'),'place exploration does not rewrite the model estimate');
  const unavailable=fixture();unavailable.select('dining');
  unavailable.responses.push({title:'외식',columns:['세부 업종'],rows:[['일반한식/백반']]});await unavailable.submit();
  unavailable.nodes['guide-result'].all().find(node=>node.tagName==='button'&&node.textContent==='관련 음식점 찾기').fire('click');
  assert(unavailable.nodes['guide-status'].textContent.includes('직접 입력'));
  const task=fixture();task.select('walk');task.nodes['guide-month'].value='6';
  assert.equal(task.dataGuide.openDining(),true);assert.equal(task.requests.length,0,'opening the dining task never predicts without submission');
  task.nodes['guide-query'].value='커피';task.responses.push({title:'다시 외식',columns:['세부 업종'],rows:[['커피전문점']]});await task.submit();
  assert.match(task.requests[0].url,/kind=dining/);assert.match(task.requests[0].url,/month=6/);
  task.dataGuide.openDining();assert.equal(task.nodes['guide-query'].value,'커피');assert(task.text().includes('커피전문점'),'reopening the same task preserves the current result');
  console.log('PASS data guide explicit calls, kind filters, source safety, metrics, cancellation, late responses, task selection and optional food exploration actions');
  console.log('PASS five-row disclosure, expandable results, closed evidence and secondary metrics, visible freshness/coverage/tolerance/ferry scope');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
