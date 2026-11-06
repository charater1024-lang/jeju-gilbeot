'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const bundled = path.join(__dirname, '../ui/trip-replan.js');
const { buildRequest, createPanel } = require(fs.existsSync(bundled) ? bundled : './trip-replan.js');

// Local fixture based on an automatic result with public 제주 landmarks.
const stops = [
  { poi_id: 'osm_tourism_node_538148519', name: '용두암', latitude: 33.5160353, longitude: 126.511988 },
  { poi_id: 'osm_tourism_way_372948141', name: '탑동광장', latitude: 33.5180929, longitude: 126.5265841 },
  { poi_id: 'osm_tourism_way_1537196430', name: '제주목관아', latitude: 33.5139451, longitude: 126.5221528 },
].map(stop => ({ ...stop, kind: 'attraction', source_overlap_verified: true }));
const [first, second, last] = stops.map(stop => stop.poi_id);
const request = {
  start_lat: 33.507, start_lon: 126.493, origin_source: 'device', origin_label: '원래 출발 위치', origin_accuracy_m: 15,
  end_lat: 33.50317, end_lon: 126.47785, date: '2026-11-06', start_minute: 540, end_minute: 1080,
  budget_krw: 80000, max_stops: 4, transport: 'car', query: '바다', region: 'north', include_geometry: false,
  excluded_ids: ['osm_tourism_way_previous'], destination_ids: [first, second, last],
};
const result = { status: 'ok', selection_mode: 'automatic', data_mode: 'reference', request, stops };
const values = { originPlaceId: last, visitedIds: [second], startTime: '12:05', remainingBudget: '30000' };

assert.deepEqual(buildRequest(result, values), {
  origin_place_id: last, origin_confirmed: true, origin_source: 'landmark',
  end_lat: request.end_lat, end_lon: request.end_lon, date: request.date,
  start_minute: 725, end_minute: request.end_minute, transport: 'car', query: '바다', region: 'north',
  include_geometry: false, budget_krw: 30000, max_stops: 2,
  excluded_ids: [last, second, 'osm_tourism_way_previous'].sort(),
});
assert.deepEqual(buildRequest(result, { ...values, visitedIds: [second, last, second] }).excluded_ids,
  buildRequest(result, values).excluded_ids, 'a selected origin and duplicate checks count once');
assert.equal(buildRequest(result, { ...values, visitedIds: [second, last, second] }).max_stops, 2);
assert.equal(buildRequest(result, { ...values, visitedIds: [], startTime: '09:00', remainingBudget: '0' }).budget_krw, 0);
assert.equal(buildRequest(result, { ...values, startTime: '17:59', remainingBudget: 80000 }).start_minute, 1079);
assert.equal(buildRequest({ ...result, request: { ...request, end_minute: 1440 } }, { ...values, startTime: '23:59' }).end_minute, 1440);
assert.throws(() => buildRequest(result, { ...values, originPlaceId: '' }), /현재 장소/);
assert.throws(() => buildRequest(result, { ...values, visitedIds: ['unknown'] }), /방문 완료 장소/);
for (const startTime of ['', '08:59', '18:00', '24:00', '12:60']) {
  assert.throws(() => buildRequest(result, { ...values, startTime }), /시각/);
}
for (const remainingBudget of ['', ' ', -1, '1e3', '80001', '1.5', true]) {
  assert.throws(() => buildRequest(result, { ...values, remainingBudget }), /남은 추정 이동비/);
}
assert.throws(() => buildRequest({ ...result, request: { ...request, max_stops: 3 } }, { ...values, visitedIds: [first, second] }), /남은 방문 수/);
const returnRequest = buildRequest({ ...result, stops: [stops[0]], request: { ...request, max_stops: 1 } },
  { ...values, action:'return', originPlaceId:first, visitedIds:[] });
assert.equal(returnRequest.return_only, true);
assert.equal(returnRequest.max_stops, 0);
assert.equal(returnRequest.end_lat, request.end_lat);
const broadened = buildRequest(result, { ...values, action:'broaden' });
assert.equal(broadened.region, 'all');
assert.equal(broadened.query, '');
assert.deepEqual(broadened.excluded_ids, buildRequest(result, values).excluded_ids);
assert.equal(broadened.end_minute, request.end_minute);
assert.throws(() => buildRequest({ ...result, request: { ...request, excluded_ids: Array.from({ length: 68 }, (_, i) => `excluded_${i}`) } }, values), /68곳/);
for (const invalid of [
  { ...result, selection_mode: 'manual' }, { ...result, status: 'infeasible' },
  { ...result, stops: [{ ...stops[0], source_overlap_verified: false }] },
  { ...result, request: { ...request, end_lon: '126.5' } },
  { ...result, request: { ...request, date: '2026-02-30' } },
]) {
  assert.equal(createPanel(invalid, { submit() {} }), null);
  assert.throws(() => buildRequest(invalid, values), /자동 추천 일정/);
}
console.log(JSON.stringify({ passed: true, checks: ['fixed itinerary constraints and public origin', 'explicit visits and exclusion union', 'required time and budget boundaries', 'ineligible or malformed result rejected'] }));
