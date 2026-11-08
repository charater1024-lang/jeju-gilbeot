(function (global) {
  'use strict';
  const host = document.getElementById('hub-insights');
  if (!host) return;
  const nf = new Intl.NumberFormat('ko-KR');
  const state = {loaded: false, serial: 0};
  const $ = id => document.getElementById(id);
  const text = value => typeof value === 'string' ? value : '';
  const count = value => Number.isFinite(value) && value >= 0 ? nf.format(Math.round(value)) : '관측 없음';
  function el(tag, cls, content) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (content !== undefined) node.textContent = content;
    return node;
  }
  function safeSource(raw) {
    try { const u = new URL(raw); return u.protocol === 'https:' && u.hostname === 'www.jejudatahub.net' ? u.href : null; }
    catch { return null; }
  }
  function options(select, rows, selected) {
    select.replaceChildren();
    for (const row of rows) {
      const option = el('option', '', row.name);
      option.value = row.key; select.append(option);
    }
    if (rows.some(row => row.key === selected)) select.value = selected;
  }
  function periodLabel(period) { return period && period.start_month && period.end_month ? period.start_month + ' — ' + period.end_month : '관측 기간 확인'; }
  function sourceDetails(data) {
    const details = el('details', 'hub-details'), summary = el('summary', '', '자료 출처와 해석 범위 확인');
    details.append(summary);
    const list = el('ul');
    for (const note of data.limitations || []) list.append(el('li', '', text(note)));
    details.append(list);
    for (const source of data.sources || []) {
      const url = safeSource(source.url);
      if (!url) continue;
      const p = el('p'), a = el('a', '', '제주데이터허브 ' + String(source.id || '') + ' 원문 ↗');
      a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; p.append(a); details.append(p);
    }
    return details;
  }
  function heading(data, selected) {
    const top = el('div', 'hub-result-top'), title = el('div');
    title.append(el('h3', '', selected.name));
    title.append(el('p', '', '월별 입장객 관측 통계 · 현재 혼잡도와 다릅니다.'));
    top.append(title, el('span', 'hub-period', periodLabel(data.period || data.source_period)));
    return top;
  }
  function historyTable(rows) {
    const details = el('details', 'hub-details'); details.append(el('summary', '', '월별 실제 관측값 펼쳐 보기'));
    const wrap = el('div', 'hub-table-wrap'), table = el('table', 'hub-table'), head = el('thead'), hr = el('tr');
    hr.append(el('th', '', '관측 월'), el('th', '', '입장객 수(명)')); head.append(hr); table.append(head);
    const body = el('tbody');
    for (const row of [...rows].reverse()) { const tr = el('tr'); tr.append(el('td', '', row.month), el('td', '', count(row.count))); body.append(tr); }
    table.append(body); wrap.append(table); details.append(wrap); return details;
  }
  function drawVisitor(data, result) {
    const selected = data.selected;
    options($('hub-place'), data.places || data.items || [], selected.key);
    result.append(heading(data, selected));
    const grid = el('div', 'hub-card-grid'), calendarCard = el('article', 'hub-card'), observedCard = el('article', 'hub-card');
    calendarCard.append(el('h4', '', '월별 평균 입장객 수'), el('p', '', periodLabel(selected.seasonality_period) + '의 같은 달을 평균했습니다. 월별 표본 수는 막대에서 확인할 수 있습니다.'));
    const calendar = el('div', 'hub-calendar'), months = selected.seasonality || [];
    const max = Math.max(0, ...months.map(row => Number.isFinite(row.mean) ? row.mean : 0));
    for (const row of months) {
      const item = el('div', 'hub-month' + (max > 0 && row.mean === max ? ' highest' : ''));
      const short = Number.isFinite(row.mean) ? row.mean >= 10000 ? (row.mean / 10000).toFixed(1) + '만' : count(row.mean) : '—';
      item.append(el('b', '', short));
      const track = el('div', 'hub-bar-track'), bar = el('i');
      bar.style.setProperty('--bar-height', (max > 0 && Number.isFinite(row.mean) ? Math.max(0, row.mean / max * 100) : 0) + '%');
      item.title = row.month + '월 · 평균 ' + count(row.mean) + '명 · ' + row.count_years + '개 연도';
      track.append(bar); item.append(track, el('span', '', row.month + '월')); calendar.append(item);
    }
    calendarCard.append(calendar, el('p', 'hub-footnote', '과거 관측 평균입니다. 코로나19 시기와 집계 대상 변동이 포함되며, 미래 방문객 예측이 아닙니다.'));
    const series = selected.monthly_series || [], latest = series.at(-1);
    observedCard.append(el('h4', '', '가장 최근 공개 관측'));
    const metrics = el('div', 'hub-metrics'), value = el('div');
    value.append(el('strong', '', latest ? count(latest.count) + '명' : '관측 없음'), el('span', '', latest ? latest.month + ' · ' + (data.audience === 'foreign' ? '외국인' : '내국인') : ''));
    metrics.append(value); observedCard.append(metrics, el('p', 'hub-footnote', '현재 시점의 인원이나 영업 여부를 나타내지 않습니다.'));
    const forecast = selected.forecast || {};
    if (forecast.available && Number.isFinite(forecast.count)) {
      observedCard.append(el('p', 'hub-notice', forecast.as_of_month + ' 자료 기준 다음 달(' + forecast.month + ') 추정 ' + count(forecast.count) + '명. 현재 시점의 예측이 아닙니다.'));
    } else {
      observedCard.append(el('p', 'hub-notice', '입장객 예측은 운영 미적용 · 새 학습 모델이 사전 성능 기준을 통과하지 못해 관측 통계만 제공합니다.'));
    }
    const guide = el('button', 'place-map-button', '이 관광지의 공식 소개 찾기 ↗');
    guide.type = 'button'; guide.dataset.hubGuide = selected.name; observedCard.append(guide);
    grid.append(calendarCard, observedCard); result.append(grid, historyTable(series), sourceDetails(data));
  }
  async function load() {
    const serial = ++state.serial, result = $('hub-visitor-result');
    result.setAttribute('aria-busy', 'true'); result.replaceChildren(el('p', 'hub-footnote', '출처와 관측 자료를 확인하고 있어요.'));
    const params = {place: $('hub-place').value, audience: $('hub-audience').value};
    try {
      const response = await fetch('/api/hub-visitor-patterns?' + new URLSearchParams(params));
      const data = await response.json();
      if (serial !== state.serial) return;
      if (!response.ok || data.kind !== 'visitor' || !data.available || !data.selected) throw new Error(data.error || data.reason || '이 자료를 지금 확인할 수 없습니다.');
      result.replaceChildren();
      drawVisitor(data, result);
      state.loaded = true;
    } catch (error) {
      if (serial === state.serial) result.replaceChildren(el('p', 'hub-error', text(error.message) || '자료를 불러오지 못했어요. 잠시 후 다시 확인해 주세요.'));
    } finally {
      if (serial === state.serial) result.setAttribute('aria-busy', 'false');
    }
  }
  function activate() { if (!state.loaded) load(); }
  $('hub-visitor-form').addEventListener('submit', event => { event.preventDefault(); load(); });
  host.addEventListener('click', event => {
    const guide = event.target.closest('[data-hub-guide]');
    if (guide) {
      const input = $('official-guide-query'), form = $('official-guide-form');
      if (input) input.value = guide.dataset.hubGuide;
      global.JejuPages?.navigate('/planner#official-guide');
      if (input && form && typeof form.requestSubmit === 'function') form.requestSubmit();
    }
  });
  global.addEventListener('jeju:pagechange', event => { if (event.detail?.path === '/insights') activate(); });
  if (global.location.pathname.replace(/\/$/, '') === '/insights') activate();
  global.JejuHubInsights = Object.freeze({safeSource, count});
})(window);
