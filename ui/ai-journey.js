(function () {
  'use strict';
  const host = document.getElementById('ai-start');
  if (!host) return;
  const status = document.getElementById('ai-start-status');
  const savedCount = document.getElementById('ai-saved-count');
  const savedHelp = document.getElementById('ai-saved-help');
  const savedButton = host.querySelector('[data-ai-plan="saved"]');

  function refreshSaved(event) {
    let items;
    try { items = window.JejuTripBridge?.getSaved?.(); } catch { items = null; }
    const known = Array.isArray(items) ? Math.min(items.length, 24) : null;
    const eventCount = event?.detail?.count;
    const badgeText = document.getElementById('saved-count')?.textContent?.trim();
    const badgeCount = /^\d{1,2}$/.test(badgeText || '') ? Number(badgeText) : null;
    const validCount = value => Number.isInteger(value) && value >= 0 && value <= 24;
    const count = validCount(eventCount) ? eventCount : validCount(badgeCount) ? badgeCount : known;
    if (count === null) return;
    if (savedCount) savedCount.textContent = `담은 장소 ${count}곳`;
    if (savedHelp) savedHelp.textContent = count
      ? known !== null && known < count
        ? '확인 중인 장소가 있어요. 담기 목록에서 정보를 확인한 뒤 일정을 만들어 주세요.'
        : '직접 담은 장소를 바탕으로 시간과 방문 순서를 확인해 보세요.'
      : '먼저 여행지를 담으면 나만의 방문 순서를 만들 수 있어요.';
    if (savedButton) savedButton.disabled = count === 0;
  }

  function openPlan(mode) {
    if (!['automatic', 'saved'].includes(mode)) return;
    if (mode === 'saved' && savedButton?.disabled) return;
    try {
      if (typeof window.JejuTripBridge?.beginPlan === 'function') {
        const result = window.JejuTripBridge.beginPlan(mode);
        if (status) status.textContent = result === false
          ? '아래 일정 입력에서 필요한 조건을 확인해 주세요.'
          : mode === 'automatic'
            ? '코스 추천 조건을 열었어요. 출발지와 여행 시간을 확인해 주세요.'
            : '담은 장소로 일정 만들기를 열었어요. 출발지와 여행 시간을 확인해 주세요.';
        return;
      }
      const form = document.getElementById('planner-form');
      if (!form) throw new Error('missing-form');
      window.JejuPages?.reveal(form);
      const details = form.closest('.planner-manual');
      if (details) details.open = true;
      form.scrollIntoView({behavior: 'smooth', block: 'start'});
      form.setAttribute('tabindex', '-1');
      form.focus({preventScroll: true});
      if (status) status.textContent = '일정 입력을 열었어요. 일정 만드는 방법과 출발지를 직접 확인해 주세요.';
    } catch {
      if (status) status.textContent = '아래 일정 입력에서 시작해 주세요. 연결이 준비되지 않으면 페이지를 새로고침해 주세요.';
    }
  }

  host.addEventListener('click', event => {
    const button = event.target.closest('[data-ai-plan]');
    if (button && host.contains(button)) {
      openPlan(button.dataset.aiPlan);
      return;
    }
    const diningLink = event.target.closest('[data-ai-tool="dining"]');
    if (diningLink && host.contains(diningLink)
        && typeof window.JejuDataGuide?.openDining === 'function') {
      event.preventDefault();
      try {
        window.JejuDataGuide.openDining();
        if (status) status.textContent = '음식 자료 비교를 열었어요. 관심 월과 업종을 골라보세요.';
      } catch {
        window.JejuPages?.navigate('/explore#data-guide');
        if (status) status.textContent = '자료 비교에서 세부 외식업종을 선택해 주세요.';
      }
    }
  });
  window.addEventListener('jeju:saved', refreshSaved);
  window.addEventListener('jeju:pagechange', refreshSaved);
  window.addEventListener('jeju:reset', () => {
    refreshSaved();
    if (status) status.textContent = '';
  });
  refreshSaved();
})();
