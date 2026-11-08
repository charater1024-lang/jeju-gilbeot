// UI behavior fixtures only; these values are not production model evidence.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.listeners = {}; this.attrs = {}; this.value = ''; this.disabled = false; this.hidden = false; this.textContent = ''; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  set innerHTML(value) { throw new Error('unsafe HTML mutation'); }
}
const names = ['climate-guide', 'climate-form', 'climate-month', 'climate-day', 'climate-station', 'climate-submit', 'climate-retry', 'climate-status', 'climate-result'];
const nodes = Object.fromEntries(names.map(name => [name, new Element()]));
const requests = [], events = {};
const context = {
  document: {getElementById: id => nodes[id], createElement: tag => new Element(tag), createElementNS: (ns, tag) => new Element(tag)},
  URL, URLSearchParams, AbortController, location: {pathname: '/planner'},
  addEventListener: (name, callback) => { events[name] = callback; },
  fetch: (url, options) => new Promise(resolve => requests.push({url, options, resolve}))
};
context.window = context;
const source = fs.readFileSync(__dirname + '/../ui/climate-guide.js', 'utf8');
vm.runInNewContext(source, context);
const month = nodes['climate-month'], day = nodes['climate-day'], station = nodes['climate-station'];
const result = nodes['climate-result'], status = nodes['climate-status'];
const allText = node => [node.textContent, ...node.children.map(allText)].join(' ');
const descendants = (node, match) => [...(match(node) ? [node] : []), ...node.children.flatMap(child => descendants(child, match))];
const flush = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve(); };
const reply = (index, data, ok = true) => requests[index].resolve({ok, json: async () => data});
const enter = () => events['jeju:pagechange']({detail: {path: '/climate'}});
const change = (field, value) => { field.value = String(value); field.listeners.change(); };
const send = () => nodes['climate-form'].listeners.submit({preventDefault() {}});
const stations = [{id: 'jeju', name: '제주'}, {id: 'gosan', name: '고산'}, {id: 'seongsan', name: '성산'}, {id: 'seogwipo', name: '서귀포'}];
const statusData = () => ({schema_version: 1, available: true, ml_applied: true, stations, default_request: {month: 4, day: 15, station: 'jeju'}});
const reference = (request = {month: 4, day: 15, station: 'jeju'}) => {
  const estimates = stations.map((row, i) => ({station: row.id, station_name: row.name, point_c: 13 + i, lower_c: 10 + i, upper_c: 16 + i}));
  return {schema_version: 1, available: true, ml_applied: true, requested: request, stations, selected: estimates.find(row => row.station === request.station), estimates,
    seasonality: Array.from({length: 12}, (_, i) => ({month: i + 1, day: 15, point_c: i + 5, lower_c: i + 2, upper_c: i + 8})),
    reference_period: ['2000-01-01', '2021-10-31'], source: {id: 877, original_producer: '기상청', hub_publisher: '고성빈', url: 'https://www.jejudatahub.net/data/view/data/877'},
    model: {name: '기후 참고 모델', point_name: 'HGB absolute error', interval_name: 'HGB quantile', train_period: ['2000-01-01', '2016-12-31'], dev_period: ['2017-01-01', '2018-12-31'], validation_period: ['2019-01-01', '2021-10-31'], test_mae_c: 1.9199917, baseline_mae_c: 1.9031884, test_rows: 4140, interval_coverage: .76570048, interval_mean_width_c: 5.6930455, latest_year_test: {year: 2021, period: ['2021-01-01', '2021-10-31'], test_mae_c: 2.236, interval_coverage: .6875, bias_c: -1.176}}, limitations: ['과거 자료만 사용합니다.']};
};
(async () => {
  assert.equal(requests.length, 0, 'no climate request on other pages');
  assert.equal(nodes['climate-submit'].disabled, true);
  enter(); assert.equal(requests.length, 1); assert.equal(requests[0].url, '/api/climate-status');
  enter(); assert.equal(requests.length, 1, 'duplicate page event does not duplicate status fetch');
  reply(0, statusData()); await flush();
  assert.equal(requests.length, 2); assert.equal(requests[1].url, '/api/climate-reference?month=4&day=15&station=jeju');
  reply(1, reference()); await flush();
  assert.equal(result.attrs['aria-busy'], 'false');
  const full = allText(result);
  assert.match(full, /13\.0°C/); assert.match(full, /10\.0°C ~ 16\.0°C/); assert.match(full, /68\.8%/); assert.match(full, /76\.57%/);
  assert.match(full, /1\.920°C/); assert.match(full, /1\.903°C/); assert.match(full, /-1\.176°C/); assert.match(full, /2021-10-31/);
  assert.match(full, /毎月15日|毎月 15日|매월 15일/); assert.match(full, /하루의 최저·최고기온이 아닙니다/); assert.match(full, /정확도가 향상됐다는 뜻은 아닙니다/);
  const tables = descendants(result, node => node.tagName === 'table'); assert.equal(tables.length, 4);
  const comparisonRows = descendants(tables[0], node => node.tagName === 'tbody')[0].children;
  assert.equal(comparisonRows.length, 4, 'all four plotted stations have a table row');
  assert.equal(descendants(result, node => node.tagName === 'circle').length, 12, 'only model-provided season points plotted');
  const plotted = descendants(result, node => node.tagName === 'svg')[0]; assert.equal(plotted.attrs['aria-hidden'], 'true');
  const seasonTable = tables[1]; assert.equal(descendants(seasonTable, node => node.tagName === 'tbody')[0].children.length, 12);
  const links = descendants(result, node => node.tagName === 'a'); assert.equal(links.length, 1); assert.equal(links[0].href, 'https://www.jejudatahub.net/data/view/data/877');
  change(month, 2); assert.equal(day.children.length, 29, 'Feb29 is available without assuming a current year');
  assert.equal(result.children.length, 0, 'changed date removes old displayed result');
  change(day, 29); const leap = send(); assert.equal(requests.length, 3); assert.match(requests[2].url, /month=2&day=29/);
  change(station, 'gosan'); assert.equal(requests[2].options.signal.aborted, true);
  const newer = send(); reply(3, reference({month: 2, day: 29, station: 'gosan'})); await newer;
  assert.match(allText(result), /고산 관측 지점/); const saved = allText(result);
  reply(2, reference({month: 2, day: 29, station: 'jeju'})); await leap;
  assert.equal(allText(result), saved, 'old reply cannot overwrite current station result');
  change(month, 4); change(day, 31); const count = requests.length; await send(); assert.equal(requests.length, count, 'invalid date rejected locally'); assert.match(status.textContent, /올바른 월·일/);
  change(day, 15); const failed = send(); reply(4, {error: '모델 파일을 확인할 수 없습니다.'}, false); await failed;
  assert.equal(result.children.length, 0); assert.equal(nodes['climate-retry'].hidden, false); assert.equal(nodes['climate-submit'].disabled, false);
  assert.match(status.textContent, /모델 파일/);
  const retrying = nodes['climate-retry'].listeners.click(); const bad = reference({month: 4, day: 15, station: 'gosan'}); bad.estimates.pop(); reply(5, bad); await retrying;
  assert.equal(result.children.length, 0); assert.match(status.textContent, /네 지점/);
  const invalidSeason = send(); const altered = reference({month: 4, day: 15, station: 'gosan'}); altered.seasonality[0].day = 29; reply(6, altered); await invalidSeason; assert.match(status.textContent, /매월 15일/);
  const unsafeSource = send(); const untrusted = reference({month: 4, day: 15, station: 'gosan'}); untrusted.source.url = 'https://www.jejudatahub.net.evil.test/data/view/data/877'; reply(7, untrusted); await unsafeSource;
  assert.equal(descendants(result, node => node.tagName === 'a').length, 0, 'source links are allowlisted');
  const leaving = send(); events['jeju:pagechange']({detail: {path: '/planner'}}); assert.equal(requests[8].options.signal.aborted, true); assert.equal(result.children.length, 0);
  reply(8, reference({month: 4, day: 15, station: 'gosan'})); await leaving; assert.equal(result.children.length, 0, 'leaving page prevents late result resurrection');
  enter(); assert.equal(requests.length, 10, 'reentry reuses verified controls and refreshes model values');
  events.pagehide(); assert.equal(requests[9].options.signal.aborted, true);
  reply(9, reference({month: 4, day: 15, station: 'gosan'})); await flush(); assert.equal(result.children.length, 0);
  events['jeju:reset'](); assert.equal(nodes['climate-submit'].disabled, true);
  enter(); assert.equal(requests[10].url, '/api/climate-status'); reply(10, {schema_version: 1, available: false, ml_applied: false}); await flush();
  assert.equal(requests.length, 11, 'failed status cannot produce a reference request'); assert.equal(result.children.length, 0); assert.equal(nodes['climate-retry'].hidden, false);
  for (const request of requests) { assert.match(request.url, /^\/api\/climate-(status|reference)(\?|$)/); assert.equal(request.options.credentials, 'same-origin'); assert.equal(request.options.body, undefined); }
  assert.doesNotMatch(source, /localStorage|sessionStorage|indexedDB|geolocation|innerHTML|sendBeacon|new Date/);
  const html = fs.readFileSync(__dirname + '/../ui/index.html', 'utf8');
  assert.match(html, /data-page="\/climate"/); assert.match(html, /href="\/climate"/); assert.match(html, /2000-01-01 ~ 2021-10-31/);
  const grid = html.slice(html.indexOf('<div class="ai-start-grid">'), html.indexOf('<a class="climate-entry"'));
  assert.equal((grid.match(/<article class="ai-start-card/g) || []).length, 3, 'planner three-card grid preserved');
  console.log(JSON.stringify({pass: true, checks: ['lazy status then local-only inference', 'fixed default date independent of current weather', 'Feb29 and invalid day validation', 'four stations and twelve mid-month values with accessible tables', 'historical daily-mean range and latest-year weakness visible', 'input edits cancel stale responses', 'network/shape/status failures permit retry without fabricated fallback', 'page leave and reset abort pending inference', 'no GPS/storage/external inference or current-date forecast', 'existing three planner cards preserved']}));
})().catch(error => { console.error(error); process.exitCode = 1; });
