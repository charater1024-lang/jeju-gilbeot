(() => {
  'use strict';
  const host = document.getElementById('model-goal-report');
  if (!host) return;
  let pending = null, loaded = false;
  const node = (tag, text) => { const item = document.createElement(tag); if (text != null) item.textContent = String(text); return item; };
  function table(columns, rows) {
    const scroll = node('div'); scroll.className = 'goal-table-scroll'; scroll.tabIndex = 0;
    const grid = node('table'), head = node('thead'), titles = node('tr'), body = node('tbody');
    for (const title of columns) { const cell = node('th', title); cell.scope = 'col'; titles.append(cell); }
    for (const values of rows) { const row = node('tr'); for (const value of values) row.append(node('td', value)); body.append(row); }
    head.append(titles); grid.append(head, body); scroll.append(grid); return scroll;
  }
  function render(data) {
    if (!Array.isArray(data.models) || data.all_service_models_93_proven !== false) throw new Error('평가 범위를 확인해야 합니다.');
    const open = host.open;
    const content = document.createDocumentFragment();
    content.append(node('summary', '93% 목표와 모델 조합 비교 · 전체 목표 미달'),
      node('p', `${data.date_kst} 기준. 고정한 허용오차와 같은 평가 대상에서 비교했습니다. 과거 기간 평가와 작성 질의 검사는 실제 사용자 정확도와 구분합니다.`));
    const regression = data.models.filter(row => row.type === 'regression');
    content.append(table(['운영 모델', '고정 평가 기준', '운영 모델 결과'], regression.map(row => [row.title, row.metric?.name || '평가 전', row.metric ? `${row.metric.percent.toFixed(2)}% · ${row.metric.hits.toLocaleString('ko-KR')}/${row.metric.total.toLocaleString('ko-KR')}` : '평가 전'])));
    content.append(node('p', data.goal_note));
    const experiment = node('details');
    experiment.append(node('summary', `비교한 학습 조합과 채택 결과 ${data.experiments?.length || 0}건`));
    experiment.append(table(['자료', '비교한 조합', '검증 선정 후보의 테스트', '채택 결과'], (data.experiments || []).map(row => [row.title, `${row.candidate_count}개${row.family_count ? ' · '+row.family_count+'계열' : ''}`, row.candidate_metric_percent == null ? '평가 기록 참조' : `${row.candidate_metric_percent.toFixed(2)}%`, row.promoted ? '개선 모델 적용' : '기존 운영 모델 유지'])));
    content.append(experiment);
    const retrieval = node('details');
    retrieval.append(node('summary', '검색·요청 분류의 작성 질의 평가 범위'));
    retrieval.append(table(['학습 요소', '현재 평가', '적용 범위'], data.models.filter(row => row.type !== 'regression').map(row => [row.title, row.metric ? `${row.metric.name} · ${row.metric.percent.toFixed(2)}% (${row.metric.hits}/${row.metric.total})` : '운영 범위 재평가 필요', row.evaluation_scope])));
    content.append(retrieval);
    for (const note of data.notes || []) content.append(node('p', note));
    const link = node('a', '개별 오차와 자료 출처 확인하기 ↗');
    link.className = 'text-link';
    link.href = '/explore#data-guide';
    content.append(link);
    host.replaceChildren(content);
    host.open = open;
  }
  async function load() {
    if (loaded || pending) return;
    const job = new AbortController(); pending = job;
    try {
      const response = await fetch('/api/model-evaluation', {cache:'no-store', signal:job.signal});
      if (!response.ok) throw new Error('평가 명세를 불러오지 못했습니다.');
      const data = await response.json(); if (pending !== job) return;
      render(data); loaded = true;
    } catch (error) {
      if (pending === job && error.name !== 'AbortError') {
        const message = host.querySelector('[data-model-evaluation-status]');
        if (message) message.textContent = '모델 평가 자료를 불러오지 못했습니다. 소개 화면을 다시 열어 확인해 주세요.';
      }
    } finally { if (pending === job) pending = null; }
  }
  window.addEventListener('jeju:pagechange', event => { if (event.detail?.path === '/about') load(); });
  window.addEventListener('pagehide', () => { pending?.abort(); pending = null; });
  if (document.body.dataset.page === '/about') load();
})();
