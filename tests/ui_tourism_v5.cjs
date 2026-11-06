// Regression tests for the real UI functions. All browser, API and location
// providers are mocked: this test never opens a socket or requests real GPS.
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const appSource = fs.readFileSync(__dirname + '/../ui/app.js', 'utf8');
const discoverySource = fs.readFileSync(__dirname + '/../ui/discovery.js', 'utf8');
const clone = value => JSON.parse(JSON.stringify(value));
const checks = [];
function fragment(source, start, end) {
  const first = source.indexOf(start), last = source.indexOf(end, first + start.length);
  assert(first >= 0 && last > first, `UI function boundaries exist: ${start}`);
  return source.slice(first, last);
}

const fixture = {
  id: 'osm_tourism_node_100000001', plan_place_id: 'osm_tourism_node_100000001',
  name: '가상 검증 해변', kind: 'attraction', category: '해변',
  region: 'north', tags: ['natural:beach', '바다'],
  description: '시험용 원자료 소개문 · 해변과 해안 기록입니다.',
  latitude: 33.51, longitude: 126.52, source_platform: 'openstreetmap',
  source_name: 'OpenStreetMap',
  source_url: 'https://www.openstreetmap.org/node/100000001',
  coordinate_source_url: 'https://www.openstreetmap.org/node/100000001',
  source_date: '2026-10-20', data_license: 'ODbL-1.0',
  source_overlap_verified: true,
  cross_source: {
    hub: {id: 'hub1349_fixture', name: '가상 검증 해변', source_url: 'https://www.jejudatahub.net/data/view/data/1349'},
    osm: {id: 'osm_tourism_node_100000001', name: '가상 검증 해변', source_url: 'https://www.openstreetmap.org/node/100000001'},
    distance_m: 42.5, match_method: 'normalized_exact_name_and_distance'
  },
  match_reason: ['검색어와 관측된 분류가 연결됨'],
  evidence_terms: [
    {term: '해변', feature: 'word:해변', idf: 4.1},
    {term: 'beach', feature: 'word:beach', idf: 5.2}
  ]
};
const fixtures = ['node', 'way', 'relation'].map((kind, i) => ({
  ...clone(fixture), id: `osm_tourism_${kind}_${100000001 + i}`,
  plan_place_id: `osm_tourism_${kind}_${100000001 + i}`,
  source_url: `https://www.openstreetmap.org/${kind}/${100000001 + i}`,
  coordinate_source_url: `https://www.openstreetmap.org/${kind}/${100000001 + i}`,
  ...(kind === 'relation' ? {category: '해변', description: ''} : {})
}));
const rejectedFixture={...clone(fixture),id:'osm_tourism_node_199999999',name:'교차확인 없는 지도 음식점',source_overlap_verified:false};

// Run the actual app normalizer and detail renderer independently of page init.
const detailNodes = new Map();
function detailNode(selector) {
  if (!detailNodes.has(selector)) detailNodes.set(selector, {innerHTML: '', open: false});
  return detailNodes.get(selector);
}
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));
const appContext = {
  $: detailNode, regions: {all: '제주 전체', north: '북부'},
  destinations: [], saved: new Set(), URL, URLSearchParams,
  escapeHTML, safeLink: value => typeof value === 'string' ? value : '',
  safeImage: () => '', icon: () => '', itemRegion: () => '북부',
  itemID: item => String(item.id), openDialog: dialog => { dialog.open = true; },
  getJSON: async () => ({item: clone(fixture)}), handleImageFailures() {}
};
vm.createContext(appContext);
vm.runInContext(
  fragment(appSource, 'function normalizeTourismGuide(raw)', 'function sourceOverlapMarkup(item)') +
  fragment(appSource, 'function sourceOverlapMarkup(item)', 'function cardMarkup(item, index)') +
  fragment(appSource, 'function normalizeOverlapEvidence(raw)', 'function normalizeExtraPlace(raw)') +
  fragment(appSource, 'function normalizeExtraPlace(raw)', 'function renderAudience()') +
  '\nlet detailRequest=0;\n' +
  fragment(appSource, 'async function showRichDetail(', 'async function getJSON('),
  appContext, {filename: 'app.js:tested-functions'}
);

const nodes = new Map(), listeners = new Map(), requests = [], routes = [], added = [];
let created = 0, gpsCalls = 0, geometryFlag = true;
function node(selector) {
  if (!nodes.has(selector)) nodes.set(selector, {
    value: '', innerHTML: '', textContent: '', hidden: false, disabled: false,
    open: false, listeners: {}, children: [],
    classList: {add() {}, remove() {}, toggle() {}},
    addEventListener(name, handler) { this.listeners[name] = handler; },
    append(child) { this.children.push(child); },
    replaceChildren() { this.children = []; },
    reset() {}, scrollIntoView() {}, setAttribute() {}
  });
  return nodes.get(selector);
}
for (const selector of ['#discovery-region', '#tourism-region', '#tourism-category']) node(selector).value = 'all';
node('#discovery-radius').value = '20';
node('#tourism-kind').value = 'attraction';
node('#tourism-query').value = '해변';
const controller = {
  setPlaces() {}, setSelectedIds() {}, clearUserLocation() {}, disableOnline() {},
  clearRoute() {}, setRoads() {}, setRoute(route) { routes.push(clone(route)); return true; }
};
const forbiddenStorage = new Proxy({}, {get() { throw new Error('Browser storage must not be used in this test'); }});
const context = {
  document: {
    querySelector: node, querySelectorAll: () => [],
    addEventListener(name, handler) { listeners.set('document:' + name, handler); },
    createElement: () => node('created-option-' + ++created)
  },
  location: {origin: 'http://127.0.0.1:8769'},
  URL, URLSearchParams, Map, Set, Number, String, Array, Object, Promise, JSON, Math,
  CSS: {escape: String}, matchMedia: () => ({matches: false}), isSecureContext: true,
  navigator: {geolocation: {getCurrentPosition() { ++gpsCalls; throw new Error('Real GPS is prohibited'); }}},
  sessionStorage: forbiddenStorage, localStorage: forbiddenStorage,
  addEventListener(name, handler) { listeners.set(name, handler); },
  JejuMap: {mount: () => controller},
  JejuTripBridge: {
    getSaved: () => [],
    addPlace(point) {
      const normalized = appContext.normalizeExtraPlace(point);
      assert(normalized, 'the app accepts the tourism ID and coordinates');
      added.push({raw: clone(point), normalized: clone(normalized)});
      return true;
    },
    openPlace: point => appContext.showRichDetail(point)
  },
  fetch: async (url, options) => {
    requests.push({url, ...(options ? {options: clone(options)} : {})});
    assert(url.startsWith('/api/'), 'the UI only contacts the mocked local API');
    let data;
    if (url === '/api/destinations') data = {items: []};
    else if (url === '/api/offline-roads') data = {lines: []};
    else if (url === '/api/models-info') data = {cards: []};
    else if (url === '/api/tourism') data = {
      items: clone(JSON.parse(options.body).query === '성산' ? fixtures.slice(0, 1) : [...fixtures,rejectedFixture]),
      total: JSON.parse(options.body).query === '성산' ? 1 : fixtures.length,
      next_cursor: JSON.parse(options.body).query === '성산' ? null : 'previous-query-cursor',
      available_categories: [{value: 'beach', label: '해변', count: 2}],
      model: {training_rows: fixtures.length}, warnings: []
    };
    else if (url === '/api/route-geometry') data = {
      kind: 'road', distance_km: 1.5, warnings: [],
      contains_private_location: geometryFlag,
      lines: [[[126.52, 33.51], [126.53, 33.52]]]
    };
    else throw new Error('Unexpected API request: ' + url);
    return {ok: true, json: async () => clone(data)};
  }
};
context.window = context;
vm.createContext(context);
vm.runInContext(discoverySource, context, {filename: 'discovery.js'});
const tick = () => new Promise(resolve => setImmediate(resolve));
async function flush() { await tick(); await tick(); }
function click(selector, dataset) {
  const target = {dataset};
  listeners.get('document:click')({target: {closest: value => value === selector ? target : null}});
}
function geometryRequests() { return requests.filter(r => r.url === '/api/route-geometry'); }

(async () => {
  await flush();
  const html = node('#tourism-results').innerHTML;
  assert.match(html, /학습 표현 · 해변 · beach/);
  assert(!html.includes('[object Object]'), 'object evidence terms must become readable terms');
  assert(!html.includes(rejectedFixture.name), 'unverified map records are never rendered as tourism');
  assert.match(html,/명부·지도 교차확인/);
  assert.match(html,/빅데이터 명부/);
  assert.match(html,/지도 원문/);
  assert.match(html,/두 자료의 좌표 차이 43m/);
  assert.match(node('#tourism-summary').textContent,/교차확인 관광지/);
  assert.equal(JSON.parse(requests.find(r=>r.url==='/api/tourism').options.body).kind,'attraction');assert.equal(JSON.parse(requests.find(r=>r.url==='/api/tourism').options.body).limit,6);assert.match(html,/<details class="discovery-more-info">/);assert(!html.includes('<details class="discovery-more-info" open'));
  checks.push('tourism results require overlap approval and show separate source proof instead of broad map-only places');
  for (const item of fixtures) assert(html.includes(`data-discovery-add="${item.id}"`), `${item.id} has an add button`);
  checks.push('object evidence terms render as readable strings', 'node/way/relation tourism IDs have add-to-trip buttons');

  for (const item of fixtures) click('[data-discovery-add]', {discoveryAdd: item.id});
  assert.equal(added.length, fixtures.length);
  for (let i = 0; i < fixtures.length; ++i) {
    const {raw, normalized} = added[i], original = fixtures[i];
    assert.equal(raw.id, original.plan_place_id);
    assert.equal(normalized.id, original.plan_place_id);
    assert.equal(normalized.category, original.category);
    assert.deepEqual(normalized.tags, original.tags);
    assert.equal(normalized.source_overlap_verified,true);
    assert.equal(normalized.cross_source.hub.id,original.cross_source.hub.id);
    assert(!normalized.tags.includes('음식'), 'tourism must not acquire a food tag');
    assert(!/업소 위치|메뉴·현재 영업|인허가 명부/.test(normalized.description), 'tourism must not acquire a food description');
    if (original.description) assert.equal(normalized.description, original.description);
    else assert.match(normalized.description, /관광·여행장소/);
  }
  checks.push('tourism category, tags and description survive the actual app normalizer');

  node('#tourism-query').value = '성산';
  node('#tourism-query').listeners.input();
  assert.equal(node('#tourism-more').textContent, '변경한 검색어로 찾기');
  await node('#tourism-more').listeners.click();
  const search = JSON.parse(requests.filter(r => r.url === '/api/tourism').at(-1).options.body);
  assert.equal(search.query, '성산');
  assert.equal(search.cursor, undefined);
  assert.match(node('#tourism-summary').textContent, /1개 기록 중 1개 표시/);
  assert(!node('#tourism-results').innerHTML.includes(`data-discovery-card="${fixtures[1].id}"`));
  checks.push('editing the query starts a fresh page and does not mix old cards');

  await appContext.showRichDetail(clone(fixture));
  const detail = detailNode('#destination-detail').innerHTML;
  assert.match(detail, /겹친 표현 · 해변 · beach/);
  assert(!detail.includes('[object Object]'));
  assert(detail.includes(`data-save="${fixture.id}"`));
  assert.match(detail,/명부·지도 교차확인/);
  assert.match(detail,/두 자료의 좌표 차이 43m/);
  checks.push('detail modal renders object evidence and tourism save ID');
  await appContext.showRichDetail(clone(fixture), {allowTripAdd:false});
  const restrictedDetail = detailNode('#destination-detail').innerHTML;
  assert.match(restrictedDetail,/방문 조건을 별도로 확인할 장소/);
  assert(!restrictedDetail.includes('data-save='));

  for (const testCase of [
    {apiFlag: true, endpoints: true, expectedPrivate: true},
    {apiFlag: false, endpoints: true, expectedPrivate: true},
    {apiFlag: true, endpoints: false, expectedPrivate: true},
    {apiFlag: false, endpoints: false, expectedPrivate: false}
  ]) {
    geometryFlag = testCase.apiFlag;
    const request = {transport: 'car', ...(testCase.endpoints ? {
      // Fixed fictional/public-area coordinates, never obtained from a device.
      start_lat: 33.506, start_lon: 126.492, end_lat: 33.506, end_lon: 126.492
    } : {})};
    await listeners.get('jeju:route')({detail: {
      status: 'ok', data_mode: 'reference', request,
      stops: [{poi_id: fixture.id, name: fixture.name, latitude: fixture.latitude, longitude: fixture.longitude}]
    }});
    const initial = routes.at(-1);
    assert.equal(initial.kind, 'road');
    assert.equal(initial.contains_private_location, testCase.expectedPrivate);
    if (testCase.endpoints) {
      assert.equal(initial.origin.private, true);
      assert.equal(initial.destination.private, true);
    } else {
      assert(!('origin' in initial) && !('destination' in initial));
    }
    const calls = geometryRequests().length;
    context.JejuExplore.showRoute();
    assert.deepEqual(routes.at(-1), initial, 'reopening the itinerary preserves the cached geometry and privacy flags');
    assert.equal(geometryRequests().length, calls, 'reopening uses the cached geometry');
  }
  checks.push('private-location flag retained initially and on itinerary reopen', 'explicit endpoints conservatively mark geometry private', 'public-only geometry remains nonprivate');

  const itineraryGeometry = routes.at(-1);
  const mapRequestCount = requests.length;
  assert.equal(context.JejuExplore.showReturnRoute({kind:'road',coordinates:[[126.5,33.5],[126.51,33.51]],distance_km:1.5}), true);
  assert.deepEqual(routes.at(-1).stops, []);
  assert.equal(routes.at(-1).contains_private_location, true);
  assert.match(node('#map-context').textContent, /오프라인 지도/);
  context.JejuExplore.showRoute();
  assert.deepEqual(routes.at(-1), itineraryGeometry);
  assert.equal(requests.length, mapRequestCount);
  checks.push('return-only overlay stays offline and does not replace cached itinerary geometry');

  assert.equal(gpsCalls, 0);
  assert(requests.every(r => r.url.startsWith('/api/')));
  console.log(JSON.stringify({passed: true, checks, fixture_count: fixtures.length, geometry_cases: 4,
    mocked_api_requests: requests.length, realGPS: false, external_network: false}));
})().catch(error => { console.error(error); process.exitCode = 1; });
