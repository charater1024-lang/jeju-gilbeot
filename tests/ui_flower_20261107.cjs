// UI behavior fixtures only. These are not flower observations or production model evidence.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.listeners = {}; this.attrs = {}; this.value = ''; this.disabled = false; this.hidden = false; this.textContent = ''; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  set innerHTML(value) { throw new Error('unsafe HTML mutation'); }
}
const ids = ['flower-guide', 'flower-form', 'flower-kind', 'flower-station', 'flower-preference', 'flower-submit', 'flower-retry', 'flower-status', 'flower-result', 'flower-weather-form', 'flower-weather-place', 'flower-weather-submit', 'flower-weather-status', 'flower-weather-result'];
const nodes = Object.fromEntries(ids.map(id => [id, new Element()])), requests = [], events = {};
const context = {document: {getElementById: id => nodes[id], createElement: tag => new Element(tag)}, URL, URLSearchParams, AbortController, location: {pathname: '/planner'}, addEventListener: (name, callback) => { events[name] = callback; }, fetch: (url, options) => new Promise(resolve => requests.push({url, options, resolve}))};
context.window = context;
const source = fs.readFileSync(__dirname + '/../ui/flower-guide.js', 'utf8'); vm.runInNewContext(source, context);
const text = node => [node.textContent, ...node.children.map(text)].join(' ');
const find = (node, test) => [...(test(node) ? [node] : []), ...node.children.flatMap(child => find(child, test))];
const result = nodes['flower-result'], weather = nodes['flower-weather-result'];
const enter = () => events['jeju:pagechange']({detail: {path: '/flowers'}});
const leave = () => events['jeju:pagechange']({detail: {path: '/planner'}});
const change = (id, value) => { nodes[id].value = value; nodes[id].listeners.change(); };
const send = () => nodes['flower-form'].listeners.submit({preventDefault() {}});
const sendWeather = () => nodes['flower-weather-form'].listeners.submit({preventDefault() {}});
const reply = (index, data, ok = true) => requests[index].resolve({ok, json: async () => data});
const flush = async () => { for (let i = 0; i < 20; i += 1) await Promise.resolve(); };
const stations = [{id: 'jeju', name: '제주'}, {id: 'gosan', name: '고산'}, {id: 'seongsan', name: '성산'}, {id: 'seogwipo', name: '서귀포'}];
const catalog = () => ({available: true, flowers: [{id: 'hydrangea', name: '수국', event_count: 2}, {id: 'cherry', name: '벚꽃', event_count: 1}], stations, preferences: [{id: 'cool', name: '시원하게', min_c: 15, max_c: 20}, {id: 'mild', name: '온화하게', min_c: 18, max_c: 24}, {id: 'warm', name: '따뜻하게', min_c: 22, max_c: 27}], default_request: {flower: 'hydrangea', station: 'seogwipo', preference: 'mild'}, event_period: ['2018-01-01', '2021-12-31'], sources: [{id: 761, title: '제주 공개 일정', url: 'https://www.jejudatahub.net/data/view/data/761'}], weather: {available: true, provider: 'Open-Meteo', places: [{id: 'public_jeju', name: '제주 공개 기준점'}, {id: 'public_south', name: '남부 공개 기준점'}]}, flower_prediction: {available: false, user_message: '개화일 예측은 제공하지 않습니다.'}});
function reference(request = {flower: 'hydrangea', station: 'seogwipo', preference: 'mild'}) {
  const common = catalog(), pref = common.preferences.find(row => row.id === request.preference);
  const months = Array.from({length: 12}, (_, i) => { const point = i + 9, count = [5, 6].includes(i) ? 1 : 0; return {month: i + 1, reference_day: 15, point_c: point, lower_c: point - 3, upper_c: point + 3, event_count: count, has_event_evidence: count > 0, within_preference: point >= pref.min_c && point <= pref.max_c, gap_c: Math.abs(point - (pref.min_c + pref.max_c) / 2)}; });
  return {...common, requested: request, month_comparisons: months, preference_match_found: months.some(row => row.has_event_evidence && row.within_preference), suggestions: [months[6], months[5]], events: [{id: 'fixture_1', event_name: '공개 일정 테스트 기록', start_date: '2019-06-01', end_date: '2019-07-15', source_row: 2, source_url: 'https://www.jejudatahub.net/data/view/data/761', reference_only: true}], observations: request.flower === 'cherry' ? [{flower: 'cherry', flower_name: '벚꽃', plant_name: '벚나무', year: 2026, station_id: 'jeju', station_name: '제주', phase: '개화', observed_date: '2026-03-28', scope: 'standard_tree', source_url: 'https://www.kma.go.kr/jeju/html/news/notice_view.jsp?articleno=fixture', source_title: 'UI fixture'}] : [], temperature_model: {name: 'HistGradientBoosting 계절 기온 모델', train_period: ['2000-01-01', '2016-12-31'], validation_period: ['2019-01-01', '2021-10-31'], test_mae_c: 1.9199917, baseline_mae_c: 1.9031884, latest_year_test: {interval_coverage: .6875}}, temperature_source: {id: 877, url: 'https://www.jejudatahub.net/data/view/data/877'}, limitations: ['공개 일정은 개화 날짜가 아닙니다.']};
}
const forecast = (id = 'public_jeju') => ({available: true, provider: 'Open-Meteo', source_url: 'https://open-meteo.com/', licence_url: 'https://open-meteo.com/en/terms', point: {id, name: id === 'public_jeju' ? '제주 공개 기준점' : '남부 공개 기준점', lat: 33.5, lon: 126.5}, retrieved_at: '2026-11-07T13:00:00Z', forecast_period: ['2026-11-08', '2026-11-14'], days: Array.from({length: 7}, (_, i) => ({date: '2026-11-' + String(8 + i).padStart(2, '0'), t_min_c: 11, t_max_c: 19, precipitation_mm: 0.2, wind_max_ms: 4})), current_forecast: true, flower_prediction: false, cached: false, limitations: ['날씨 예보이며 개화 예보가 아닙니다.']});
(async () => {
  assert.equal(requests.length, 0, 'other pages do not fetch flower data');
  enter(); enter(); assert.equal(requests.length, 1, 'one lazy catalog request'); assert.equal(requests[0].url, '/api/flower-status');
  reply(0, catalog()); await flush(); assert.equal(requests.length, 2); assert.equal(requests[1].url, '/api/flower-seasons?flower=hydrangea&station=seogwipo&preference=mild');
  reply(1, reference()); await flush(); const ready = text(result);
  assert.match(ready, /선택 조건으로 비교한 참고월/); assert.match(ready, /규칙 비교/); assert.match(ready, /실제 개최·개화·인기도의 증거가 아니며/); assert.match(ready, /기온.*1\.920°C/); assert.match(ready, /1\.903°C/); assert.match(ready, /68\.8%/);
  assert.equal(find(result, node => node.className === 'flower-month-card').length, 2);
  const monthCards = find(result, node => node.className === 'flower-month-card');
  assert.deepEqual(monthCards.map(card => find(card, node => node.tagName === 'h3')[0].textContent), ['7월', '6월'], 'card titles are reference months, not mid-month bloom dates');
  assert.match(text(monthCards[0]), /기온 비교 기준: 7월 15일/); assert.match(ready, /꽃 관람일정을 정한 결과가 아닙니다/); assert.match(ready, /과거 공개 일정의 시작·종료 날짜/);
  assert.match(ready, /고른 기온 범위에 맞는 참고월 자료가 없어 가까운 조건을 비교했습니다/);
  assert.deepEqual(nodes['flower-preference'].children.map(node => node.textContent), ['시원하게 (15~20°C)', '온화하게 (18~24°C)', '따뜻하게 (22~27°C)']);
  assert.equal(find(result, node => node.tagName === 'tbody')[0].children.length, 12, '12 supplied months, not invented flower windows');
  assert.match(ready, /과거 공개 일정 기록/); assert.doesNotMatch(ready, /개최 횟수|만개 예정일|개화 예측일|인기도 점수/);
  assert.equal(requests.length, 2, 'weather API is never called automatically');
  const weatherFailed = sendWeather(); assert.equal(requests[2].url, '/api/flower-weather'); assert.deepEqual(JSON.parse(requests[2].options.body), {place_id: 'public_jeju'});
  reply(2, {error: '외부 예보를 확인하지 못했습니다.'}, false); await weatherFailed; assert.equal(text(result), ready, 'weather failure preserves flower and historical ML result'); assert.match(nodes['flower-weather-status'].textContent, /과거 기온 참고는 계속/); assert.equal(weather.children.length, 0);
  const weatherOK = sendWeather(); reply(3, forecast()); await weatherOK; assert.equal(find(weather, node => node.tagName === 'tbody')[0].children.length, 7); assert.match(text(weather), /무료 비상업 예보/); assert.match(text(weather), /꽃 개화 예보 아님/); assert.match(text(weather), /4\.0 m\/s/);
  change('flower-weather-place', 'public_south'); assert.equal(weather.children.length, 0); assert.equal(text(result), ready);
  const olderWeather = sendWeather(); change('flower-weather-place', 'public_jeju'); assert.equal(requests[4].options.signal.aborted, true); const newerWeather = sendWeather(); reply(5, forecast()); await newerWeather; const weatherSaved = text(weather); reply(4, forecast('public_south')); await olderWeather; assert.equal(text(weather), weatherSaved, 'older weather place cannot replace newest result');
  change('flower-kind', 'cherry'); assert.equal(result.children.length, 0); assert.equal(text(weather), weatherSaved, 'independent forecast remains for same public weather point');
  const oldReference = send(); change('flower-preference', 'cool'); assert.equal(requests[6].options.signal.aborted, true); const currentReference = send(); reply(7, reference({flower: 'cherry', station: 'seogwipo', preference: 'cool'})); await currentReference; const selected = text(result); assert.match(selected, /2026-03-28/); assert.match(selected, /표준 관측목/); assert.match(selected, /다른 꽃밭/); assert.doesNotMatch(selected, /고른 기온 범위에 맞는 참고월 자료가 없어/); reply(6, reference({flower: 'cherry', station: 'seogwipo', preference: 'mild'})); await oldReference; assert.equal(text(result), selected);
  const malformed = send(), short = reference({flower: 'cherry', station: 'seogwipo', preference: 'cool'}); short.month_comparisons.pop(); reply(8, short); await malformed; assert.equal(result.children.length, 0); assert.match(nodes['flower-status'].textContent, /12개월/); assert.equal(nodes['flower-retry'].hidden, false);
  const recovery = nodes['flower-retry'].listeners.click(); reply(9, reference({flower: 'cherry', station: 'seogwipo', preference: 'cool'})); await recovery; assert.notEqual(result.children.length, 0);
  const unsupported = send(), changed = reference({flower: 'cherry', station: 'seogwipo', preference: 'cool'}); changed.suggestions = [changed.month_comparisons[0]]; reply(10, changed); await unsupported; assert.equal(result.children.length, 0, 'month with no event evidence cannot become suggestion');
  const leaving = send(); leave(); assert.equal(requests[11].options.signal.aborted, true); assert.equal(result.children.length, 0); assert.equal(weather.children.length, 0); reply(11, reference({flower: 'cherry', station: 'seogwipo', preference: 'cool'})); await leaving; assert.equal(result.children.length, 0, 'page exit blocks late result resurrection');
  enter(); assert.match(requests[12].url, /^\/api\/flower-seasons/); events.pagehide(); assert.equal(requests[12].options.signal.aborted, true); reply(12, reference({flower: 'cherry', station: 'seogwipo', preference: 'cool'})); await flush(); assert.equal(result.children.length, 0);
  events['jeju:reset'](); assert.equal(nodes['flower-submit'].disabled, true); enter(); assert.equal(requests[13].url, '/api/flower-status'); reply(13, {available: false}); await flush(); assert.equal(requests.length, 14, 'bad catalog never starts a reference or weather fetch'); assert.equal(nodes['flower-retry'].hidden, false);
  for (const request of requests) { assert.match(request.url, /^\/api\/flower-(status|seasons|weather)(\?|$)/); assert.equal(request.options.credentials, 'same-origin'); if (request.url === '/api/flower-weather') { assert.equal(request.options.method, 'POST'); assert.deepEqual(Object.keys(JSON.parse(request.options.body)), ['place_id']); } else assert.equal(request.options.body, undefined); }
  assert.doesNotMatch(source, /localStorage|sessionStorage|indexedDB|geolocation|innerHTML|sendBeacon|new Date/);
  const html = fs.readFileSync(__dirname + '/../ui/index.html', 'utf8'); assert.match(html, /data-page="\/flowers"/); assert.match(html, /꽃 여행 시기 같이 보기/); assert.match(html, /개화일을 예측하는 기능은 제공하지 않습니다/); assert.equal((html.slice(html.indexOf('<div class="ai-start-grid">'), html.indexOf('<a class="climate-entry"')).match(/<article class="ai-start-card/g) || []).length, 3);
  console.log(JSON.stringify({pass: true, checks: ['lazy local status and source-backed rule comparison', '12 actual climate months and historical-only event records', 'KMA observed specimen is distinct from current blooming', 'weather API only by explicit public-place submit', 'weather error leaves flower and ML results intact', 'independent race cancellation for flower and weather', 'page leave and reset prevent late results', 'no GPS credentials browser storage or invented bloom forecast', 'planner grid and climate cross-link preserved']}));
})().catch(error => { console.error(error); process.exitCode = 1; });
