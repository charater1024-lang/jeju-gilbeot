(function () {
  'use strict';

  const panel = document.getElementById('assistant');
  if (!panel) return;
  const form = document.getElementById('assistant-form');
  const input = document.getElementById('assistant-message');
  const send = document.getElementById('assistant-send');
  const clear = document.getElementById('assistant-clear');
  const status = document.getElementById('assistant-status');
  const result = document.getElementById('assistant-response');
  const examples = Array.from(panel.querySelectorAll('[data-assistant-example]'));
  let state = null;
  let lastOriginChoice = null;
  let pending = null;

  function element(tag, value, className) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (typeof value === 'string') node.textContent = value;
    return node;
  }

  function list(value, limit = 8) {
    return Array.isArray(value) ? value.slice(0, limit) : [];
  }

  function notes(values) {
    const entries = list(values, 100).filter(value => typeof value === 'string' && value.trim());
    if (!entries.length) return null;
    const group = element('ul', null, 'assistant-notes');
    for (const text of entries) group.append(element('li', text));
    return group;
  }

  function disclosure(label) {
    const details = element('details', null, 'assistant-details');
    details.open = false;
    details.append(element('summary', label));
    return details;
  }

  function sourceDate(source) {
    const date = source?.checked_at || source?.source_date || source?.retrieved_at;
    return typeof date === 'string' ? date : '';
  }

  function preview(container, entries, count, noun) {
    const caption = element('p', null, 'assistant-note');
    const remaining = entries.slice(count);
    let expanded = false;
    function update() {
      for (const entry of remaining) entry.hidden = !expanded;
      caption.textContent = expanded ? `${entries.length}${noun} 전체 표시` : `${entries.length}${noun} 중 ${Math.min(count, entries.length)}${noun} 먼저 표시`;
    }
    update();
    container.append(caption);
    if (remaining.length) {
      const toggle = button(`${entries.length}${noun} 전체 보기`, () => {
        expanded = !expanded;
        update();
        toggle.textContent = expanded ? `${count}${noun}만 보기` : `${entries.length}${noun} 전체 보기`;
        toggle.setAttribute('aria-expanded', String(expanded));
      });
      toggle.setAttribute('aria-expanded', 'false');
      container.append(toggle);
    }
  }

  function analysisCell(value) {
    const cell = element('td');
    const text = typeof value === 'string' ? value : '–';
    if (text.length <= 180) {
      cell.textContent = text;
    } else {
      const warning = text.split('확인 필요 · ')[1];
      if (warning) cell.append(element('p', `확인 필요 · ${warning}`, 'assistant-note'));
      const detail = disclosure('기록 원문 보기');
      detail.append(element('p', text, 'assistant-evidence'));
      cell.append(detail);
    }
    return cell;
  }

  function linkFor(value) {
    if (typeof value !== 'string' || !/^https?:\/\//i.test(value)) return null;
    try {
      const url = new URL(value);
      return url.username || url.password ? null : url.href;
    } catch {
      return null;
    }
  }

  function addSource(container, source, dateLabel = '자료 기준') {
    if (!source || typeof source !== 'object') return;
    const name = source.name || source.source_name || source.label;
    if (typeof name !== 'string' || !name) return;
    const row = element('p', null, 'assistant-source');
    const href = linkFor(source.url || source.source_url);
    if (href) {
      const link = element('a', `${name} ↗`);
      link.href = href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      row.append(link);
    } else {
      row.append(element('span', name));
    }
    const date = source.checked_at || source.source_date || source.retrieved_at;
    if (typeof date === 'string' && date) row.append(element('span', ` · ${dateLabel} ${date}`));
    container.append(row);
  }

  function button(label, handler, primary = false) {
    const node = element('button', label, primary ? 'button button-blue' : 'assistant-link');
    node.type = 'button';
    node.dataset.assistantAction = 'true';
    node.disabled = Boolean(pending);
    node.addEventListener('click', handler);
    return node;
  }

  function clock(value) {
    if (!Number.isInteger(value) || value < 0 || value > 1440) return '';
    return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
  }

  function routeSummary(route) {
    const totals = route.totals || {};
    const parts = [`방문 ${list(route.stops).length}곳`];
    if (Number.isFinite(totals.duration_minutes)) parts.push(`총 ${totals.duration_minutes}분 추정`);
    if (Number.isFinite(totals.travel_cost_krw)) parts.push(`이동비 약 ${totals.travel_cost_krw.toLocaleString('ko-KR')}원`);
    const end = clock(totals.end_arrival_minute);
    if (end) parts.push(`복귀 ${end}`);
    return parts.join(' · ');
  }

  function showRoute(route) {
    if (!route || route.data_mode !== 'reference') return;
    const box = element('section', null, 'assistant-output');
    const stops = list(route.stops);
    if (route.status === 'ok' && stops.length) {
      box.append(element('h3', '추천 방문 순서'), element('p', routeSummary(route), 'assistant-route-summary'));
      const visits = element('ol', null, 'assistant-visits');
      for (const stop of stops) {
        const item = element('li');
        item.append(element('h4', stop.name));
        const arrival = clock(stop.arrival_minute);
        const departure = clock(stop.departure_minute);
        if (arrival && departure) item.append(element('p', `${arrival}–${departure} 체류 예상`));
        const proof = list(route.selected_place_evidence).find(entry => entry.id === (stop.poi_id || stop.id)) || stop.trust;
        const sources = list(proof?.sources, 4);
        const dates = [...new Set(sources.map(sourceDate).filter(Boolean))];
        if (dates.length) item.append(element('p', `자료 기준·소개 확인 ${dates.join(' / ')}`, 'assistant-source'));
        const warnings = notes(proof?.warnings);
        if (warnings) item.append(warnings);
        if (proof?.selection_reason || stop.selection_reason || sources.length) {
          const detail = disclosure('선정 근거·출처 보기');
          if (proof?.selection_reason || stop.selection_reason) detail.append(element('p', proof?.selection_reason || stop.selection_reason));
          for (const source of sources) addSource(detail, source, source.date_kind === 'guide_review' ? '공식 소개 확인일' : '자료 기준');
          item.append(detail);
        }
        visits.append(item);
      }
      box.append(visits, element('p', '이동시간·이동비는 추정입니다. 입장료·식비·주차비와 영업시간은 방문 전에 확인해 주세요.', 'assistant-note'));
    } else {
      box.append(element('h3', '일정 조건 확인'), element('p', route.message));
    }
    const detail = notes(route.status === 'ok' ? route.warnings : route.suggestions);
    if (detail) box.append(detail);
    if (state && lastOriginChoice && ['ok', 'infeasible'].includes(route.status)) {
      box.append(button('조건을 바꾼 대안 비교', () => withOrigin('alternatives', lastOriginChoice)));
    }
    result.append(box);
  }

  function showAnalysis(analysis) {
    const columns = list(analysis?.columns, 8);
    if (!columns.length) return;
    const box = element('section', null, 'assistant-output');
    const title = analysis.title || '제주 데이터 비교';
    box.append(element('h3', title));
    const scroll = element('div', null, 'assistant-table-scroll');
    scroll.tabIndex = 0;
    scroll.setAttribute('aria-label', title);
    const table = element('table');
    table.setAttribute('aria-label', title);
    const head = element('thead');
    const headers = element('tr');
    for (const column of columns) {
      const header = element('th', column);
      header.scope = 'col';
      headers.append(header);
    }
    head.append(headers);
    const body = element('tbody');
    const records = [];
    for (const row of list(analysis.rows, 100).filter(Array.isArray)) {
      const record = element('tr');
      for (let i = 0; i < columns.length; i++) record.append(analysisCell(row[i]));
      body.append(record);
      records.push(record);
    }
    table.append(head, body);
    scroll.append(table);
    box.append(scroll);
    if (records.length > 5) preview(box, records, 5, '행');
    const allNotes = list(analysis.notes, 100).filter(value => typeof value === 'string' && value.trim());
    const visible = allNotes.filter(text => /^(학습 원자료 관측 기간|관측 기간|오차 평가 기간|결제 건당 금액의 관측 참고 기간)/.test(text)
      || / · [\d,]+(?:\.\d+)?(?:%|명\/일|퍼센트포인트)/.test(text)
      || /19코스|전 코스|배편|현재 접근성|실시간.*아닙|현재 운행.*검증|현재 운영.*미확인/.test(text));
    const summary = notes([...new Set(visible)]);
    if (summary) box.append(summary);
    const detail = disclosure('자료 출처·분석 범위 자세히 보기');
    for (const source of list(analysis.sources, 24)) addSource(detail, source);
    const remainder = notes(allNotes.filter(text => !visible.includes(text)));
    if (remainder) detail.append(remainder);
    if (detail.childElementCount > 1) box.append(detail);
    result.append(box);
  }

  function showPlaces(places) {
    const records = list(places, 24);
    if (!records.length) return;
    const box = element('section', null, 'assistant-output');
    box.append(element('h3', records.every(place => place.kind === 'food') ? '제주데이터허브 음식점 기록' : '관심사와 관련된 관광지'));
    const cards = element('div', null, 'assistant-cards');
    const entries = [];
    for (const place of records) {
      const card = element('article', null, 'assistant-card');
      card.append(element('h4', place.name));
      const details = [place.category, place.address].filter(value => typeof value === 'string' && value).join(' · ');
      if (details) card.append(element('p', details));
      const source = place.primary_source;
      const date = sourceDate(source);
      if (source?.name || date) card.append(element('p', [source?.name, date ? `자료 기준 ${date}` : ''].filter(Boolean).join(' · '), 'assistant-source'));
      const proof = disclosure('소개 근거·자료 원문 보기');
      addSource(proof, source);
      if (place.matched_evidence?.text) {
        proof.append(element('p', place.matched_evidence.text, 'assistant-evidence'));
        if (place.matched_evidence.source_url !== place.primary_source?.url || place.matched_evidence.retrieved_at) {
          addSource(proof, place.matched_evidence, '소개 확인일');
        }
      }
      if (proof.childElementCount > 1) card.append(proof);
      if (place.location_basis === 'address_only') card.append(element('p', '명부의 주소로 확인할 수 있어요.', 'assistant-note'));
      const detail = notes(place.limitations);
      if (detail) card.append(detail);
      cards.append(card);
      entries.push(card);
    }
    box.append(cards);
    if (entries.length > 3) preview(box, entries, 3, '개');
    result.append(box);
  }

  function showAlternatives(alternatives) {
    const options = list(alternatives, 4);
    if (!options.length) return;
    const box = element('section', null, 'assistant-output');
    box.append(element('h3', '조건별 대안'), element('p', '원하는 대안의 조건을 문장으로 입력해 적용할 수 있어요.', 'assistant-note'));
    const cards = element('div', null, 'assistant-cards');
    for (const option of options) {
      const card = element('article', null, 'assistant-card');
      card.append(element('h4', option.label), element('p', option.condition_change));
      if (option.route?.status === 'ok' && option.route.data_mode === 'reference') {
        card.append(element('p', routeSummary(option.route), 'assistant-route-summary'));
        card.append(element('p', list(option.route.stops).map(stop => stop.name).join(' → ')));
      } else {
        card.append(element('p', option.route?.message || '이 조건에서는 가능한 코스를 찾지 못했어요.'));
      }
      cards.append(card);
    }
    box.append(cards);
    result.append(box);
  }

  function render(response) {
    result.replaceChildren();
    result.hidden = false;
    const conditions = Object.entries(response.conditions || {}).filter(([, value]) => typeof value === 'string');
    if (conditions.length) {
      const box = element('section', null, 'assistant-output');
      const confirmed = !['needs_confirmation', 'needs_input'].includes(response.status);
      const container = confirmed ? disclosure('적용한 여행 조건 다시 보기') : box;
      if (!confirmed) box.append(element('h3', '여행 조건'));
      const summary = element('dl', null, 'assistant-conditions');
      for (const [label, value] of conditions.slice(0, 16)) {
        const item = element('div');
        item.append(element('dt', label), element('dd', value));
        summary.append(item);
      }
      container.append(summary);
      if (confirmed) box.append(container);
      result.append(box);
    }
    if (response.status === 'needs_confirmation' && state) {
      const actions = element('div', null, 'assistant-confirm-actions');
      if (typeof response.origin_candidate?.label === 'string' && response.origin_candidate.label) {
        actions.append(button(`${response.origin_candidate.label} 출발로 확인하고 계산`, () => withOrigin('confirm', 'candidate'), true));
      } else {
        const link = element('a', '출발지 직접 확인', 'assistant-link');
        link.href = '#planner-origin-title';
        actions.append(button('일정에서 확인한 출발지로 계산', () => withOrigin('confirm', 'planner'), true), link);
      }
      result.append(actions);
    }
    const detail = notes(response.suggestions);
    if (detail) result.append(detail);
    showRoute(response.route);
    showAnalysis(response.analysis);
    showPlaces(response.places);
    showAlternatives(response.alternatives);
    if (!result.childElementCount) result.hidden = true;
  }

  function busy(value) {
    send.disabled = value;
    input.disabled = value;
    for (const control of [...examples, ...result.querySelectorAll('[data-assistant-action]')]) control.disabled = value;
    result.setAttribute('aria-busy', String(value));
  }

  function reset(message = '') {
    pending?.controller.abort();
    pending = null;
    state = null;
    lastOriginChoice = null;
    form.reset();
    result.replaceChildren();
    result.hidden = true;
    status.textContent = message;
    busy(false);
  }

  async function request(payload, submittedText = '') {
    if (pending) return;
    const job = {controller: new AbortController(), originChoice: payload.origin_choice};
    pending = job;
    busy(true);
    status.textContent = '요청을 확인하고 있어요.';
    const timeout = setTimeout(() => job.controller.abort(), 30000);
    try {
      const http = await fetch('/api/assistant', {
        method: 'POST',
        cache: 'no-store',
        headers: {'Content-Type': 'application/json', Accept: 'application/json'},
        body: JSON.stringify({...payload, ...(state ? {state} : {})}),
        signal: job.controller.signal
      });
      const response = await http.json();
      if (pending !== job) return;
      if (!http.ok) throw new Error(typeof response.error === 'string' ? response.error : '요청을 처리하지 못했어요.');
      if (!response || typeof response.status !== 'string') throw new Error('응답을 확인하지 못했어요. 다시 시도해 주세요.');
      if (Object.hasOwn(response, 'state')) state = typeof response.state === 'string' && response.state.length <= 6000 ? response.state : null;
      if (payload.action === 'confirm' && response.route && state) lastOriginChoice = job.originChoice;
      if (submittedText && input.value.trim() === submittedText) input.value = '';
      status.textContent = typeof response.message === 'string' ? response.message : '요청 결과를 확인하세요.';
      render(response);
    } catch (error) {
      if (pending !== job) return;
      status.textContent = error.name === 'AbortError' ? '응답이 늦어지고 있어요. 다시 시도해 주세요.' : error.message || '서버 응답을 확인하지 못했어요.';
    } finally {
      clearTimeout(timeout);
      if (pending === job) {
        pending = null;
        busy(false);
      }
    }
  }

  function withOrigin(action, choice) {
    if (!state || pending) return;
    const payload = {action, origin_choice: choice};
    if (choice === 'planner') {
      try {
        payload.origin = window.JejuTripBridge?.getConfirmedOrigin?.();
        if (!payload.origin?.origin_confirmed) throw new Error('아래의 일정 입력에서 출발지를 먼저 확인해 주세요.');
      } catch (error) {
        status.textContent = error.message;
        return;
      }
    }
    return request(payload);
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    const message = input.value.trim();
    if (message) return request({message}, message);
  });
  for (const example of examples) example.addEventListener('click', () => {
    input.value = example.dataset.assistantExample;
    input.focus();
  });
  clear.addEventListener('click', () => {
    reset('대화를 지웠어요.');
    input.focus();
  });
  window.addEventListener('jeju:reset', () => reset());
  window.addEventListener('pagehide', () => reset());
  window.addEventListener('jeju:planneroriginchange', () => {
    if (lastOriginChoice === 'planner' || pending?.originChoice === 'planner') reset('출발지가 바뀌었어요. 여행 조건을 다시 확인해 주세요.');
  });
})();
