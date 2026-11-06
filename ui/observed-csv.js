(() => {
  'use strict';
  const MAX_BYTES = 8 * 1024 * 1024;
  const FIELDS = ['base_year_month', 'biz_nm', 'user_type', 'sex', 'use_count'];
  const CATEGORIES = ['한식 음식점업', '중식 음식점업', '일식 음식점업', '서양식 음식점업', '기타 외국식 음식점업', '비알콜 음료점업', '피자 햄버거 샌드위치 및 유사 음식점업', '빵 및 과자류 소매업'];
  const GROUPS = ['제주도민', '내국인'];
  const SEXES = ['남성', '여성', '알수없음'];

  function eachRecord(csv, emit) {
    let row = [], value = '', quoted = false, closed = false;
    for (let i = 0; i < csv.length; i++) {
      const ch = csv[i];
      if (quoted) {
        if (ch !== '"') value += ch;
        else if (csv[i+1] === '"') { value += '"'; i++; }
        else { quoted = false; closed = true; }
      } else if (ch === '"' && !closed && value.length === 0) {
        quoted = true;
      } else if (ch === ',' || ch === '\r' || ch === '\n') {
        row.push(value); value = ''; closed = false;
        if (ch !== ',') {
          if (row.length !== 1 || row[0] !== '') emit(row);
          row = [];
          if (ch === '\r' && csv[i+1] === '\n') i++;
        }
      } else if (ch === '"' || closed) {
        throw new Error('CSV의 따옴표나 열 구분을 확인해 주세요.');
      } else value += ch;
    }
    if (quoted) throw new Error('닫히지 않은 따옴표가 있는 CSV입니다.');
    if (row.length || value.length || closed) emit([...row, value]);
  }

  function decode(bytes) {
    try { return new TextDecoder('utf-8', {fatal:true}).decode(bytes); }
    catch {
      try { return new TextDecoder('euc-kr', {fatal:true}).decode(bytes); }
      catch { throw new Error('UTF-8 또는 한글 CSV로 저장한 뒤 다시 선택해 주세요.'); }
    }
  }

  function parseHub1048(bytes) {
    if (!bytes.byteLength || bytes.byteLength > MAX_BYTES) throw new Error('8MB 이하의 1048 CSV를 선택해 주세요.');
    const panels = new Map(), months = new Set();
    let header = null, positions, used = 0;
    eachRecord(decode(bytes), row => {
      if (!header) {
        header = row;
        positions = FIELDS.map(name => header.indexOf(name));
        if (positions.some(i => i < 0) || new Set(header).size !== header.length) {
          throw new Error('1048의 월·업종·집단·성별·이용건수 열이 있는 원본 CSV를 선택해 주세요.');
        }
        return;
      }
      if (row.length !== header.length) throw new Error('CSV 열 개수가 머리글과 다른 행이 있습니다.');
      const [month, category, group, sex, rawCount] = positions.map(i => row[i]);
      if (!GROUPS.includes(group) || !CATEGORIES.includes(category)) return;
      if (!/^(?:19|20|21)\d{2}(?:0[1-9]|1[0-2])$/.test(month) || !SEXES.includes(sex)) {
        throw new Error('월 형식(YYYYMM)과 성별 분류를 확인해 주세요.');
      }
      if (/^(?:|NA)$/i.test(rawCount.trim())) {
        throw new Error('대상 집단·업종에 이용건수 결측이 있습니다. 결측을 0으로 처리하지 않습니다.');
      }
      const count = Number(rawCount);
      if (!/^\d+(?:\.0+)?$/.test(rawCount) || !Number.isSafeInteger(count)) throw new Error('이용건수는 0 이상의 정수여야 합니다.');
      const key = `${month}/${group}`;
      if (!panels.has(key)) panels.set(key, new Map());
      const panel = panels.get(key);
      if (!panel.has(category)) panel.set(category, new Map());
      const counts = panel.get(category);
      if (counts.has(sex)) throw new Error('월·집단·업종·성별이 같은 중복 행이 있습니다.');
      counts.set(sex, count); months.add(month); used++;
    });
    if (!used) throw new Error('이 파일에 비교 대상 두 집단과 8개 업종의 관측이 없습니다.');
    return {panels, months:[...months].sort(), used};
  }

  function observe(data, month, group) {
    const panel = data.panels.get(`${month}/${group}`);
    const cells = CATEGORIES.map(category => ({category, values:panel?.get(category)}));
    if (cells.some(cell => !cell.values?.has('남성') || !cell.values?.has('여성'))) return null;
    const counts = cells.map(cell => ({category:cell.category, count:[...cell.values.values()].reduce((a,b)=>a+b,0)}));
    const total = counts.reduce((sum,row)=>sum+row.count,0);
    if (!Number.isSafeInteger(total)) return {status:'overflow'};
    if (total === 0) return {status:'zero', total};
    const unknownCategories = cells.filter(cell => cell.values.has('알수없음')).map(cell => cell.category);
    const rows = counts.map(row => ({...row, percent:100*row.count/total})).sort((a,b)=>b.count-a.count);
    return {status:'ready', total, rows, unknownCategories};
  }

  function compareMonths(data, month, baselineMonth, group) {
    const selected = observe(data, month, group);
    if (!selected) return null;
    if (selected.status !== 'ready') return {selected, baseline:null, rows:[]};
    let baseline = null, baselineIssue = null;
    if (baselineMonth === month) {
      baselineIssue = 'same_month';
    } else if (baselineMonth) {
      const candidate = observe(data, baselineMonth, group);
      if (candidate?.status === 'ready') baseline = candidate;
      else baselineIssue = candidate?.status || 'missing';
    }
    const byCategory = new Map((baseline?.rows || []).map(row => [row.category, row]));
    const rows = selected.rows.map(row => {
      const previous = byCategory.get(row.category);
      return {...row, previous, deltaPoints:previous ? row.percent - previous.percent : null};
    });
    const unknownCoverageDiffers = baseline !== null && CATEGORIES.some(category =>
      selected.unknownCategories.includes(category) !== baseline.unknownCategories.includes(category));
    return {selected, baseline, rows, baselineIssue, unknownCoverageDiffers};
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {parseHub1048, observe, compareMonths};
  if (typeof document === 'undefined') return;
  const file = document.getElementById('observed-csv-file');
  if (!file) return;
  const month = document.getElementById('observed-csv-month'), group = document.getElementById('observed-csv-group');
  const baseline = document.getElementById('observed-csv-baseline');
  const referenceButton = document.getElementById('observed-csv-reference');
  const referenceStatus = document.getElementById('observed-csv-reference-status');
  const result = document.getElementById('observed-csv-result'), status = document.getElementById('observed-csv-status');
  let current = null, request = 0;
  let reference = null, referenceRequest = null;
  const labelMonth = value => `${value.slice(0,4)}년 ${Number(value.slice(4))}월`;
  const number = value => value.toLocaleString('ko-KR');
  const signed = (value, digits) => `${value >= 0 ? '+' : '−'}${Math.abs(value).toLocaleString('ko-KR', {minimumFractionDigits:digits, maximumFractionDigits:digits})}`;
  function element(tag, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function observationNotice(problem, label) {
    if (problem === 'zero') return label + '의 8업종 이용건수 합계가 0건이어서 비중을 계산할 수 없습니다.';
    if (problem === 'overflow') return label + '의 8업종 이용건수 합계가 정확하게 계산할 수 있는 정수 범위를 초과했습니다.';
    return label + '에 완전한 8업종 관측이 없습니다.';
  }
  function render() {
    result.replaceChildren();
    referenceButton.disabled = true;
    if (!current) return;
    const comparison = compareMonths(current, month.value, baseline.value, group.value);
    if (comparison?.selected.status !== 'ready') {
      status.textContent = observationNotice(comparison?.selected.status, '선택한 월·집단') + ' 다른 월 또는 집단을 확인해 주세요.';
      return;
    }
    referenceButton.disabled = !!referenceRequest;
    const {selected, baseline:previous, rows, baselineIssue, unknownCoverageDiffers} = comparison;
    const summary = `${labelMonth(month.value)} · ${group.value} · 8업종 이용건수 ${number(selected.total)}건`;
    const difference = previous ? selected.total - previous.total : null;
    status.textContent = previous
      ? `${summary} · ${labelMonth(baseline.value)} ${number(previous.total)}건 대비 ${signed(difference, 0)}건`
      : summary;
    if (baselineIssue) {
      const notice = baselineIssue === 'same_month'
        ? '두 월이 같아 선택 월만 표시합니다. 다른 기준 월을 고르면 변화를 비교할 수 있어요.'
        : observationNotice(baselineIssue, '기준 월') + ' 선택 월만 표시합니다.';
      result.append(element('p', notice));
    }
    const coverage = '성별 ‘알수없음’ 이용건수를 포함한 업종은 선택 월 ' + selected.unknownCategories.length + '/8개'
      + (previous ? ', 기준 월 ' + previous.unknownCategories.length + '/8개입니다.' : '입니다.');
    result.append(element('p', coverage));
    if (unknownCoverageDiffers) {
      result.append(element('p', '두 달의 ‘알수없음’ 기록이 있는 업종이 다릅니다. 월별 합계는 각 달의 기록을 반영하므로 변화에 집계 범위 차이도 포함될 수 있어요.'));
    }
    const table = element('table'), head = element('thead'), heading = element('tr'), body = element('tbody');
    const titles = ['업종', '선택 월 이용건수', '선택 월 비중'];
    if (previous) titles.push('기준 월 이용건수', '기준 월 비중', '비중 변화');
    if (reference) titles.push('월별 모델 참고값', '관측과 차이');
    for (const title of titles) {
      const cell = element('th', title); cell.scope = 'col'; heading.append(cell);
    }
    head.append(heading); table.append(head, body);
    for (const row of rows) {
      const tr = element('tr');
      tr.append(element('td', row.category), element('td', number(row.count)), element('td', `${row.percent.toFixed(2)}%`));
      if (row.previous) {
        tr.append(element('td', number(row.previous.count)), element('td', `${row.previous.percent.toFixed(2)}%`), element('td', `${signed(row.deltaPoints, 2)}%p`));
      }
      if (reference) {
        const expected = reference.shares.get(row.category);
        tr.append(element('td', `${expected.toFixed(2)}%`), element('td', `${signed(row.percent - expected, 2)}%p`));
      }
      body.append(tr);
    }
    if (previous) {
      const largest = rows.reduce((current, row) => Math.abs(row.deltaPoints) > Math.abs(current.deltaPoints) ? row : current);
      if (Number(Math.abs(largest.deltaPoints).toFixed(2)) === 0) {
        result.append(element('p', '소수점 둘째 자리까지 표시한 업종 비중 변화는 모두 0.00%p입니다.'));
      } else {
        result.append(element('p', `비중 변화가 가장 큰 업종은 ${largest.category} (${signed(largest.deltaPoints, 2)}%p)입니다.`));
      }
    }
    result.append(table);
  }
  function clearReference() {
    referenceRequest?.abort();
    referenceRequest = null;
    reference = null;
    referenceStatus.textContent = '';
  }
  function defaultBaseline() {
    const older = [...current.months].reverse().filter(value => value < month.value && observe(current, value, group.value)?.status === 'ready');
    const priorYear = String(Number(month.value.slice(0,4)) - 1) + month.value.slice(4);
    baseline.value = older.includes(priorYear) ? priorYear : older[0] || '';
  }
  function clearFile() {
    current = null;
    clearReference();
    month.replaceChildren();
    baseline.replaceChildren();
    month.disabled = baseline.disabled = group.disabled = referenceButton.disabled = true;
    result.replaceChildren();
    status.textContent = '';
  }
  function reset() {
    request++;
    file.value = '';
    group.value = '제주도민';
    clearFile();
  }
  file.addEventListener('change', async () => {
    const source = file.files?.[0], id = ++request;
    clearFile();
    if (!source) return;
    if (source.size > MAX_BYTES) { status.textContent = '8MB 이하의 1048 CSV를 선택해 주세요.'; return; }
    status.textContent = '이 탭에서 CSV 형식을 확인하고 있어요.';
    try {
      const bytes = await source.arrayBuffer();
      if (id !== request) return;
      current = parseHub1048(bytes);
      const noBaseline = element('option', '선택 월만 보기');
      noBaseline.value = '';
      baseline.append(noBaseline);
      for (const value of [...current.months].reverse()) {
        const option = element('option', labelMonth(value)); option.value = value; month.append(option);
        baseline.append(option.cloneNode(true));
      }
      month.disabled = baseline.disabled = group.disabled = false;
      defaultBaseline();
      render();
    } catch (error) {
      if (id === request) status.textContent = error.message || 'CSV를 읽지 못했습니다.';
    }
  });
  for (const field of [month, group]) field.addEventListener('change', () => {
    clearReference();
    defaultBaseline();
    render();
  });
  baseline.addEventListener('change', render);
  referenceButton.addEventListener('click', async () => {
    if (!current) return;
    clearReference();
    const controller = new AbortController();
    referenceRequest = controller;
    referenceButton.disabled = true;
    referenceStatus.textContent = '로컬에 저장된 월별 모델 참고값을 읽고 있어요.';
    const params = new URLSearchParams({audience:group.value === '제주도민' ? 'resident' : 'tourist', month:String(Number(month.value.slice(4)))});
    try {
      const response = await fetch(`/api/observed-reference?${params}`, {signal:controller.signal});
      const data = await response.json();
      if (referenceRequest !== controller) return;
      const shares = new Map((Array.isArray(data.categories) ? data.categories : []).map(row => [row.name, row.share * 100]));
      if (!response.ok || data.source_id !== '1048' || !CATEGORIES.every(name => Number.isFinite(shares.get(name)))) {
        throw new Error('월별 모델 참고값을 확인하지 못했습니다.');
      }
      reference = {shares};
      referenceStatus.textContent = `같은 집단·달력 월의 1048 모델 참고값을 표시합니다. 원자료 관측 ${data.observation_period.start}~${data.observation_period.end}. 차이는 선택한 파일의 비중에서 모델 참고값을 뺀 값입니다.`;
    } catch (error) {
      if (referenceRequest === controller) referenceStatus.textContent = '월별 모델 참고값을 불러오지 못했습니다. 관측 결과는 계속 볼 수 있어요.';
    } finally {
      if (referenceRequest === controller) {
        referenceRequest = null;
        render();
      }
    }
  });
  document.getElementById('observed-csv-clear').addEventListener('click', reset);
  window.addEventListener('jeju:reset', reset); window.addEventListener('pagehide', reset);
})();
