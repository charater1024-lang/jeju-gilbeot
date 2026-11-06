(() => {
  'use strict';

  const regions = new Set(['all', 'north', 'south', 'east', 'west']);

  function publicId(value) {
    return typeof value === 'string' && value.length <= 120 && value.trim() === value && value.length > 0;
  }

  function jejuPoint(latitude, longitude) {
    return Number.isFinite(latitude) && Number.isFinite(longitude)
      && latitude >= 32.9 && latitude <= 33.8 && longitude >= 126 && longitude <= 127.05;
  }

  function integerInRange(value, minimum, maximum) {
    return Number.isInteger(value) && value >= minimum && value <= maximum;
  }

  function dateValid(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return false;
    const utc = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(utc.getTime()) && utc.toISOString().slice(0, 10) === value;
  }

  function clockMinutes(value) {
    if (typeof value !== 'string' || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)) return null;
    return Number(value.slice(0, 2)) * 60 + Number(value.slice(3));
  }

  function clockLabel(minutes) {
    const hours = String(Math.floor(minutes / 60)).padStart(2, '0');
    const remainder = String(minutes % 60).padStart(2, '0');
    return `${hours}:${remainder}`;
  }

  function eligiblePlan(result) {
    if (result?.status !== 'ok' || result.data_mode !== 'reference' || result.selection_mode !== 'automatic') return null;
    const request = result.request;
    const stops = result.stops;
    if (!request || !dateValid(request.date) || !['car', 'walk'].includes(request.transport)
      || !jejuPoint(request.end_lat, request.end_lon)
      || !integerInRange(request.start_minute, 0, 1439)
      || !integerInRange(request.end_minute, request.start_minute + 1, 1440)
      || !integerInRange(request.budget_krw, 0, 10000000)
      || !integerInRange(request.max_stops, 1, 8)
      || typeof request.query !== 'string' || request.query.length > 100
      || !regions.has(request.region) || typeof request.include_geometry !== 'boolean'
      || !Array.isArray(request.excluded_ids) || request.excluded_ids.length > 68
      || !request.excluded_ids.every(publicId)
      || !Array.isArray(stops) || stops.length === 0 || stops.length > request.max_stops) return null;

    const byId = new Map();
    const excluded = new Set(request.excluded_ids);
    for (const stop of stops) {
      if (!publicId(stop?.poi_id) || stop.kind !== 'attraction' || stop.source_overlap_verified !== true
        || typeof stop.name !== 'string' || !stop.name.trim() || !jejuPoint(stop.latitude, stop.longitude)
        || byId.has(stop.poi_id) || excluded.has(stop.poi_id)) return null;
      byId.set(stop.poi_id, stop);
    }
    return { request, byId };
  }

  function buildRequest(result, values) {
    const plan = eligiblePlan(result);
    if (!plan) throw new Error('공개 장소가 확인된 자동 추천 일정에서 남은 코스를 다시 짤 수 있어요.');
    const { request, byId } = plan;
    const action = values?.action ?? 'continue';
    if (!['continue', 'broaden', 'return'].includes(action)) throw new Error('일정 조정 방법을 확인해 주세요.');
    const originPlaceId = values?.originPlaceId;
    if (!byId.has(originPlaceId)) throw new Error('현재 장소를 기존 추천 일정에서 골라 주세요.');
    const visitedIds = values?.visitedIds ?? [];
    if (!Array.isArray(visitedIds) || visitedIds.some(id => !byId.has(id))) {
      throw new Error('방문 완료 장소는 기존 추천 일정에서 골라 주세요.');
    }
    const startMinute = clockMinutes(values?.startTime);
    if (startMinute === null) throw new Error('남은 코스를 시작할 시각을 입력해 주세요.');
    if (startMinute < request.start_minute || startMinute >= request.end_minute) {
      throw new Error(`시작 시각은 기존 시작 ${clockLabel(request.start_minute)}부터 복귀 마감 ${clockLabel(request.end_minute)} 전까지 골라 주세요.`);
    }
    const enteredBudget = values?.remainingBudget;
    const budgetText = typeof enteredBudget === 'string' ? enteredBudget.trim() : enteredBudget;
    const budget = typeof budgetText === 'string' && /^\d+$/.test(budgetText) ? Number(budgetText) : budgetText;
    if (!integerInRange(budget, 0, request.budget_krw)) {
      throw new Error(`남은 추정 이동비는 0원부터 기존 한도 ${request.budget_krw.toLocaleString('ko-KR')}원까지 원 단위로 입력해 주세요.`);
    }

    const visited = new Set([originPlaceId, ...visitedIds]);
    const remainingStops = request.max_stops - visited.size;
    if (action !== 'return' && remainingStops <= 0) {
      throw new Error('남은 방문 수가 없어요. 도착지로 바로 가는 시간을 확인할 수 있어요.');
    }
    const excludedIds = new Set([...request.excluded_ids, ...visited]);
    if (excludedIds.size > 68) throw new Error('기존 제외와 방문 완료를 합쳐 최대 68곳까지 적용할 수 있어요.');

    return {
      origin_place_id: originPlaceId,
      origin_confirmed: true,
      origin_source: 'landmark',
      end_lat: request.end_lat,
      end_lon: request.end_lon,
      date: request.date,
      start_minute: startMinute,
      end_minute: request.end_minute,
      transport: request.transport,
      query: action === 'broaden' ? '' : request.query,
      region: action === 'broaden' ? 'all' : request.region,
      include_geometry: request.include_geometry,
      budget_krw: budget,
      max_stops: action === 'return' ? 0 : remainingStops,
      excluded_ids: [...excludedIds].sort(),
      ...(action === 'return' ? {return_only:true} : {}),
    };
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function labelField(text, control) {
    const label = element('label', undefined, 'field');
    label.append(element('span', text), control);
    return label;
  }

  function createPanel(result, { nowKST, submit } = {}) {
    const plan = eligiblePlan(result);
    if (!plan || typeof submit !== 'function') return null;
    const { request, byId } = plan;
    const panel = element('details', undefined, 'trip-replan');
    panel.append(element('summary', '여행 중 일정 다시 짜기'));

    const form = element('form', undefined, 'trip-replan-form');
    form.noValidate = true;
    form.append(element('p', `${request.date} · 기존 도착지에 ${clockLabel(request.end_minute)}까지`));
    form.append(element('p', '현재 장소로 고른 곳의 공개 자료 대표 위치에서 계산합니다. 해당 장소는 방문 완료에 포함됩니다.'));
    const fields = element('div', undefined, 'trip-replan-fields');

    const origin = element('select');
    origin.name = 'replan_origin_place_id';
    origin.required = true;
    const prompt = element('option', '현재 장소를 선택해 주세요');
    prompt.value = '';
    prompt.disabled = true;
    origin.append(prompt);
    for (const stop of byId.values()) {
      const option = element('option', stop.name);
      option.value = stop.poi_id;
      origin.append(option);
    }
    origin.value = '';
    fields.append(labelField('공개 위치를 출발 기준으로 확인할 장소', origin));

    const time = element('input');
    time.name = 'replan_start_time';
    time.type = 'time';
    time.required = true;
    time.min = clockLabel(request.start_minute);
    time.max = clockLabel(request.end_minute - 1);
    if (typeof nowKST === 'string' && nowKST.length === 16 && nowKST.startsWith(`${request.date}T`)) {
      const currentTime = nowKST.slice(11);
      const currentMinute = clockMinutes(currentTime);
      if (currentMinute !== null && currentMinute >= request.start_minute && currentMinute < request.end_minute) {
        time.value = currentTime;
      }
    }
    fields.append(labelField('다시 출발할 시각 (한국 시간)', time));

    const budget = element('input');
    budget.name = 'replan_budget_krw';
    budget.type = 'number';
    budget.required = true;
    budget.min = '0';
    budget.max = String(request.budget_krw);
    budget.step = '1';
    budget.inputMode = 'numeric';
    budget.value = '';
    fields.append(labelField('남은 추정 이동비 한도 (원)', budget));
    form.append(fields, element('p', '이동비 한도는 계획용 교통비에 적용합니다. 입장료·식사비·주차비·렌터카 비용은 별도로 확인해 주세요.'));

    const visited = element('fieldset', undefined, 'trip-replan-visited');
    visited.append(element('legend', '그 밖에 이미 방문한 장소'));
    const checks = [];
    for (const stop of byId.values()) {
      const check = element('input');
      check.type = 'checkbox';
      check.name = 'replan_visited_ids';
      check.value = stop.poi_id;
      const label = element('label');
      label.append(check, element('span', stop.name));
      visited.append(label);
      checks.push({ check, label });
    }
    const status = element('p', '', 'trip-replan-status');
    status.setAttribute('role', 'status');
    origin.addEventListener('change', () => {
      for (const { check, label } of checks) {
        check.disabled = check.value === origin.value;
        label.hidden = check.disabled;
      }
      status.textContent = '';
    });
    const actions = element('div', undefined, 'trip-replan-actions');
    const choices = request.max_stops > 1 ? [['continue', '남은 코스 다시 짜기']] : [];
    if (request.max_stops > 1 && (request.query || request.region !== 'all')) {
      choices.push(['broaden', '제주 전체에서 대체 장소 찾기']);
    }
    choices.push(['return', '기존 도착지로 바로 가기']);
    for (const [value, label] of choices) {
      const button = element('button', label, 'place-map-button');
      button.type = 'submit';
      button.value = value;
      actions.append(button);
    }
    form.append(visited, actions, status);
    form.addEventListener('input', () => {
      status.textContent = '';
      form.querySelector('.trip-replan-return-result')?.remove();
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      try {
        const replan = buildRequest(result, {
          action: event.submitter?.value,
          originPlaceId: origin.value,
          visitedIds: checks.filter(({ check }) => check.checked && !check.disabled).map(({ check }) => check.value),
          startTime: time.value,
          remainingBudget: budget.value,
        });
        status.textContent = '';
        await submit(replan, { panel, form, status });
      } catch (error) {
        status.textContent = error instanceof Error ? error.message : '남은 코스를 다시 불러오지 못했어요.';
      }
    });
    panel.append(form);
    return panel;
  }

  const api = { buildRequest, createPanel };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.JejuTripReplan = api;
})();
