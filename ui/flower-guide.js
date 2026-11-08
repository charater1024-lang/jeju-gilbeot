(function (global) {
  'use strict';
  if (!document.getElementById('flower-guide')) return;
  const $ = id => document.getElementById(id);
  const form = $('flower-form'), flower = $('flower-kind'), station = $('flower-station'), preference = $('flower-preference');
  const submit = $('flower-submit'), retry = $('flower-retry'), status = $('flower-status'), result = $('flower-result');
  const weatherForm = $('flower-weather-form'), weatherPlace = $('flower-weather-place'), weatherSubmit = $('flower-weather-submit');
  const weatherStatus = $('flower-weather-status'), weatherResult = $('flower-weather-result');
  const state = {active: false, ready: false, serial: 0, controller: null, weatherSerial: 0, weatherController: null, catalog: null};
  const str = value => typeof value === 'string' ? value : '';
  const count = value => Number.isInteger(value) && value >= 0 && value <= 100000;
  const iso = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const temp = value => value.toFixed(1) + '°C';
  const number = new Intl.NumberFormat('ko-KR');
  const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; };
  function message(node, text, error = false) { node.textContent = text; node.className = 'flower-status' + (error ? ' is-error' : ''); }
  function safeURL(raw, kind) {
    try {
      const url = new URL(raw);
      if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')) return null;
      const hub = ['www.jejudatahub.net', 'jejudatahub.net'].includes(url.hostname) && /^\/data\/view\/data\/(761|877)\/?$/.test(url.pathname) && !url.search && !url.hash;
      const kma = ['www.kma.go.kr', 'kma.go.kr', 'data.kma.go.kr', 'www.weather.go.kr', 'weather.go.kr', 'testweather.kma.go.kr'].includes(url.hostname);
      const weather = ['open-meteo.com', 'www.open-meteo.com', 'api.open-meteo.com', 'creativecommons.org'].includes(url.hostname);
      return (kind === 'hub' ? hub : kind === 'kma' ? kma : weather) ? url.href : null;
    } catch { return null; }
  }
  function link(parent, raw, text, kind) {
    const url = safeURL(raw, kind); if (!url) return;
    const node = el('a', 'flower-link', text); node.href = url; node.target = '_blank'; node.rel = 'noopener noreferrer'; parent.append(node);
  }
  function cancelReference() { state.serial += 1; state.controller?.abort(); state.controller = null; result.setAttribute('aria-busy', 'false'); submit.disabled = !state.ready; }
  function clearReference() { cancelReference(); result.replaceChildren(); retry.hidden = true; }
  function clearWeather() { state.weatherSerial += 1; state.weatherController?.abort(); state.weatherController = null; weatherResult.replaceChildren(); weatherResult.setAttribute('aria-busy', 'false'); weatherSubmit.disabled = !state.ready || !state.catalog?.weather?.available; message(weatherStatus, '기준점을 선택하고 버튼을 누를 때만 예보 API를 호출합니다.'); }
  function controls(disabled) { for (const node of [flower, station, preference]) node.disabled = disabled; submit.disabled = disabled; }
  function options(node, rows, label) { node.replaceChildren(); for (const row of rows) { const option = el('option', '', label(row)); option.value = row.id; node.append(option); } }
  function catalogOK(data) {
    const ids = ['cherry', 'canola', 'hydrangea', 'camellia', 'buckwheat', 'silvergrass'];
    if (data?.available !== true || !Array.isArray(data.flowers) || !data.flowers.length || data.flowers.some(row => !ids.includes(row.id) || !str(row.name) || !count(row.event_count)) || new Set(data.flowers.map(row => row.id)).size !== data.flowers.length) throw new Error('꽃 관련 공개 일정의 종류를 확인하지 못했습니다.');
    if (!Array.isArray(data.stations) || data.stations.length !== 4 || new Set(data.stations.map(row => row.id)).size !== 4 || data.stations.some(row => !['jeju', 'gosan', 'seongsan', 'seogwipo'].includes(row.id) || !str(row.name))) throw new Error('과거 기온 관측지점을 확인하지 못했습니다.');
    if (!Array.isArray(data.preferences) || data.preferences.length !== 3 || new Set(data.preferences.map(row => row.id)).size !== 3 || data.preferences.some(row => !['cool', 'mild', 'warm'].includes(row.id) || !str(row.name) || !finite(row.min_c) || !finite(row.max_c) || row.min_c > row.max_c)) throw new Error('기온 비교 조건을 확인하지 못했습니다.');
    if (!Array.isArray(data.event_period) || data.event_period.length !== 2 || !data.event_period.every(iso) || data.event_period[0] > data.event_period[1]) throw new Error('과거 일정의 자료 기간을 확인하지 못했습니다.');
    if (data.flower_prediction?.available !== false) throw new Error('꽃 개화일 예측과 계절 참고의 구분을 확인하지 못했습니다.');
    const defaults = data.default_request;
    if (!defaults || !data.flowers.some(row => row.id === defaults.flower) || !data.stations.some(row => row.id === defaults.station) || !data.preferences.some(row => row.id === defaults.preference)) throw new Error('기본 비교 조건을 확인하지 못했습니다.');
    if (!data.weather || typeof data.weather.available !== 'boolean' || !Array.isArray(data.weather.places) || (data.weather.available && !data.weather.places.length) || new Set(data.weather.places.map(row => row.id)).size !== data.weather.places.length || data.weather.places.some(row => !/^[A-Za-z0-9_-]{1,120}$/.test(row.id) || !str(row.name))) throw new Error('날씨를 참고할 공개 기준점을 확인하지 못했습니다.');
  }
  function monthOK(row) { return row && Number.isInteger(row.month) && row.month >= 1 && row.month <= 12 && row.reference_day === 15 && ['point_c', 'lower_c', 'upper_c'].every(key => finite(row[key]) && row[key] >= -60 && row[key] <= 65) && row.lower_c <= row.upper_c && count(row.event_count) && typeof row.has_event_evidence === 'boolean' && row.has_event_evidence === (row.event_count > 0) && typeof row.within_preference === 'boolean' && finite(row.gap_c) && row.gap_c >= 0; }
  function referenceOK(data, request) {
    catalogOK(data);
    if (!data.requested || Object.keys(request).some(key => data.requested[key] !== request[key])) throw new Error('선택한 꽃·지점·기온 조건과 결과가 일치하지 않습니다.');
    if (!Array.isArray(data.month_comparisons) || data.month_comparisons.length !== 12 || data.month_comparisons.some((row, index) => !monthOK(row) || row.month !== index + 1)) throw new Error('12개월의 실제 기온 비교값을 확인하지 못했습니다.');
    if (typeof data.preference_match_found !== 'boolean' || data.preference_match_found !== data.month_comparisons.some(row => row.has_event_evidence && row.within_preference)) throw new Error('선택한 기온 범위에 맞는 자료가 있는지 확인하지 못했습니다.');
    if (!Array.isArray(data.suggestions) || data.suggestions.length > 3 || new Set(data.suggestions.map(row => row.month)).size !== data.suggestions.length || data.suggestions.some(row => !monthOK(row) || !row.has_event_evidence || ['point_c', 'lower_c', 'upper_c', 'event_count', 'within_preference'].some(key => row[key] !== data.month_comparisons[row.month - 1][key]))) throw new Error('과거 일정에 근거한 참고월을 확인하지 못했습니다.');
    if (!Array.isArray(data.events) || data.events.some(row => !str(row.id) || !str(row.event_name) || !iso(row.start_date) || !iso(row.end_date) || row.start_date > row.end_date || row.reference_only !== true)) throw new Error('과거 공개 일정의 날짜를 확인하지 못했습니다.');
    if (!Array.isArray(data.observations) || data.observations.some(row => !str(row.flower_name) || !str(row.plant_name) || !str(row.station_name) || !str(row.phase) || !iso(row.observed_date) || !Number.isInteger(row.year))) throw new Error('꽃 기준목 관측의 날짜·종류를 확인하지 못했습니다.');
    if (!data.temperature_model || !finite(data.temperature_model.test_mae_c) || data.temperature_source?.id !== 877) throw new Error('과거 기온 AI의 자료 근거를 확인하지 못했습니다.');
  }
  function table(headers, rows, caption, rowClasses = []) {
    const wrap = el('div', 'flower-table-wrap'), node = el('table', 'flower-table'), head = el('thead'), title = el('tr');
    node.append(el('caption', '', caption));
    for (const name of headers) { const th = el('th', '', name); th.setAttribute('scope', 'col'); title.append(th); }
    head.append(title); node.append(head); const body = el('tbody');
    rows.forEach((cells, index) => { const tr = el('tr', rowClasses[index] || ''); cells.forEach((text, position) => { const td = el(position ? 'td' : 'th', '', text); if (!position) td.setAttribute('scope', 'row'); tr.append(td); }); body.append(tr); });
    node.append(body); wrap.append(node); return wrap;
  }
  function details(title) { const node = el('details', 'flower-details'), body = el('div', 'flower-details-body'); node.append(el('summary', '', title), body); return [node, body]; }
  function renderReference(data, request) {
    const selectedFlower = state.catalog.flowers.find(row => row.id === request.flower), selectedStation = state.catalog.stations.find(row => row.id === request.station), selectedPreference = state.catalog.preferences.find(row => row.id === request.preference);
    const head = el('div', 'flower-result-head'), headCopy = el('div');
    headCopy.append(el('h2', '', selectedFlower.name + ', 선택 조건으로 비교한 참고월'), el('p', '', selectedStation.name + ' 관측지점 · ' + selectedPreference.name + ' ' + selectedPreference.min_c + '~' + selectedPreference.max_c + '°C · 과거 일평균기온 기준'));
    head.append(headCopy, el('span', 'flower-method-tag', '기온 AI + 공개 일정의 규칙 비교'));
    const cards = el('div', 'flower-suggestion-grid');
    data.suggestions.forEach((row, index) => { const card = el('article', 'flower-month-card'); card.append(el('p', 'flower-card-index', 'REFERENCE MONTH / 0' + (index + 1)), el('h3', '', row.month + '월')); const value = el('div', 'flower-card-temperature'); value.append(el('strong', '', temp(row.point_c)), el('span', '', '과거 대표 일평균기온')); const range = el('p', 'flower-card-range'); range.append(el('span', '', '기온 비교 기준: ' + row.month + '월 15일'), el('br'), el('span', '', '일평균기온 10~90백분위 추정 ' + temp(row.lower_c) + ' ~ ' + temp(row.upper_c))); card.append(value, range, el('p', 'flower-card-record', '이 꽃의 공개 일정과 겹치는 기록 ' + number.format(row.event_count) + '건'), el('span', 'flower-match' + (row.within_preference ? '' : ' is-outside'), row.within_preference ? '고른 대표기온 범위 안' : '고른 대표기온 범위 밖')); cards.append(card); });
    const note = el('p', 'flower-rule-note', '과거 이 꽃의 일정이 기록된 월 안에서, 매월 15일의 대표기온이 고른 범위의 중앙값에 가까운 순으로 비교했습니다. 일정 기록은 실제 개최·개화·인기도의 증거가 아니며, 기록이 없는 달에 꽃이 없다는 뜻도 아닙니다.');
    const [months, monthsBody] = details('12개월의 기온과 공개 일정 근거 비교하기');
    monthsBody.append(el('p', 'flower-note', '월 중순의 과거 일평균기온 분포입니다. 올해 예보나 하루 최저·최고기온이 아닙니다. 공개 일정 기록 수는 중복 가능성이 있어 고유 행사 수로 해석하지 않습니다.'), table(['참고월', '대표 일평균기온', '10~90백분위 추정 범위', '꽃 관련 공개 일정', '고른 기온 범위'], data.month_comparisons.map(row => [row.month + '월 15일', temp(row.point_c), temp(row.lower_c) + ' ~ ' + temp(row.upper_c), row.event_count ? number.format(row.event_count) + '건' : '해당 기록 없음', row.within_preference ? '범위 안' : '범위 밖']), selectedStation.name + ' 관측지점의 월 중순 기온과 ' + selectedFlower.name + '의 과거 공개 일정', data.month_comparisons.map(row => row.has_event_evidence && row.within_preference ? 'is-month-match' : '')));
    const history = el('section', 'flower-section'); history.append(el('h3', '', '과거 공개 일정에서 찾아본 ' + selectedFlower.name), el('p', 'flower-note', '자료 기간 ' + data.event_period.join(' ~ ') + '. 원자료에 공개된 일정이며 실제 개최 여부·꽃의 상태·올해 일정은 확인하지 않았습니다.'));
    const historyGrid = el('div', 'flower-history-grid');
    function eventCard(row) { const card = el('article', 'flower-history-card'); card.append(el('span', 'flower-record-tag', '과거 공개 일정 기록'), el('h4', '', row.event_name), el('p', '', row.start_date + ' ~ ' + row.end_date)); link(card, row.source_url, '허브 일정 원자료 ↗', 'hub'); return card; }
    for (const row of data.events.slice(0, 6)) historyGrid.append(eventCard(row)); history.append(historyGrid);
    if (data.events.length > 6) { const [more, moreBody] = details('나머지 공개 일정 ' + (data.events.length - 6) + '건 더 보기'); more.className += ' flower-history-more'; const moreGrid = el('div', 'flower-history-grid'); for (const row of data.events.slice(6)) moreGrid.append(eventCard(row)); moreBody.append(moreGrid); history.append(more); }
    if (!data.events.length) history.append(el('p', 'flower-note', '이 꽃의 공개 일정 기록을 확인하지 못해 행사 정보를 표시하지 않았습니다.'));
    const fragment = [head, el('p', 'flower-note', '꽃 관람일정을 정한 결과가 아닙니다. 아래 과거 공개 일정의 시작·종료 날짜를 확인해 주세요.')];
    if (!data.preference_match_found) fragment.push(el('p', 'flower-limit', '고른 기온 범위에 맞는 참고월 자료가 없어 가까운 조건을 비교했습니다. 아래 각 카드의 범위 밖 표시를 함께 확인해 주세요.'));
    if (data.suggestions.length) fragment.push(cards); else fragment.push(el('p', 'flower-no-result', '이 꽃의 공개 일정과 기온 조건을 비교할 근거가 없어 참고월을 만들지 않았습니다. 아래의 실제 자료 범위를 확인해 주세요.'));
    fragment.push(note, months, history);
    if (data.observations.length) { const observed = el('section', 'flower-section'); observed.append(el('h3', '', '확인한 기상청 기준목의 관측 기록'), el('p', 'flower-note', '표준 관측목의 실제 관측 날짜입니다. 다른 꽃밭·관광지의 개화 상태나 지금 꽃이 피어 있다는 뜻은 아닙니다.')); const grid = el('div', 'flower-observation-grid'); for (const row of data.observations) { const card = el('article', 'flower-observation-card'); card.append(el('span', 'flower-record-tag', row.year + '년 · ' + row.flower_name), el('h4', '', row.station_name + ' · ' + row.plant_name + ' ' + row.phase), el('strong', 'flower-observation-date', row.observed_date)); link(card, row.source_url, '기상청 관측 발표 ↗', 'kma'); grid.append(card); } observed.append(grid); fragment.push(observed); }
    const [evidence, evidenceBody] = details('데이터·AI 사용 범위와 오차 확인하기');
    const model = data.temperature_model, list = el('ul', 'flower-metadata-list');
    for (const text of ['꽃 관련 자료: 제주데이터허브 공개 일정 기록. 개화일 학습 정답으로 사용하지 않았습니다.', '기온 모델: ' + (str(model.name) || 'HistGradientBoosting 계절 기온 모델'), '기온 학습: ' + (model.train_period || []).join(' ~ ') + ' / 시간 분리 평가: ' + (model.validation_period || []).join(' ~ '), '기온 평균 절대 오차: ' + model.test_mae_c.toFixed(3) + '°C' + (finite(model.baseline_mae_c) ? ' / 기준 통계 ' + model.baseline_mae_c.toFixed(3) + '°C' : ''), '꽃의 개화일과 개인의 여행 선호를 새로 학습한 모델은 아닙니다.']) list.append(el('li', '', text));
    evidenceBody.append(list);
    if (finite(model.latest_year_test?.interval_coverage)) evidenceBody.append(el('p', 'flower-limit', '기온 모델의 최근 시험연도(2021년 1~10월)에서 범위의 실제 관측 포함률은 ' + (model.latest_year_test.interval_coverage * 100).toFixed(1) + '%였습니다. 과거 경향 참고이며 현재 기후나 꽃의 개화를 보장하지 않습니다.'));
    const limits = el('ul', 'flower-metadata-list'); for (const text of data.limitations || []) if (str(text)) limits.append(el('li', '', text)); evidenceBody.append(limits);
    for (const source of data.sources || []) link(evidenceBody, source.url, str(source.title) + ' ↗', 'hub');
    link(evidenceBody, data.temperature_source.url, '기온 학습 원자료 · 허브 877 ↗', 'hub');
    fragment.push(evidence); result.replaceChildren(...fragment);
  }
  async function readJSON(path, options) { const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...options}); const data = await response.json(); if (!response.ok) throw new Error(str(data.error) || '자료를 불러오지 못했습니다.'); return data; }
  async function loadReference() {
    if (!state.active || !state.ready) return;
    const request = {flower: flower.value, station: station.value, preference: preference.value};
    if (!state.catalog.flowers.some(row => row.id === request.flower) || !state.catalog.stations.some(row => row.id === request.station) || !state.catalog.preferences.some(row => row.id === request.preference)) { clearReference(); message(status, '자료에서 제공하는 꽃·지점·기온 조건을 선택해 주세요.', true); return; }
    clearReference(); const serial = state.serial, controller = new AbortController(); state.controller = controller; submit.disabled = true; result.setAttribute('aria-busy', 'true'); message(status, '공개 일정과 과거 기온으로 참고월을 비교하고 있어요.');
    try { const data = await readJSON('/api/flower-seasons?' + new URLSearchParams(request), {signal: controller.signal}); if (serial !== state.serial || !state.active) return; referenceOK(data, request); renderReference(data, request); message(status, '선택 조건으로 참고월을 비교했습니다. 공개 일정과 개화 시기는 구분해 읽어 주세요.'); }
    catch (error) { if (serial !== state.serial || !state.active) return; result.replaceChildren(); message(status, str(error.message) || '자료를 확인하지 못했습니다. 다시 시도해 주세요.', true); retry.hidden = false; }
    finally { if (serial === state.serial) { state.controller = null; result.setAttribute('aria-busy', 'false'); submit.disabled = !state.ready; } }
  }
  function weatherOK(data, placeID) {
    if (data?.available !== true || data.current_forecast !== true || data.flower_prediction !== false || data.point?.id !== placeID || !str(data.point.name) || !str(data.retrieved_at)) throw new Error('선택한 기준점의 날씨 예보를 확인하지 못했습니다.');
    if (!Array.isArray(data.forecast_period) || data.forecast_period.length !== 2 || !data.forecast_period.every(iso) || !Array.isArray(data.days) || data.days.length !== 7 || new Set(data.days.map(row => row.date)).size !== 7 || data.days.some(row => !iso(row.date) || ![row.t_min_c, row.t_max_c, row.precipitation_mm, row.wind_max_ms].every(finite) || row.t_min_c > row.t_max_c || row.precipitation_mm < 0 || row.wind_max_ms < 0 || row.date < data.forecast_period[0] || row.date > data.forecast_period[1])) throw new Error('7일 예보의 날짜와 값을 확인하지 못했습니다.');
  }
  function renderWeather(data) {
    const meta = el('p', 'flower-weather-meta', data.point.name + ' 공개 기준점 · ' + data.forecast_period.join(' ~ ') + ' · 가져온 시각 ' + data.retrieved_at + (data.cached ? ' · 저장된 최근 응답' : ''));
    const values = table(['예보 날짜', '최저기온', '최고기온', '강수량', '최대 풍속'], data.days.map(row => [row.date, temp(row.t_min_c), temp(row.t_max_c), row.precipitation_mm.toFixed(1) + ' mm', row.wind_max_ms.toFixed(1) + ' m/s']), '선택한 공개 기준점의 7일 날씨 예보 · 꽃 개화 예보 아님');
    const sources = el('div', 'flower-weather-links'); sources.append(el('span', '', 'Open-Meteo 무료 비상업 예보')); link(sources, data.source_url, '예보 제공 출처 ↗', 'weather'); link(sources, data.licence_url, '이용 조건·출처 표시 ↗', 'weather');
    const notes = el('ul', 'flower-metadata-list'); for (const text of data.limitations || []) if (str(text)) notes.append(el('li', '', text)); weatherResult.replaceChildren(meta, values, sources, notes);
  }
  async function loadWeather() {
    if (!state.active || !state.ready) return;
    const placeID = weatherPlace.value; if (!state.catalog.weather.places.some(row => row.id === placeID)) { clearWeather(); message(weatherStatus, '공개 기준점을 선택해 주세요.', true); return; }
    clearWeather(); const serial = state.weatherSerial, controller = new AbortController(); state.weatherController = controller; weatherSubmit.disabled = true; weatherResult.setAttribute('aria-busy', 'true'); message(weatherStatus, '선택한 공개 기준점의 7일 예보를 가져오고 있어요.');
    try { const data = await readJSON('/api/flower-weather', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({place_id: placeID}), signal: controller.signal}); if (serial !== state.weatherSerial || !state.active) return; weatherOK(data, placeID); renderWeather(data); message(weatherStatus, '7일 날씨 예보를 확인했습니다. 꽃의 개화 관측·예측과는 별개입니다.'); }
    catch (error) { if (serial !== state.weatherSerial || !state.active) return; weatherResult.replaceChildren(); message(weatherStatus, (str(error.message) || '7일 예보를 확인하지 못했습니다.') + ' 꽃 공개 일정과 과거 기온 참고는 계속 사용할 수 있습니다.', true); }
    finally { if (serial === state.weatherSerial) { state.weatherController = null; weatherResult.setAttribute('aria-busy', 'false'); weatherSubmit.disabled = !state.ready || !state.catalog.weather.available; } }
  }
  async function initialize() {
    if (!state.active) return;
    clearReference(); controls(true); const serial = state.serial, controller = new AbortController(); state.controller = controller; message(status, '꽃 관련 공개 일정과 모델 자료를 확인하고 있어요.');
    try { const data = await readJSON('/api/flower-status', {signal: controller.signal}); if (serial !== state.serial || !state.active) return; catalogOK(data); state.catalog = data;
      options(flower, data.flowers, row => row.name + ' · 공개 일정 ' + number.format(row.event_count) + '건'); options(station, data.stations, row => row.name); options(preference, data.preferences, row => row.name + ' (' + row.min_c + '~' + row.max_c + '°C)');
      flower.value = data.default_request.flower; station.value = data.default_request.station; preference.value = data.default_request.preference;
      options(weatherPlace, data.weather.places, row => row.name); weatherPlace.value = data.weather.places[0]?.id || ''; weatherPlace.disabled = !data.weather.available; state.ready = true; controls(false); clearWeather(); state.controller = null; await loadReference();
    } catch (error) { if (serial !== state.serial || !state.active) return; state.ready = false; controls(true); weatherPlace.disabled = true; weatherSubmit.disabled = true; message(status, str(error.message) || '꽃 관련 자료를 확인하지 못했습니다.', true); retry.hidden = false; state.controller = null; }
  }
  form.addEventListener('submit', event => { event.preventDefault(); return loadReference(); });
  for (const field of [flower, station, preference]) field.addEventListener('change', () => { clearReference(); message(status, '조건이 바뀌었어요. 참고월 비교하기를 눌러 주세요.'); });
  retry.addEventListener('click', () => state.ready ? loadReference() : initialize());
  weatherForm.addEventListener('submit', event => { event.preventDefault(); return loadWeather(); });
  weatherPlace.addEventListener('change', clearWeather);
  function enter(path) { const active = path === '/flowers'; if (active === state.active) return; state.active = active; if (!active) { clearReference(); clearWeather(); } else if (state.ready) loadReference(); else initialize(); }
  global.addEventListener('jeju:pagechange', event => enter(event.detail?.path));
  global.addEventListener('pagehide', () => { state.active = false; clearReference(); clearWeather(); });
  global.addEventListener('jeju:reset', () => { clearReference(); clearWeather(); state.ready = false; state.catalog = null; controls(true); weatherPlace.disabled = true; weatherSubmit.disabled = true; if (state.active) initialize(); });
  controls(true); weatherSubmit.disabled = true; enter(global.JejuPages?.getPath?.() || global.location.pathname);
})(window);
