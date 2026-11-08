'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '../ui/official-guide.js'), 'utf8');

class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.events = {}; this.dataset = {};
    this.textContent = ''; this.value = ''; this.checked = false;
    this.disabled = false; this.isConnected = true;
  }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  replaceChildren() {
    const detach = node => { node.isConnected = false; node.children.forEach(detach); };
    this.children.forEach(detach); this.children = [];
  }
  addEventListener(type, handler) { this.events[type] = handler; }
  contains(node) { return this === node || this.children.some(child => child.contains(node)); }
  closest() { return this.dataset.guideExample ? this : this.parent?.closest() || null; }
  focus() { this.focused = true; }
  all() { return [this, ...this.children.flatMap(node => node.all())]; }
}

function fixture() {
  const ids = Object.fromEntries(['official-guide-form','official-guide-query','official-guide-submit',
    'official-guide-status','official-guide-results','official-guide-examples','official-guide-semantic']
    .map(id => [id, new Element(id)]));
  const input = ids['official-guide-query'], toggle = ids['official-guide-semantic'];
  const results = ids['official-guide-results'], submit = ids['official-guide-submit'];
  ids['official-guide-form'].reset = () => { input.value = ''; };
  const examples = ['해안','화산','전통 가옥','제주목관아'].map(query => {
    const button = new Element('button'); button.dataset.guideExample = query; return button;
  });
  ids['official-guide-examples'].append(...examples);
  const events = {}, requests = [], queue = [];
  const context = {
    AbortController, URL, URLSearchParams,
    document: {getElementById: id => ids[id], createElement: tag => new Element(tag)},
    addEventListener: (name, handler) => { events[name] = handler; },
    fetch: async (url, options) => {
      assert(['/api/guide-search','/api/semantic-guide-search'].includes(url), 'search must stay local');
      assert.equal(options.method, 'POST');
      const body = JSON.parse(options.body);
      assert.deepEqual(Object.keys(body).sort(), ['query','region']);
      assert.equal(body.region, 'all');
      requests.push({url, body, options});
      assert(queue.length, 'each request must have an explicit test response');
      const answer = queue.shift();
      if (answer instanceof Error) throw answer;
      if (answer && typeof answer.then === 'function') return answer;
      return answer;
    },
    JejuTripBridge: {openPlace() {}, addPlace() { throw new Error('search must not save automatically'); }},
    JejuExplore: {showPlaces() { throw new Error('search must not map automatically'); }},
  };
  context.window = context;
  for (const name of ['navigator','localStorage','sessionStorage']) {
    Object.defineProperty(context, name, {get() { throw new Error('search must not access location or storage'); }});
  }
  vm.runInNewContext(script, context);
  const response = (items, status = 200) => ({ok: status >= 200 && status < 300, status, json: async () => items});
  return {ids, input, toggle, results, submit, events, requests, queue, response,
    setMode(value) { toggle.checked = value; toggle.events.change(); },
    search() { return ids['official-guide-form'].events.submit({preventDefault() {}}); },
    text() { return results.all().map(node => node.textContent).join(' '); },
    example(index) { return ids['official-guide-examples'].events.click({target: examples[index]}); },
    fallback() { return results.all().find(node => node.tag === 'button' && node.textContent === '기본 검색으로 다시 찾기'); },
  };
}

const place = {id: 'verified-place', name: '허브 표시 관광지', kind: 'attraction',
  source_status: 'cross_source_verified', automatic_eligible: true,
  official_intro: {text: '검토한 소개문을 그대로 보여줍니다.', source_url: 'https://www.visitjeju.net/', retrieved_at: '2026-10-29'}};
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };

(async () => {
  const f = fixture();
  assert.equal(f.requests.length, 0, 'startup must not load the neural API');
  assert.equal(f.toggle.checked, false); assert.equal(f.submit.textContent, '소개 찾기');
  f.input.value = '공식 소개'; f.queue.push(f.response([place])); await f.search();
  assert.equal(f.requests[0].url, '/api/guide-search'); assert.match(f.text(), /검토한 소개문/);

  f.setMode(true);
  assert.equal(f.requests.length, 1, 'selecting semantic mode must not submit');
  assert.equal(f.results.children.length, 0); assert.equal(f.submit.textContent, '의미로 소개 찾기');
  assert.match(f.ids['official-guide-status'].textContent, /AI 의미 검색을 선택/);
  f.queue.push(f.response([place, {...place, id: 'unverified', source_status: 'unknown'},
    {...place, id: 'limited', name: '접근 확인 장소', automatic_eligible: false,
      visit_restrictions: [{message: '실제 입구를 확인해야 합니다.'}]}]));
  await f.search();
  assert.equal(f.requests.at(-1).url, '/api/semantic-guide-search');
  assert.equal(f.results.children.length, 2); assert.match(f.text(), /실제 입구를 확인/);
  assert.match(f.ids['official-guide-status'].textContent, /문맥이 비슷한 장소 2곳/);
  assert.match(f.ids['official-guide-status'].textContent, /요청한 조건은 소개문과 원문에서 확인/);
  assert.equal(f.results.children[1].children.at(-1).children.length, 1, 'restricted place stays details-only');
  assert(!f.text().includes('unverified'));

  const inputPending = deferred(); f.queue.push(inputPending.promise); const oldInput = f.search();
  const inputSignal = f.requests.at(-1).options.signal;
  f.input.value = '새 검색어'; f.input.events.input();
  assert(inputSignal.aborted); assert.equal(f.results.children.length, 0); assert.equal(f.submit.disabled, false);
  inputPending.resolve(f.response([{...place, name: 'STALE INPUT'}])); await oldInput;
  assert(!f.text().includes('STALE INPUT')); assert.equal(f.results.children.length, 0);

  const modePending = deferred(); f.queue.push(modePending.promise); const oldMode = f.search();
  const modeSignal = f.requests.at(-1).options.signal;
  f.setMode(false); assert(modeSignal.aborted);
  f.queue.push(f.response([{...place, name: '기본 검색 새 결과'}])); await f.search();
  modePending.resolve(f.response([{...place, name: 'STALE MODE'}])); await oldMode;
  assert.equal(f.requests.at(-1).url, '/api/guide-search');
  assert.match(f.text(), /기본 검색 새 결과/); assert(!f.text().includes('STALE MODE'));

  f.setMode(true); f.queue.push(f.response({error: '의미 검색을 잠시 사용할 수 없어요.'}, 503));
  const before503 = f.requests.length; await f.search();
  assert.equal(f.requests.length, before503 + 1, '503 must not silently call basic search');
  assert(f.toggle.checked); assert.match(f.ids['official-guide-status'].textContent, /잠시 사용할 수 없어요/);
  assert(f.fallback()); assert.equal(f.input.value, '새 검색어');
  f.queue.push(f.response([place])); await f.fallback().events.click();
  assert.equal(f.requests.length, before503 + 2); assert.equal(f.requests.at(-1).url, '/api/guide-search');
  assert.equal(f.requests.at(-1).body.query, '새 검색어'); assert.equal(f.toggle.checked, false);

  f.setMode(true); f.queue.push(new Error('연결하지 못했어요.')); await f.search();
  assert(f.fallback()); assert.match(f.ids['official-guide-status'].textContent, /연결하지 못했어요/);
  f.queue.push(f.response({unexpected: 'shape'})); await f.search();
  assert(f.fallback()); assert.match(f.ids['official-guide-status'].textContent, /자료를 읽지 못했어요/);

  f.queue.push(f.response([])); await f.search();
  assert(!f.fallback(), 'supported empty response uses normal recovery examples');
  assert.match(f.text(), /간단한 주제나 장소명/);
  assert.equal(f.results.all().filter(node => node.tag === 'button').length, 4);
  f.queue.push(f.response([place])); await f.example(1);
  assert.equal(f.requests.at(-1).url, '/api/semantic-guide-search'); assert.equal(f.requests.at(-1).body.query, '화산');

  const resetPending = deferred(); f.queue.push(resetPending.promise); const resetting = f.search();
  const resetSignal = f.requests.at(-1).options.signal; f.events['jeju:reset']();
  assert(resetSignal.aborted); assert.equal(f.toggle.checked, false); assert.equal(f.input.value, '');
  assert.equal(f.submit.textContent, '소개 찾기'); assert.equal(f.ids['official-guide-status'].textContent, '');
  resetPending.resolve(f.response([place])); await resetting; assert.equal(f.results.children.length, 0);

  const html = fs.readFileSync(path.join(__dirname, '../ui/index.html'), 'utf8');
  assert.match(html, /id="official-guide-semantic" type="checkbox"/);
  assert(!html.match(/id="official-guide-semantic"[^>]*\bchecked\b/));
  assert(html.includes('표현이 달라도 공식 소개의 문맥에서 찾습니다. 소개문을 생성하지 않습니다.'));
  console.log('PASS opt-in semantic search, no startup request/GPS/storage, cancellation and stale responses, explicit 503 fallback, source eligibility, examples, and reset.');
})().catch(error => { console.error(error); process.exitCode = 1; });
