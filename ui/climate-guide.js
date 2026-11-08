(function (global) {
  'use strict';
  const host = document.getElementById('climate-guide');
  if (!host) return;
  const $ = id => document.getElementById(id);
  const form = $('climate-form'), month = $('climate-month'), day = $('climate-day'), station = $('climate-station');
  const submit = $('climate-submit'), retry = $('climate-retry'), status = $('climate-status'), result = $('climate-result');
  const state = {ready: false, active: false, serial: 0, controller: null, stations: []};
  const days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const nf = new Intl.NumberFormat('ko-KR');
  const str = value => typeof value === 'string' ? value : '';
  const temp = value => value.toFixed(1) + '°C';
  const el = (tag, cls, content) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (content !== undefined) node.textContent = content;
    return node;
  };
  function setStatus(message, error = false) {
    status.textContent = message;
    status.className = 'climate-status' + (error ? ' climate-error' : '');
  }
  function busy(value) {
    result.setAttribute('aria-busy', String(value));
    submit.disabled = value || !state.ready;
    retry.hidden = value;
  }
  function cancel() {
    state.serial += 1;
    state.controller?.abort();
    state.controller = null;
    result.setAttribute('aria-busy', 'false');
    submit.disabled = !state.ready;
  }
  function clearResult() {
    cancel(); result.replaceChildren();
    retry.hidden = true;
  }
  function dayOptions(wanted = Number(day.value) || 15) {
    const max = days[Number(month.value) - 1];
    day.replaceChildren();
    for (let i = 1; i <= max; i += 1) {
      const option = el('option', '', i + '일'); option.value = String(i); day.append(option);
    }
    day.value = String(Math.min(Math.max(1, wanted), max));
  }
  function stationRows(rows) {
    if (!Array.isArray(rows) || rows.length !== 4) throw new Error('관측 지점 정보를 확인할 수 없습니다.');
    const expected = ['jeju', 'gosan', 'seongsan', 'seogwipo'];
    if (new Set(rows.map(row => row.id)).size !== 4 || rows.some(row => !expected.includes(row.id) || !str(row.name))) throw new Error('관측 지점 정보 형식이 올바르지 않습니다.');
    return rows;
  }
  function validTemperature(row) {
    return row && ['point_c', 'lower_c', 'upper_c'].every(key => Number.isFinite(row[key]) && row[key] >= -60 && row[key] <= 65) && row.lower_c <= row.upper_c;
  }
  function validate(data, request) {
    if (data.schema_version !== 1 || data.available !== true || data.ml_applied !== true) throw new Error('검증된 기후 참고 모델을 지금 사용할 수 없습니다.');
    stationRows(data.stations);
    if (!data.requested || Object.keys(request).some(key => data.requested[key] !== request[key])) throw new Error('요청한 날짜·지점과 결과가 일치하지 않습니다.');
    if (!Array.isArray(data.estimates) || data.estimates.length !== 4 || new Set(data.estimates.map(row => row.station)).size !== 4 || data.estimates.some(row => !state.stations.some(item => item.id === row.station) || !validTemperature(row))) throw new Error('네 지점의 기온 값을 확인하지 못했습니다.');
    if (!validTemperature(data.selected) || data.selected.station !== request.station) throw new Error('선택한 지점의 기온 값을 확인하지 못했습니다.');
    const selected = data.estimates.find(row => row.station === request.station);
    if (['point_c', 'lower_c', 'upper_c'].some(key => Math.abs(data.selected[key] - selected[key]) > 0.000001)) throw new Error('선택한 지점의 결과가 일치하지 않습니다.');
    if (!Array.isArray(data.seasonality) || data.seasonality.length !== 12 || data.seasonality.some((row, index) => row.month !== index + 1 || row.day !== 15 || !validTemperature(row))) throw new Error('매월 15일의 계절 흐름을 확인하지 못했습니다.');
    if (!Array.isArray(data.reference_period) || data.reference_period.length !== 2 || data.reference_period.some(value => !/^\d{4}-\d{2}-\d{2}$/.test(value)) || data.source?.id !== 877) throw new Error('자료의 출처·관측 기간을 확인하지 못했습니다.');
  }
  function safeSource(raw) {
    try {
      const url = new URL(raw);
      return url.protocol === 'https:' && url.hostname === 'www.jejudatahub.net' && /^\/data\/view\/data\/877\/?$/.test(url.pathname) && !url.username && !url.password && !url.search && !url.hash ? url.href : null;
    } catch { return null; }
  }
  function periodText(period) {
    return Array.isArray(period) && period.length === 2 ? period.map(str).join(' ~ ') : '기간 정보 확인 필요';
  }
  function table(headers, rows, caption) {
    const wrap = el('div', 'climate-table-wrap'), node = el('table', 'climate-table');
    node.append(el('caption', '', caption));
    const head = el('thead'), tr = el('tr');
    for (const header of headers) { const th = el('th', '', header); th.setAttribute('scope', 'col'); tr.append(th); }
    head.append(tr); node.append(head);
    const body = el('tbody');
    for (const cells of rows) {
      const row = el('tr');
      cells.forEach((cell, index) => { const item = el(index ? 'td' : 'th', '', cell); if (!index) item.setAttribute('scope', 'row'); row.append(item); });
      body.append(row);
    }
    node.append(body); wrap.append(node); return wrap;
  }
  function svgNode(tag, attrs, content) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, String(value));
    if (content !== undefined) node.textContent = content;
    return node;
  }
  function seasonChart(rows) {
    const svg = svgNode('svg', {viewBox: '0 0 740 280', 'aria-hidden': 'true', focusable: 'false', class: 'climate-chart'});
    const low = Math.floor(Math.min(...rows.flatMap(row => [row.lower_c, row.point_c])) / 5) * 5;
    const high = Math.max(low + 5, Math.ceil(Math.max(...rows.flatMap(row => [row.upper_c, row.point_c])) / 5) * 5);
    const x = i => 48 + i * (664 / 11), y = value => 232 - (value - low) / (high - low) * 206;
    for (let i = 0; i <= 4; i += 1) {
      const value = low + (high - low) * i / 4, pos = y(value);
      svg.append(svgNode('line', {x1: 48, y1: pos, x2: 712, y2: pos, class: 'climate-grid-line'}), svgNode('text', {x: 39, y: pos + 4, 'text-anchor': 'end', class: 'climate-tick'}, value.toFixed(0) + '°'));
    }
    const points = rows.map((row, i) => x(i) + ',' + y(row.upper_c)).concat([...rows].reverse().map((row, i) => x(11 - i) + ',' + y(row.lower_c)));
    svg.append(svgNode('polygon', {points: points.join(' '), class: 'climate-band'}));
    svg.append(svgNode('polyline', {points: rows.map((row, i) => x(i) + ',' + y(row.point_c)).join(' '), class: 'climate-point-line'}));
    rows.forEach((row, i) => svg.append(svgNode('circle', {cx: x(i), cy: y(row.point_c), r: 4, class: 'climate-point-dot'}), svgNode('text', {x: x(i), y: 261, 'text-anchor': 'middle', class: 'climate-tick'}, row.month + '월')));
    return svg;
  }
  function modelDetails(data) {
    const details = el('details', 'climate-details'); details.append(el('summary', '', '사용한 AI 모델·평가와 자료 출처'));
    const model = data.model || {}, source = data.source || {};
    const body = el('div', 'climate-details-body');
    body.append(el('h4', '', str(model.name) || '과거 일평균기온 기후 참고 모델'));
    const list = el('ul');
    for (const line of [
      '대표값: ' + (str(model.point_name) || 'HistGradientBoosting · absolute error'),
      '분포 범위: ' + (str(model.interval_name) || 'HistGradientBoosting · 10·90백분위 회귀'),
      '학습: ' + periodText(model.train_period) + ' / 개발: ' + periodText(model.dev_period),
      '시간을 분리한 최종 평가: ' + periodText(model.validation_period),
      '관측 원자료: ' + str(source.original_producer) + ' 유래 / 제주데이터허브 게시: ' + str(source.hub_publisher)
    ]) list.append(el('li', '', line));
    body.append(list);
    const metrics = [];
    if (Number.isFinite(model.test_mae_c)) metrics.push(['대표값 평균절대오차(MAE)', model.test_mae_c.toFixed(3) + '°C']);
    if (Number.isFinite(model.baseline_mae_c)) metrics.push(['개발 구간에서 고른 기준통계 MAE', model.baseline_mae_c.toFixed(3) + '°C']);
    if (Number.isFinite(model.interval_coverage)) metrics.push(['평가 관측값의 추정 범위 포함률', (model.interval_coverage * 100).toFixed(2) + '%']);
    if (Number.isFinite(model.interval_mean_width_c)) metrics.push(['추정 범위 평균 너비', model.interval_mean_width_c.toFixed(3) + '°C']);
    if (Number.isInteger(model.test_rows)) metrics.push(['평가 관측 건수', nf.format(model.test_rows) + '건']);
    if (metrics.length) body.append(table(['평가 항목', '실측 성능'], metrics, '과거 자료를 시간으로 분리한 모델 평가'));
    const latest = model.latest_year_test;
    if (latest && Number.isInteger(latest.year)) {
      const rows = [];
      if (Number.isFinite(latest.test_mae_c)) rows.push(['대표값 평균절대오차(MAE)', latest.test_mae_c.toFixed(3) + '°C']);
      if (Number.isFinite(latest.interval_coverage)) rows.push(['추정 범위 관측 포함률', (latest.interval_coverage * 100).toFixed(2) + '%']);
      if (Number.isFinite(latest.bias_c)) rows.push(['평균 편향(추정값 − 관측값)', latest.bias_c.toFixed(3) + '°C']);
      if (rows.length) body.append(table(['최근 시험연도 평가', '실측 성능'], rows, periodText(latest.period) + ' · ' + latest.year + '년의 한계'));
      body.append(el('p', 'climate-footnote', '최근 시험연도에는 기온을 관측값보다 낮게 추정하는 경향이 있었습니다. 음의 편향은 관측값보다 낮게 추정했다는 뜻입니다.'));
    }
    body.append(el('p', 'climate-footnote', '기준통계보다 정확도가 향상됐다는 뜻은 아닙니다. 포함률은 과거 평가 구간에서 확인한 값이며, 다음 여행일의 기온을 보장하지 않습니다.'));
    const notes = el('ul');
    for (const note of data.limitations || []) if (str(note)) notes.append(el('li', '', note));
    if (notes.children.length) body.append(notes);
    const url = safeSource(source.url);
    if (url) { const a = el('a', 'climate-source', '제주데이터허브 877 원자료 안내 ↗'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; body.append(a); }
    details.append(body); return details;
  }
  function render(data, request) {
    const selected = data.selected, name = state.stations.find(row => row.id === request.station).name;
    const top = el('div', 'climate-result-heading');
    top.append(el('div', '', undefined), el('span', 'climate-period', '관측 ' + periodText(data.reference_period)));
    top.children[0].append(el('p', 'climate-kicker', request.month + '월 ' + request.day + '일 · 과거 계절 참고'), el('h3', '', name + ' 관측 지점'));
    const hero = el('article', 'climate-summary');
    const value = el('div', 'climate-value'); value.append(el('span', '', '대표 일평균기온'), el('strong', '', temp(selected.point_c)));
    const range = el('div', 'climate-range'); range.append(el('span', '', '일평균기온 10~90백분위 추정 범위'), el('strong', '', temp(selected.lower_c) + ' ~ ' + temp(selected.upper_c)), el('p', '', '하루의 최저·최고기온이 아닙니다. 과거 일평균기온 분포의 중간 80%에 해당하는 범위를 추정합니다.'));
    hero.append(value, range);
    const comparison = el('article', 'climate-panel'); comparison.append(el('h3', '', '같은 날짜, 네 관측 지점 비교'), el('p', 'climate-footnote', '관측소 주변의 과거 계절 특성입니다. 관광지별 고도·해안·실내외 환경의 차이를 반영하지 않습니다.'));
    comparison.append(table(['관측 지점', '대표 일평균기온', '10~90백분위 추정 범위'], data.estimates.map(row => [state.stations.find(item => item.id === row.station).name + (row.station === request.station ? ' · 선택' : ''), temp(row.point_c), temp(row.lower_c) + ' ~ ' + temp(row.upper_c)]), request.month + '월 ' + request.day + '일의 과거 일평균기온 참고'));
    const season = el('article', 'climate-panel'); season.append(el('h3', '', name + '의 계절 흐름'), el('p', 'climate-footnote', '아래 그래프는 선택한 날짜와 별도로, 매월 15일의 대표값과 분포 범위를 비교합니다.'));
    const legend = el('div', 'climate-legend'); legend.append(el('span', 'climate-legend-point', '대표 일평균기온'), el('span', 'climate-legend-band', '10~90백분위 추정 범위'));
    const plot = el('div', 'climate-chart-scroll'); plot.setAttribute('tabindex', '0'); plot.setAttribute('role', 'region'); plot.setAttribute('aria-label', '계절 기온 그래프. 작은 화면에서는 좌우로 이동할 수 있으며, 아래에 같은 수치의 표가 있습니다.'); plot.append(seasonChart(data.seasonality)); season.append(legend, plot);
    const values = el('details', 'climate-details climate-chart-values'); values.append(el('summary', '', '계절 그래프의 수치를 표로 보기'), table(['기준일', '대표 일평균기온', '10~90백분위 추정 범위'], data.seasonality.map(row => [row.month + '월 15일', temp(row.point_c), temp(row.lower_c) + ' ~ ' + temp(row.upper_c)]), name + ' 관측 지점 · 매월 15일의 모델 수치')); season.append(values);
    const latest = data.model?.latest_year_test;
    const recentNote = latest && Number.isFinite(latest.interval_coverage) ? '최근 시험연도(' + latest.year + '년 1~10월)의 범위 관측 포함률은 ' + (latest.interval_coverage * 100).toFixed(1) + '%로 낮았습니다. 과거 계절 경향 참고용입니다.' : '최근 연도의 기온 변화를 충분히 반영하지 못할 수 있습니다. 과거 계절 경향 참고용입니다.';
    result.replaceChildren(top, hero, el('p', 'climate-recent-limit', recentNote), el('p', 'climate-boundary', '현재·미래의 기상 예보가 아닙니다. 옷차림과 여행 시기를 비교하는 과거 계절 참고용이며, 여행 직전의 예보와 현장 상황을 별도로 확인하세요.'), comparison, season, modelDetails(data));
  }
  async function readJSON(url, signal) {
    const response = await fetch(url, {credentials: 'same-origin', signal});
    const data = await response.json();
    if (!response.ok) throw new Error(str(data.error) || '기후 참고 자료를 불러오지 못했습니다.');
    return data;
  }
  async function loadReference() {
    if (!state.ready || !state.active) return;
    const request = {month: Number(month.value), day: Number(day.value), station: station.value};
    if (!Number.isInteger(request.month) || request.month < 1 || request.month > 12 || !Number.isInteger(request.day) || request.day < 1 || request.day > days[request.month - 1] || !state.stations.some(row => row.id === request.station)) {
      clearResult(); setStatus('올바른 월·일과 관측 지점을 골라 주세요.', true); return;
    }
    clearResult(); const serial = state.serial, controller = new AbortController(); state.controller = controller;
    busy(true); setStatus('과거 관측으로 학습한 계절 참고 값을 확인하고 있어요.');
    try {
      const data = await readJSON('/api/climate-reference?' + new URLSearchParams(request), controller.signal);
      if (serial !== state.serial || !state.active) return;
      validate(data, request); render(data, request);
      setStatus(request.month + '월 ' + request.day + '일의 과거 계절 참고입니다. 현재 날씨와 다를 수 있어요.');
    } catch (error) {
      if (serial !== state.serial || !state.active) return;
      result.replaceChildren(); setStatus(str(error.message) || '자료를 확인하지 못했어요. 다시 시도해 주세요.', true); retry.hidden = false;
    } finally {
      if (serial === state.serial) { state.controller = null; result.setAttribute('aria-busy', 'false'); submit.disabled = !state.ready; }
    }
  }
  async function initialize() {
    if (!state.active) return;
    clearResult(); const serial = state.serial, controller = new AbortController(); state.controller = controller;
    busy(true); setStatus('공개 관측 자료와 모델 상태를 확인하고 있어요.');
    try {
      const data = await readJSON('/api/climate-status', controller.signal);
      if (serial !== state.serial || !state.active) return;
      if (data.schema_version !== 1 || data.available !== true || data.ml_applied !== true) throw new Error('검증된 기후 참고 모델을 지금 사용할 수 없습니다.');
      state.stations = stationRows(data.stations);
      const defaults = data.default_request || {};
      if (!Number.isInteger(defaults.month) || defaults.month < 1 || defaults.month > 12 || !Number.isInteger(defaults.day) || defaults.day < 1 || defaults.day > days[defaults.month - 1] || !state.stations.some(row => row.id === defaults.station)) throw new Error('기본 비교 날짜를 확인할 수 없습니다.');
      station.replaceChildren();
      for (const row of state.stations) { const option = el('option', '', row.name); option.value = row.id; station.append(option); }
      month.value = String(defaults.month); dayOptions(defaults.day); station.value = defaults.station;
      month.disabled = day.disabled = station.disabled = false; state.ready = true;
      await loadReference();
    } catch (error) {
      if (serial !== state.serial || !state.active) return;
      state.ready = false; result.replaceChildren(); setStatus(str(error.message) || '모델 상태를 확인하지 못했어요.', true); retry.hidden = false; submit.disabled = true;
    } finally {
      if (serial === state.serial) { state.controller = null; result.setAttribute('aria-busy', 'false'); }
    }
  }
  function activate() {
    if (state.active) return;
    state.active = true;
    if (state.ready) loadReference(); else initialize();
  }
  function deactivate() { state.active = false; clearResult(); setStatus('월·일과 관측 지점을 골라 과거 계절을 비교해 보세요.'); }
  for (let i = 1; i <= 12; i += 1) { const option = el('option', '', i + '월'); option.value = String(i); month.append(option); }
  month.value = '4'; dayOptions(15);
  month.disabled = day.disabled = station.disabled = submit.disabled = true;
  month.addEventListener('change', () => { dayOptions(); clearResult(); setStatus('선택이 바뀌었어요. 계절 참고 보기를 눌러 주세요.'); });
  for (const field of [day, station]) field.addEventListener('change', () => { clearResult(); setStatus('선택이 바뀌었어요. 계절 참고 보기를 눌러 주세요.'); });
  form.addEventListener('submit', event => { event.preventDefault(); return loadReference(); });
  retry.addEventListener('click', () => state.ready ? loadReference() : initialize());
  global.addEventListener('jeju:pagechange', event => { if (event.detail?.path === '/climate') activate(); else deactivate(); });
  global.addEventListener('pagehide', deactivate);
  global.addEventListener('jeju:reset', () => { deactivate(); state.ready = false; month.disabled = day.disabled = station.disabled = submit.disabled = true; if (global.JejuPages?.getPath() === '/climate' || global.location.pathname === '/climate') activate(); });
  if (global.location.pathname.replace(/\/$/, '') === '/climate') activate();
})(window);
