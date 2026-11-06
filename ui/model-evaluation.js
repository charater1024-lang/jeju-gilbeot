(() => {
  'use strict';
  const host = document.getElementById('model-goal-report');
  if (!host) return;
  let pending = null, loaded = false;
  const node = (tag, value) => {
    const element = document.createElement(tag);
    if (value != null) element.textContent = String(value);
    return element;
  };
  function table(models) {
    const wrapper = node('div');
    wrapper.className = 'goal-table-scroll'; wrapper.tabIndex = 0;
    const grid = node('table'), head = node('thead'), labels = node('tr'), body = node('tbody');
    for (const label of ['모델', '고정 평가', '서비스에서 쓰는 방식']) {
      const heading = node('th', label); heading.scope = 'col'; labels.append(heading);
    }
    for (const model of models) {
      const row = node('tr'), metric = model.metric;
      row.append(node('td', model.title), node('td', metric ? `${metric.name} · ${metric.percent.toFixed(2)}% (${metric.hits}/${metric.total})` : '운영 범위 지표 없음'), node('td', model.decision));
      body.append(row);
    }
    head.append(labels); grid.append(head, body); wrapper.append(grid);
    return wrapper;
  }
  function render(report) {
    if (report.service_version !== 23 || report.field_accuracy_proven !== false || !Array.isArray(report.models)) throw new Error('평가 범위를 확인해야 합니다.');
    const active = report.models.filter(model => model.active), retired = report.models.filter(model => !model.active);
    if (active.length !== report.active_count || active.some(model => model.metric?.percent < report.target_percent)) throw new Error('평가 기준이 일치하지 않습니다.');
    const content = document.createDocumentFragment();
    content.append(node('summary', `운영 모델 ${active.length}종의 평가와 ${report.target_percent}% 적용 기준`), table(active));
    for (const note of report.notes || []) content.append(node('p', note));
    const details = node('details');
    details.append(node('summary', `운영에서 제외한 모델 ${retired.length}종`), table(retired));
    content.append(details);
    host.replaceChildren(content);
  }
  async function load() {
    if (loaded || pending) return;
    const job = new AbortController(); pending = job;
    try {
      const response = await fetch('/api/model-evaluation', {cache:'no-store', signal:job.signal});
      if (!response.ok) throw new Error('평가 명세를 불러오지 못했습니다.');
      const report = await response.json();
      if (pending === job) { render(report); loaded = true; }
    } catch (error) {
      if (pending === job && error.name !== 'AbortError') {
        const message = host.querySelector('[data-model-evaluation-status]');
        if (message) message.textContent = '모델 평가를 확인하지 못했습니다.';
      }
    } finally { if (pending === job) pending = null; }
  }
  window.addEventListener('jeju:pagechange', event => { if (event.detail?.path === '/about') load(); });
  window.addEventListener('pagehide', () => { pending?.abort(); pending = null; });
  if (document.body.dataset.page === '/about') load();
})();
