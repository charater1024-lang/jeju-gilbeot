'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ui/assistant.js'), 'utf8');

class Node {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.textContent = '';
    this.value = '';
    this.dataset = {};
    this.listeners = {};
    this.attributes = {};
  }
  get childElementCount() { return this.children.length; }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  focus() {}
  fire(type) { return this.listeners[type]?.({preventDefault() {}}); }
  descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
  querySelectorAll(selector) {
    if (selector === '[data-assistant-example]') return this.descendants().filter(child => child.dataset.assistantExample);
    if (selector === '[data-assistant-action]') return this.descendants().filter(child => child.dataset.assistantAction);
    return [];
  }
}

function fixture() {
  const ids = ['assistant', 'assistant-form', 'assistant-message', 'assistant-send', 'assistant-clear', 'assistant-status', 'assistant-response'];
  const nodes = Object.fromEntries(ids.map(id => [id, new Node(id)]));
  const example = new Node('button');
  example.dataset.assistantExample = '제주공항에서 오전 10시에 차로 출발해서 3시간 안에 돌아오고 싶어요.';
  nodes.assistant.append(example);
  nodes['assistant-form'].reset = () => { nodes['assistant-message'].value = ''; };
  const requests = [];
  const responses = [];
  const events = {};
  let plannerReads = 0;
  const window = {
    addEventListener(type, handler) { events[type] = handler; },
    JejuTripBridge: {getConfirmedOrigin() {
      plannerReads += 1;
      return {origin_confirmed: true, origin_source: 'landmark', origin_label: '확인한 공개 지점', start_lat: 33.503, start_lon: 126.492};
    }}
  };
  const context = {
    document: {getElementById: id => nodes[id], createElement: tag => new Node(tag)},
    window, AbortController, URL, setTimeout, clearTimeout,
    async fetch(url, options) {
      assert.equal(url, '/api/assistant');
      requests.push({body: JSON.parse(options.body), signal: options.signal});
      const data = await responses.shift();
      return {ok: true, async json() { return data; }};
    }
  };
  vm.runInNewContext(source, context, {filename: 'assistant.js'});
  const result = nodes['assistant-response'];
  return {
    nodes, example, requests, responses, events, result,
    get plannerReads() { return plannerReads; },
    async submit(text) {
      nodes['assistant-message'].value = text;
      return nodes['assistant-form'].fire('submit');
    },
    async click(label) {
      const button = result.descendants().find(item => item.tagName === 'button' && item.textContent.includes(label));
      assert(button, `missing button ${label}`);
      return button.fire('click');
    },
    text() { return [nodes['assistant-status'], ...result.descendants()].map(item => item.textContent).join(' '); }
  };
}

async function main() {
  const airport = fixture();
  airport.example.fire('click');
  assert.equal(airport.requests.length, 0);
  assert.match(airport.nodes['assistant-message'].value, /제주공항/);
  airport.responses.push({status: 'needs_confirmation', message: '출발지를 확인하세요.', state: 'opaque-preview', origin_candidate: {label: '제주공항'}, conditions: {'출발 시각': '10:00', '복귀 시각': '13:00'}});
  await airport.nodes['assistant-form'].fire('submit');
  assert.deepEqual(Object.keys(airport.requests[0].body), ['message']);
  assert.match(airport.text(), /13:00/);
  airport.responses.push({status: 'ok', state: 'opaque-confirmed', route: {
    status: 'ok', data_mode: 'reference', stops: [{name: '제주목 관아', arrival_minute: 625, departure_minute: 650}],
    totals: {duration_minutes: 95, end_arrival_minute: 695}
  }});
  await airport.click('제주공항 출발로 확인');
  assert.deepEqual(airport.requests[1].body, {action: 'confirm', origin_choice: 'candidate', state: 'opaque-preview'});
  assert.match(airport.text(), /제주목 관아/);
  assert.match(airport.text(), /복귀 11:35/);
  assert(!airport.text().includes('opaque-confirmed'));
  airport.responses.push({status: 'ok', state: 'opaque-confirmed', alternatives: [{label: '한 곳 줄이기', condition_change: '최대 2곳', route: {status: 'infeasible', message: '조건을 확인해 주세요.'}}]});
  await airport.click('대안 비교');
  assert.deepEqual(airport.requests[2].body, {action: 'alternatives', origin_choice: 'candidate', state: 'opaque-confirmed'});
  assert.match(airport.text(), /한 곳 줄이기/);
  airport.responses.push({status: 'needs_confirmation', state: 'opaque-revision', conditions: {'방문 장소': '최대 2곳'}});
  await airport.submit('한 곳만 줄여줘');
  assert.equal(airport.requests[3].body.state, 'opaque-confirmed');
  assert.match(airport.text(), /최대 2곳/);

  const planner = fixture();
  planner.responses.push({status: 'needs_confirmation', state: 'opaque-planner', conditions: {'출발 시각': '09:00'}});
  await planner.submit('오전 9시부터 걷는 코스');
  assert.equal(planner.plannerReads, 0);
  planner.responses.push({status: 'infeasible', state: 'opaque-confirmed', route: {data_mode: 'reference', status: 'infeasible', message: '시간이 짧아요.'}});
  await planner.click('일정에서 확인한 출발지');
  assert.equal(planner.plannerReads, 1);
  assert.equal(planner.requests[1].body.origin.start_lat, 33.503);
  assert(!planner.text().includes('33.503'));
  planner.events['jeju:planneroriginchange']();
  assert(planner.result.hidden);

  const search = fixture();
  search.responses.push({status: 'ok', places: [{
    name: '<img src=x onerror=alert(1)>', kind: 'food', address: '명부 주소', location_basis: 'address_only',
    primary_source: {name: '제주데이터허브', url: 'https://www.jejudatahub.net/data/view/data/780', source_date: '2026-10-29'},
    matched_evidence: {text: '<script>unsafe()</script>', source_url: 'javascript:alert(1)', source_name: '문서'}
  }]});
  await search.submit('음식점 찾아줘');
  assert.match(search.text(), /제주데이터허브/);
  assert.match(search.text(), /2026-10-29/);
  assert.equal(search.result.descendants().filter(node => node.tagName === 'a').length, 1);
  assert(search.result.descendants().some(node => node.tagName === 'h4' && node.textContent.includes('<img')));
  assert(!search.result.descendants().some(node => node.tagName === 'img' || node.tagName === 'script'));
  const proof = search.result.descendants().find(node => node.tagName === 'details');
  assert(proof && proof.open === false, 'source evidence starts collapsed');
  assert(search.result.descendants().some(node => node.tagName === 'p' && node.textContent.includes('자료 기준 2026-10-29')), 'source date remains visible outside source details');
  search.responses.push({status: 'ok', analysis: {title: '제주 소비 비중', columns: ['업종', '비중'], rows: [['분류', '표의 값']], notes: ['과거 집계 범위']}});
  await search.submit('소비 비중');
  assert(search.result.descendants().some(node => node.tagName === 'th' && node.textContent === '비중'));
  assert.match(search.text(), /과거 집계 범위/);

  const compact = fixture();
  compact.responses.push({status:'ok', analysis:{title:'모델 평가 비교', columns:['항목','값'],
    rows:Array.from({length:12},(_,i)=>[`업종${i+1}`,`${i+1}%`]),
    notes:['관측 기간 2019~2024','일반 설명1','일반 설명2','일반 설명3','일반 설명4','일반 설명5','일반 설명6','일반 설명7','일반 설명8', '관측값 ±20% 이내 · 13200/28092건 · 47.0%'],
    sources:[{name:'허브561',url:'https://www.jejudatahub.net/data/view/data/561'}]}});
  await compact.submit('모델 평가 비교');
  const records = compact.result.descendants().filter(node=>node.tagName==='tr' && node.children.some(child=>child.tagName==='td'));
  assert.equal(records.length,12);
  assert.equal(records.filter(node=>!node.hidden).length,5,'analysis shows five rows first');
  assert(compact.result.descendants().some(node=>node.tagName==='li' && node.textContent.includes('47.0%')), 'performance metrics after eighth note are preserved');
  const metricContainer = compact.result.descendants().find(node=>node.tagName==='ul' && node.children.some(child=>child.textContent.includes('47.0%')));
  assert(compact.result.descendants().find(node=>node.tagName==='section').children.includes(metricContainer),'critical evaluation metric stays outside collapsed disclosure');
  await compact.click('12행 전체 보기');
  assert.equal(records.filter(node=>!node.hidden).length,12);
  await compact.click('5행만 보기');
  assert.equal(records.filter(node=>!node.hidden).length,5);
  assert(compact.result.descendants().filter(node=>node.tagName==='details').every(node=>node.open===false));

  const cards = fixture();
  cards.responses.push({status:'ok',places:Array.from({length:5},(_,i)=>({name:`장소${i+1}`,kind:'food',address:'실제 명부 주소',location_basis:'address_only',
    primary_source:{name:'제주데이터허브',url:'https://www.jejudatahub.net/data/view/data/780',source_date:'2022-09-30'},
    matched_evidence:{text:'긴 원자료 소개 설명',source_url:'https://www.jejudatahub.net/data/view/data/780'},
    limitations:['현재 영업 여부 미확인']}))});
  await cards.submit('음식점 기록');
  const entries=cards.result.descendants().filter(node=>node.tagName==='article');
  assert.equal(entries.filter(node=>!node.hidden).length,3,'place search shows three cards first');
  assert(entries.slice(0,3).every(node=>node.children.some(child=>child.tagName==='ul' && child.children.some(note=>note.textContent.includes('현재 영업')))),'current operation warnings remain visible');
  await cards.click('5개 전체 보기');
  assert.equal(entries.filter(node=>!node.hidden).length,5);
  await cards.click('3개만 보기');
  assert.equal(entries.filter(node=>!node.hidden).length,3);

  const evidence = fixture();
  evidence.responses.push({status:'ok',analysis:{title:'걷기 코스',columns:['이름','근거'],rows:[['가파도', '기록 원문 '.repeat(45)+'확인 필요 · 소요시간에 배편과 복귀는 포함하지 않음']],notes:['올레는 2021년 19코스만 수록합니다.']}});
  await evidence.submit('걷기 기록');
  const cells=evidence.result.descendants().filter(node=>node.tagName==='td');
  assert(cells[1].children.some(node=>node.tagName==='details' && node.open===false),'raw table evidence starts collapsed');
  assert(cells[1].children.some(node=>node.tagName==='p' && node.textContent.includes('배편')),'ferry warning remains visible before raw evidence');

  const stale = fixture();
  let reply;
  stale.responses.push(new Promise(resolve => { reply = resolve; }));
  const inFlight = stale.submit('새 일정');
  stale.events['jeju:reset']();
  assert(stale.requests[0].signal.aborted);
  reply({status: 'ok', message: '늦은 결과', state: 'stale-state'});
  await inFlight;
  assert(!stale.text().includes('늦은 결과'));
  stale.responses.push({status: 'needs_input', message: '조건을 알려주세요.'});
  await stale.submit('다시 확인');
  assert(!('state' in stale.requests[1].body));
  console.log(JSON.stringify({passed: true, checks: ['explicit public and planner confirmation', 'same-session revision and alternative request', 'safe evidence and analysis rendering', 'five-row preview and reversible expand', 'three-card preview and reversible expand', 'closed evidence with dates warnings and performance visible', 'reset drops late replies and state']}));
}

main().catch(error => { console.error(error); process.exitCode = 1; });
