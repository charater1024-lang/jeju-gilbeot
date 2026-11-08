(() => {
  'use strict';
  const form = document.getElementById('data-guide-form');
  if (!form) return;
  const byId = id => document.getElementById(id);
  const query = byId('guide-query'), day = byId('guide-date'), month = byId('guide-month');
  const duration = byId('guide-duration'), result = byId('guide-result'), status = byId('guide-status');
  const tabs = [...document.querySelectorAll('[data-guide-kind]')];
  const submit = byId('guide-submit');
  let kind = tabs[0]?.dataset.guideKind || 'dining', pending = null;
  const scopes = {
    route: '과거 통계 노선코드별 하루 승차 집계에서 학습한 요일 참고치입니다. 현재 운행 노선·차량 혼잡·도착 시간을 안내하는 자료와 구분해 주세요.',
    dining: '제주 전체 세부 외식업종의 이용건수 구성비를 추정합니다. 결제 건당 금액은 과거 집계 참고치이며, 식당별 메뉴 가격과 다릅니다.',
    walk: '공개 자료의 코스 길이와 제공 소요시간을 비교합니다. 출발 전 최신 통제와 코스 접근 방법을 확인해 주세요.',
    beach: '해변별 시설 수와 규모의 과거 기록을 비교합니다. 현재 시설 운영 여부와 빈 주차면은 방문 전에 확인해 주세요.',
    accessible: '접근성 자료에 기록된 위치와 설명을 확인합니다. 이용할 구간의 현재 노면·출입구·시설 상태는 운영기관에 확인해 주세요.',
    amenity: '공공자료의 편의시설 위치와 기준일을 확인합니다. 현재 영업·충전 가능 여부는 운영기관의 최신 안내가 필요합니다.'
  };
  function node(tag, text, cls) {
    const el = document.createElement(tag);
    if (text !== undefined && text !== null) el.textContent = String(text);
    if (cls) el.className = cls;
    return el;
  }
  function cancel() { if (pending) pending.controller.abort(); pending = null; submit.disabled = false; }
  function select(next) {
    cancel(); kind = next; result.replaceChildren(); status.textContent = ''; query.value = '';
    for (const tab of tabs) tab.setAttribute('aria-pressed', String(tab.dataset.guideKind === kind));
    if (day) { byId('guide-date-field').hidden = kind !== 'route'; day.required = kind === 'route'; }
    byId('guide-month-field').hidden = kind !== 'dining';
    byId('guide-duration-field').hidden = kind !== 'walk';
    byId('guide-query-label').textContent = kind === 'route' ? '원자료 통계 노선코드 (비우면 주요 기록 비교)' : kind === 'dining' ? '세부 업종 또는 중분류 (선택)' : '코스·장소·시설 이름이나 특징 (선택)';
    query.placeholder = kind === 'route' ? '예: 202-14' : kind === 'dining' ? '예: 한식' : kind === 'walk' ? '예: 올레' : kind === 'beach' ? '예: 협재' : '';
    byId('guide-scope').textContent = scopes[kind];
  }
  function disclosure(label, cls = 'data-guide-detail') {
    const details = node('details', null, cls);
    details.append(node('summary', label));
    return details;
  }
  function metric(entry) {
    const cell = node('div', null, 'data-guide-metric');
    cell.append(node('strong', entry.value), node('span', entry.label));
    return cell;
  }
  function sourceRow(source) {
    const row = node('p', null, 'data-guide-source');
    let url; try { url = new URL(source.url); } catch { url = null; }
    if (url && url.protocol === 'https:') {
      const link = node('a', source.name || '자료 원문'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link);
    } else row.append(node('span', source.name || '자료'));
    if (source.source_date) row.append(node('span', ` · 자료 기준 ${source.source_date}`));
    return row;
  }
  function knownCell(value) {
    const cell = node('td');
    const lines = String(value ?? '확인 자료 없음').split('\n').filter(Boolean);
    const priority = kind === 'walk' ? /거리\(km\)|제공 소요시간|^구간/ : kind === 'beach' ? /화장실|샤워장|주차규모/ : /시설유형|주소|명부/;
    const main = lines.filter(line => priority.test(line)).slice(0, 3);
    if (!main.length) main.push(...lines.slice(0, 3));
    const rest = lines.filter(line => !main.includes(line));
    cell.append(node('p', main.join('\n'), 'data-guide-known'));
    if (rest.length) {
      const details = disclosure(`기록 항목 ${rest.length}개 더 보기`, 'data-guide-row-detail');
      details.append(node('p', rest.join('\n'), 'data-guide-evidence'));
      cell.append(details);
    }
    return cell;
  }
  function visibleContext(box, data, records) {
    const notes = (data.notes || []).filter(note => typeof note === 'string');
    const dates = [...new Set((data.sources || []).map(source => source.source_date).filter(Boolean))];
    if (!dates.length && !['route', 'dining'].includes(kind)) {
      dates.push(...new Set(records.map(row => row[2]).filter(Boolean)));
    }
    const important = notes.filter(note => /^학습 원자료 관측 기간|^오차 평가 기간/.test(note));
    if (dates.length) important.push(`자료 기준 ${dates.join(' · ')}`);
    const coverage = notes.find(note => /평가는.*(?:관측|셀).*%/.test(note));
    if (coverage) important.push(coverage);
    const partial = notes.find(note => /올레.*19|미리보기.*코스|전 코스 목록/.test(note));
    if (partial) important.push(partial);
    if (kind === 'walk' && notes.some(note => /시간.*배편|배편.*시간/.test(note))) important.push('코스 소요시간은 출발지 이동·복귀·배편을 포함하지 않습니다.');
    if (kind === 'dining') {
      const top = (data.metrics || []).find(entry => /상위\s*10/.test(entry.label));
      if (top) important.push(`${top.label} · ${top.value}. 소규모 업종이 많아 전체 평균오차와 함께 확인해 주세요.`);
    }
    for (const text of [...new Set(important)]) box.append(node('p', text, 'data-guide-context'));
  }
  function foodQueryForCategory(value) {
    if (typeof value !== 'string') return null;
    const category = value.trim();
    if (category.length < 2 || category.length > 80) return null;
    const words = {
      '커피전문점': '커피', '일반한식/백반': '한식', '중국음식': '중식',
      '제과점': '빵', '패스트푸드': '햄버거', '라면김밥분식': '분식',
      '아이스크림/빙수': '아이스크림', '국수/만두/칼국수': '국수',
      '해장국/감자탕': '해장국'
    };
    return words[category] || category;
  }
  function render(data) {
    result.replaceChildren();
    const box = node('section', null, 'data-guide-result');
    box.append(node('h3', data.title || '제주 자료 비교'));
    if (data.summary) box.append(node('p', data.summary));
    const records = Array.isArray(data.rows) ? data.rows.filter(Array.isArray).slice(0, 30) : [];
    visibleContext(box, data, records);
    const allMetrics = Array.isArray(data.metrics) ? data.metrics : [];
    if (allMetrics.length) {
      const metrics = node('div', null, 'data-guide-metrics');
      const tolerance = allMetrics.find(entry => /이내/.test(entry.label));
      const primary = [allMetrics[0], tolerance || allMetrics[1]].filter((entry, i, values) => entry && values.indexOf(entry) === i);
      for (const entry of primary) metrics.append(metric(entry));
      box.append(metrics, node('p', '과거 평가 결과입니다. 허용오차 내 비율은 개인별 추천 정확도와 구분합니다.', 'data-guide-note'));
      const remaining = allMetrics.filter(entry => !primary.includes(entry));
      if (remaining.length) {
        const details = disclosure('평가 지표 전체 보기', 'data-guide-detail data-guide-evaluation');
        const additional = node('div', null, 'data-guide-metrics');
        for (const entry of remaining) additional.append(metric(entry));
        details.append(additional);
        box.append(details);
      }
    }
    if (records.length) {
      const scroll = node('div', null, 'data-guide-table'); scroll.tabIndex = 0;
      const table = node('table'), head = node('thead'), headers = node('tr'), body = node('tbody');
      const columns = Array.isArray(data.columns) ? data.columns : [];
      const contextRows = columns[3] === '설명과 확인할 내용';
      table.setAttribute('aria-label', data.title || '자료 비교');
      body.id = 'guide-table-rows';
      for (const label of columns) { const cell = node('th', label); cell.scope = 'col'; headers.append(cell); }
      head.append(headers);
      const rows = [];
      for (const values of records) {
        const row = node('tr');
        for (let index = 0; index < values.length; index++) {
          const value = values[index];
          if (contextRows && index === 1) row.append(knownCell(value));
          else if (contextRows && index === 3) {
            const cell = node('td');
            const details = disclosure('원문·확인사항', 'data-guide-row-detail');
            details.append(node('p', value ?? '확인 자료 없음', 'data-guide-evidence'));
            const sources = (data.sources || []).filter(source => source.source_date === values[2]);
            for (const source of sources) details.append(sourceRow(source));
            cell.append(details); row.append(cell);
          } else {
            const cell = node('td', value ?? '확인 자료 없음');
            const foodQuery = kind === 'dining' && index === 0 ? foodQueryForCategory(value) : null;
            if (foodQuery) {
              const find = node('button', '관련 음식점 찾기', 'place-map-button data-guide-food-link');
              find.type = 'button';
              find.setAttribute('aria-label', `${value} 관련 음식점 찾기`);
              find.addEventListener('click', () => {
                const opened = window.JejuExplore?.searchFoodFromQuery?.(foodQuery);
                status.textContent = opened
                  ? `‘${value}’의 관련 음식점 검색을 열었어요. 업종 비중은 개별 음식점의 인기·메뉴를 뜻하지 않습니다.`
                  : '지금은 음식점 검색을 열지 못했어요. 지도·먹거리에서 관심 음식을 직접 입력해 주세요.';
              });
              cell.append(find);
            }
            row.append(cell);
          }
        }
        row.hidden = rows.length >= 5;
        rows.push(row); body.append(row);
      }
      table.append(head, body); scroll.append(table); box.append(scroll);
      const count = node('p', `${Math.min(records.length, 5)} / ${records.length}개 표시`, 'data-guide-count');
      count.setAttribute('role', 'status');
      box.append(count);
      if (records.length > 5) {
        let expanded = false;
        const more = node('button', `나머지 ${records.length - 5}개 보기`, 'data-guide-more');
        more.type = 'button'; more.setAttribute('aria-expanded', 'false'); more.setAttribute('aria-controls', body.id);
        more.addEventListener('click', () => {
          expanded = !expanded;
          rows.forEach((row, index) => { row.hidden = !expanded && index >= 5; });
          more.textContent = expanded ? '처음 5개만 보기' : `나머지 ${records.length - 5}개 보기`;
          more.setAttribute('aria-expanded', String(expanded));
          count.textContent = `${expanded ? records.length : 5} / ${records.length}개 표시`;
        });
        box.append(more);
      }
    } else { box.append(node('p', data.empty_message || '조건에 맞는 기록이 없습니다. 이름이나 시간 조건을 바꿔 주세요.', 'data-guide-empty')); }
    const notes = (data.notes || []).filter(note => typeof note === 'string');
    const sources = Array.isArray(data.sources) ? data.sources : [];
    if (notes.length || sources.length) {
      const detail = disclosure(`자료 해석·출처 ${sources.length}건`, 'data-guide-detail data-guide-provenance');
      for (const note of notes) detail.append(node('p', note, 'data-guide-evidence'));
      for (const source of sources) detail.append(sourceRow(source));
      box.append(detail);
    }
    result.append(box);
  }
  async function load(event) {
    event.preventDefault(); cancel(); result.replaceChildren();
    const job = {controller: new AbortController()}; pending = job; submit.disabled = true; status.textContent = '자료를 비교하고 있어요.';
    const params = new URLSearchParams({kind, query: query.value.trim()});
    if (kind === 'route' && day) params.set('date', day.value);
    if (kind === 'dining') params.set('month', month.value);
    if (kind === 'walk' && duration.value) params.set('max_minutes', duration.value);
    const timeout = setTimeout(() => job.controller.abort(), 30000);
    try {
      const response = await fetch(`/api/data-guide?${params}`, {cache: 'no-store', signal: job.controller.signal});
      const data = await response.json(); if (pending !== job) return;
      if (!response.ok) throw new Error(data.error || '자료를 불러오지 못했습니다.');
      render(data); status.textContent = data.status === 'unavailable' ? '이 자료는 아직 서비스에 연결되지 않았습니다.' : data.status === 'unsupported' ? '지원하는 조건을 확인해 주세요.' : '핵심 결과를 먼저 보여드려요. 상세 근거는 항목을 펼쳐 확인할 수 있습니다.';
    } catch (error) {
      if (pending !== job) return;
      status.textContent = error.name === 'AbortError' ? '응답을 기다리는 시간이 길어졌습니다. 다시 시도해 주세요.' : error.message;
    } finally { clearTimeout(timeout); if (pending === job) { pending = null; submit.disabled = false; } }
  }
  const now = new Date(), parts = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(now);
  const part = type => parts.find(value => value.type === type).value;
  if (day) day.value = `${part('year')}-${part('month')}-${part('day')}`;
  for (let value = 1; value <= 12; value++) { const option = node('option', `${value}월`); option.value = String(value); month.append(option); }
  month.value = String(Number(part('month')));
  for (const tab of tabs) tab.addEventListener('click', () => select(tab.dataset.guideKind));
  window.JejuDataGuide = Object.freeze({
    openDining() {
      if (kind !== 'dining') select('dining');
      const target = byId('data-guide');
      window.JejuPages?.reveal(target);
      target?.scrollIntoView?.({behavior: 'smooth', block: 'start'});
      query.focus?.({preventScroll: true});
      return true;
    }
  });
  form.addEventListener('submit', load);
  for (const control of [query, day, month, duration].filter(Boolean)) control.addEventListener('input', () => { cancel(); result.replaceChildren(); status.textContent = ''; });
  window.addEventListener('jeju:reset', () => {
    form.reset();
    if (day) day.value = `${part('year')}-${part('month')}-${part('day')}`;
    month.value = String(Number(part('month')));
    select(tabs[0]?.dataset.guideKind || 'dining');
  });
  window.addEventListener('pagehide', cancel);
  select(kind);
})();
