(function () {
  'use strict';

  const form = document.getElementById('official-guide-form');
  if (!form) return;

  const input = document.getElementById('official-guide-query');
  const submit = document.getElementById('official-guide-submit');
  const status = document.getElementById('official-guide-status');
  const results = document.getElementById('official-guide-results');
  const officialHosts = new Set([
    'visitjeju.net', 'www.visitjeju.net', 'm.visitjeju.net', 'jejudatahub.net',
    'www.jejudatahub.net', 'korean.visitkorea.or.kr', 'english.visitkorea.or.kr',
  ]);
  let request = null;

  function element(tag, text = '', className = '') {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function sourceLink(url, label) {
    try {
      const target = new URL(url);
      if (target.protocol === 'https:' && officialHosts.has(target.hostname)
          && !target.username && !target.password && !target.port) {
        const link = element('a', `${label} ↗`);
        link.href = target.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        return link;
      }
    } catch {
      // An invalid URL can still be presented as a plain source label.
    }
    return element('span', label);
  }

  function addSource(parent, source, name, dateLabel) {
    if (!source) return;
    const line = element('p', '', 'data-guide-source');
    line.append(sourceLink(source.url || source.source_url, source.name || source.source_name || name));
    const date = source.checked_at || source.source_date || source.retrieved_at;
    if (typeof date === 'string' && date) line.append(element('span', ` · ${dateLabel} ${date}`));
    parent.append(line);
  }

  function actionButton(label, handler) {
    const button = element('button', label, 'place-map-button');
    button.type = 'button';
    button.addEventListener('click', handler);
    return button;
  }

  async function withVerifiedPoint(card, place, button, action) {
    button.disabled = true;
    status.textContent = '공개 장소 위치를 확인하고 있어요.';
    try {
      const response = await fetch(`/api/place-details?${new URLSearchParams({id: place.id})}`,
        {cache: 'no-store'});
      const data = await response.json();
      if (!card.isConnected) return;
      const item = data?.item;
      if (!response.ok || item?.id !== place.id || item.source_overlap_verified !== true
          || !Number.isFinite(item.latitude) || !Number.isFinite(item.longitude)) {
        throw new Error('교차확인 장소의 공개 좌표를 불러오지 못했어요.');
      }
      status.textContent = action(item);
    } catch (error) {
      if (card.isConnected) status.textContent = error.message || '장소 위치를 확인하지 못했어요.';
    } finally {
      button.disabled = false;
    }
  }

  function makeCard(place) {
    const card = element('article', '', 'data-guide-result');
    card.append(element('h3', place.name));
    const overview = [place.category, place.address].filter(value => typeof value === 'string' && value);
    if (overview.length) card.append(element('p', overview.join(' · '), 'data-guide-context'));
    const evidence = place.matched_evidence;
    const introduction = place.official_intro?.text || evidence?.text;
    if (typeof introduction === 'string' && introduction) {
      card.append(element('p', introduction, 'data-guide-evidence'));
    }
    const sources = Array.isArray(place.sources) ? place.sources : [];
    const guide = sources.find(source => source?.kind === 'tourism_guide');
    addSource(card, place.official_intro || guide || (evidence?.date_kind === 'guide_review' ? evidence : null), '공식 관광 안내', '소개 확인일');
    addSource(card, place.primary_source, '제주데이터허브 여행장소 명부', '명부 기준일');
    const eligible = place.automatic_eligible === true;
    if (!eligible) {
      card.append(element('p', '장소 소개를 참고할 수 있어요. 자동 코스 후보에는 포함하지 않습니다.', 'data-guide-note'));
      for (const restriction of Array.isArray(place.visit_restrictions) ? place.visit_restrictions : []) {
        if (typeof restriction?.message === 'string' && restriction.message) {
          card.append(element('p', restriction.message, 'data-guide-note'));
        }
      }
    }
    const actions = element('div', '', 'discovery-card-actions');
    actions.append(actionButton('장소 상세 보기', () => {
      window.JejuTripBridge?.openPlace(place, {allowTripAdd: eligible});
    }));
    if (eligible) {
      const mapButton = actionButton('지도에서 보기', () => withVerifiedPoint(card, place, mapButton, item => {
        window.JejuExplore?.showPlaces([item], {focus: true, label: `${item.name} 위치`});
        return `${item.name}의 공개 장소 위치를 지도에서 확인할 수 있어요.`;
      }));
      const addButton = actionButton('여행에 담기', () => withVerifiedPoint(card, place, addButton, item => {
        return window.JejuTripBridge?.addPlace(item)
          ? `${item.name}을 여행에 담았어요.`
          : '여행에 담지 못했어요. 모아둔 장소를 확인해 주세요.';
      }));
      actions.append(mapButton, addButton);
    }
    card.append(actions);
    return card;
  }

  function clearResults() {
    request?.abort();
    request = null;
    submit.disabled = false;
    status.textContent = '';
    results.replaceChildren();
  }
  input.addEventListener('input', clearResults);
  window.addEventListener('jeju:reset', () => {
    form.reset();
    clearResults();
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query || query.length > 160) {
      status.textContent = '장소명 또는 관심 주제를 160자 이내로 입력해 주세요.';
      return;
    }
    request?.abort();
    const current = new AbortController();
    request = current;
    submit.disabled = true;
    results.replaceChildren();
    status.textContent = '관광지 소개를 찾고 있어요.';
    try {
      const response = await fetch('/api/guide-search', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query, region: 'all'}),
        signal: current.signal,
      });
      const data = await response.json();
      if (request !== current) return;
      if (!response.ok) throw new Error(typeof data?.error === 'string' ? data.error : '관광지 소개를 불러오지 못했어요.');
      if (!Array.isArray(data)) throw new Error('관광지 소개 자료를 읽지 못했어요.');
      const places = data.filter(place => place?.kind === 'attraction' && place.source_status === 'cross_source_verified'
        && typeof place.id === 'string' && place.id.length > 0 && place.id.length <= 120
        && typeof place.name === 'string' && place.name.trim());
      for (const place of places) results.append(makeCard(place));
      status.textContent = places.length
        ? `소개 근거가 연결된 장소 ${places.length}곳을 찾았어요.`
        : '확인한 소개에서 일치하는 장소를 찾지 못했어요. 다른 장소명이나 주제로 찾아보세요.';
    } catch (error) {
      if (request === current) status.textContent = error.message || '관광지 소개를 불러오지 못했어요.';
    } finally {
      if (request === current) {
        request = null;
        submit.disabled = false;
      }
    }
  });
})();
