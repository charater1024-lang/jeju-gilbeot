'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../ui/official-guide.js'), 'utf8');
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.dataset = {}; this.textContent = ''; this.value = ''; this.isConnected = true; }
  append(...items) { for (const item of items) { item.parent = this; this.children.push(item); } }
  replaceChildren() {
    const remove = item => { item.isConnected = false; item.children.forEach(remove); };
    this.children.forEach(remove); this.children = [];
  }
  addEventListener(name, handler) { this.events[name] = handler; }
  contains(node) { return this === node || this.children.some(child => child.contains(node)); }
  closest() { return this.dataset.guideExample ? this : this.parent?.closest() || null; }
  focus() { this.focused = true; }
  all() { return [this, ...this.children.flatMap(child => child.all())]; }
}
function fixture() {
  const ids = Object.fromEntries(['official-guide-form','official-guide-query','official-guide-submit','official-guide-status','official-guide-results','official-guide-examples'].map(id => [id, new Node(id)]));
  const queries = ['해안', '화산', '전통 가옥', '제주목관아'];
  const buttons = queries.map(query => { const button = new Node('button'); button.dataset.guideExample = query; return button; });
  ids['official-guide-examples'].append(...buttons);
  ids['official-guide-form'].reset = () => { ids['official-guide-query'].value = ''; };
  const events = {}, requests = [], responses = [];
  const context = {document: {getElementById: id => ids[id], createElement: tag => new Node(tag)},
    AbortController, URL, URLSearchParams,
    addEventListener: (name, handler) => { events[name] = handler; },
    fetch: async (url, options) => {
      assert.equal(url, '/api/guide-search');requests.push({query: JSON.parse(options.body).query, options});
      return {ok: true, json: async () => await responses.shift()};
    },
    JejuTripBridge: {openPlace() {}, addPlace() { throw new Error('examples must not add places automatically'); }} };
  context.window = context;
  Object.defineProperty(context, 'navigator', {get() { throw new Error('examples must not request location'); }});
  vm.runInNewContext(script, context);
  return {ids, buttons, events, requests, responses,
    click: index => ids['official-guide-examples'].events.click({target: buttons[index]}),
    submit: () => ids['official-guide-form'].events.submit({preventDefault() {}}),
    text: () => ids['official-guide-results'].all().map(node => node.textContent).join(' ')};
}
const place = {kind: 'attraction', source_status: 'cross_source_verified', id: 'public-place', name: '허브 표시 이름',
  automatic_eligible: true, official_intro: {text: '검토된 공식 소개', source_url: 'https://www.visitjeju.net/', retrieved_at: '2026-10-29'}};
(async () => {
  const f = fixture();assert.equal(f.requests.length, 0, 'examples never search on initial load');
  f.responses.push([place]);await f.click(0);
  assert.equal(f.requests[0].query, '해안');assert.equal(f.ids['official-guide-query'].value, '해안');
  assert(f.ids['official-guide-query'].focused);assert.match(f.text(), /허브 표시 이름/);

  f.ids['official-guide-query'].value = '없는 검색어';f.responses.push([]);await f.submit();
  assert.match(f.text(), /간단한 주제나 장소명/);
  const recovery = f.ids['official-guide-results'].all().filter(node => node.tag === 'button');
  assert.equal(recovery.length, 4);f.responses.push([place]);await recovery[2].events.click();
  assert.equal(f.requests.at(-1).query, '전통 가옥');assert.match(f.text(), /검토된 공식 소개/);

  let finishOld;
  f.responses.push(new Promise(resolve => { finishOld = resolve; }));const old = f.click(1);
  const oldSignal = f.requests.at(-1).options.signal;
  f.responses.push([{...place, id: 'new-place', name: '새 검색 결과'}]);await f.click(3);
  assert(oldSignal.aborted);finishOld([{...place, name: 'OLD RESPONSE'}]);await old;
  assert.match(f.text(), /새 검색 결과/);assert(!f.text().includes('OLD RESPONSE'));
  assert.equal(f.requests.at(-1).query, '제주목관아');

  const fake = new Node('button');fake.dataset.guideExample = '<script>unsafe</script>';
  f.ids['official-guide-examples'].append(fake);const before = f.requests.length;
  f.ids['official-guide-examples'].events.click({target: fake});assert.equal(f.requests.length, before);

  let finishPage;
  f.responses.push(new Promise(resolve => { finishPage = resolve; }));const leaving = f.click(0);
  const leaveSignal = f.requests.at(-1).options.signal;f.events.pagehide();
  assert(leaveSignal.aborted);finishPage([place]);await leaving;assert.equal(f.text(), '');
  f.events['jeju:reset']();assert.equal(f.ids['official-guide-query'].value, '');
  f.ids['official-guide-query'].value = '';await f.submit();assert.match(f.ids['official-guide-status'].textContent, /160자 이내/);
  assert.equal(f.requests.length, before + 1);

  const html = fs.readFileSync(path.join(__dirname, '../ui/index.html'), 'utf8');
  for (const query of ['해안', '화산', '전통 가옥', '제주목관아']) assert(html.includes(`data-guide-example="${query}"`));
  console.log('PASS verified example choices, explicit query visibility, empty-result recovery, cancellation, stale-response guards, unsupported example rejection, and page exit reset.');
})().catch(error => { console.error(error); process.exitCode = 1; });
