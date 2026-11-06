'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor() {
    this.children = [];
    this.events = {};
    this.textContent = '';
    this.value = '';
    this.isConnected = true;
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() {
    const disconnect = node => {
      node.isConnected = false;
      node.children.forEach(disconnect);
    };
    this.children.forEach(disconnect);
    this.children = [];
  }
  addEventListener(event, handler) { this.events[event] = handler; }
  click() { return this.events.click(); }
}

const form = new Element();
const input = new Element();
const submit = new Element();
const status = new Element();
const results = new Element();
form.reset = () => { input.value = ''; };
const nodes = {
  'official-guide-form': form,
  'official-guide-query': input,
  'official-guide-submit': submit,
  'official-guide-status': status,
  'official-guide-results': results,
};
const eligible = {id: 'public-place', name: '교차확인 장소', kind: 'attraction',
  source_status: 'cross_source_verified', automatic_eligible: true,
  official_intro: {text: '공식 소개의 검토 문장', source_url: 'https://www.visitjeju.net/', retrieved_at: '2026-11-01'}};
const restricted = {...eligible, id: 'restricted-place', name: '배편 확인 장소', automatic_eligible: false,
  visit_restrictions: [{code: 'ferry', message: '배편과 운항 여부를 확인해야 합니다.'}]};
const unverified = {...eligible, id: 'unverified-place', source_status: 'unknown'};
const canonical = {id: eligible.id, name: eligible.name, source_overlap_verified: true,
  latitude: 33.506, longitude: 126.492};

const calls = [];
const events = {};
let detailResponse = canonical;
const context = {
  AbortController, URL, URLSearchParams,
  document: {getElementById: id => nodes[id], createElement: () => new Element()},
  addEventListener: (event, handler) => { events[event] = handler; },
  JejuTripBridge: {
    openPlace: (place, options) => calls.push(['detail', place.id, options.allowTripAdd]),
    addPlace: point => { calls.push(['add', point]); return true; },
  },
  JejuExplore: {showPlaces: points => calls.push(['map', points[0]])},
  fetch: async (url, options) => {
    if (url === '/api/guide-search') {
      assert.equal(JSON.parse(options.body).query, '공식 소개');
      return {ok: true, json: async () => [eligible, restricted, unverified]};
    }
    assert.equal(url, '/api/place-details?id=public-place');
    return {ok: true, json: async () => ({item: detailResponse})};
  },
};
context.window = context;
vm.runInNewContext(fs.readFileSync(__dirname + '/../ui/official-guide.js', 'utf8'), context);

(async () => {
  input.value = '공식 소개';
  await form.events.submit({preventDefault() {}});
  assert.equal(results.children.length, 2);
  const [place, limited] = results.children;
  assert(place.children.some(node => node.textContent === eligible.official_intro.text));
  assert(limited.children.some(node => node.textContent === restricted.visit_restrictions[0].message));

  const [detail, map, add] = place.children.at(-1).children;
  const limitedActions = limited.children.at(-1).children;
  assert.equal(limitedActions.length, 1);
  limitedActions[0].click();
  detail.click();
  assert.deepEqual(calls, [['detail', restricted.id, false], ['detail', eligible.id, true]]);

  await map.click();
  await add.click();
  assert.deepEqual(calls.slice(2), [['map', canonical], ['add', canonical]]);
  detailResponse = {...canonical, source_overlap_verified: false};
  await add.click();
  assert.equal(calls.length, 4);
  assert.match(status.textContent, /공개 좌표를 불러오지 못했어요/);

  events['jeju:reset']();
  assert.equal(input.value, '');
  assert.equal(results.children.length, 0);
  assert.equal(status.textContent, '');
  console.log('Official guide verification, restricted detail, trip actions, and reset passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
