'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../ui/ai-journey.js'), 'utf8');
class Node {
  constructor(id) { this.id = id; this.textContent = ''; this.dataset = {}; this.events = {}; this.disabled = false; this.attributes = {}; }
  addEventListener(name, handler) { this.events[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
}
function fixture({bridge = true, saved = [], formPresent = true, hostPresent = true} = {}) {
  const host = new Node('ai-start'), status = new Node('ai-start-status');
  const count = new Node('ai-saved-count'), help = new Node('ai-saved-help');
  const automatic = new Node('automatic'), manual = new Node('saved');
  automatic.dataset.aiPlan = 'automatic'; manual.dataset.aiPlan = 'saved';
  for (const button of [automatic, manual]) button.closest = selector => selector === '[data-ai-plan]' ? button : null;
  const diningLink = new Node('dining');diningLink.dataset.aiTool = 'dining';
  diningLink.closest = selector => selector === '[data-ai-tool="dining"]' ? diningLink : null;
  host.querySelector = selector => selector === '[data-ai-plan="saved"]' ? manual : null;
  host.contains = node => [automatic, manual, diningLink].includes(node);
  const details = {open: false}, form = new Node('planner-form');
  form.value = 'existing trip inputs';
  form.closest = selector => selector === '.planner-manual' ? details : null;
  const calls = [];
  form.scrollIntoView = options => calls.push(['scroll', options]);
  form.focus = options => calls.push(['focus', options]);
  form.requestSubmit = () => { throw new Error('start must never calculate a route'); };
  const ids = {'ai-start': hostPresent ? host : null, 'ai-start-status': status,
    'ai-saved-count': count, 'ai-saved-help': help, 'planner-form': formPresent ? form : null};
  const events = {}, model = {saved, beginResult: true};
  const context = {document: {getElementById: id => ids[id]},
    addEventListener: (name, handler) => { events[name] = handler; },
    JejuPages: {reveal: form => calls.push(['reveal', form.id]), navigate: url => calls.push(['navigate', url])},
    JejuDataGuide: {openDining: () => calls.push(['dining'])},
    fetch: () => { throw new Error('task hub must never start a server request'); }};
  if (bridge) context.JejuTripBridge = {
    getSaved: () => model.saved,
    beginPlan: mode => { calls.push(['plan', mode]); return model.beginResult; },
  };
  for (const key of ['navigator', 'localStorage', 'sessionStorage']) Object.defineProperty(context, key, {
    get() { throw new Error('task hub must not access location or persistent storage'); },
  });
  context.window = context;
  vm.runInNewContext(script, context);
  return {host, status, count, help, automatic, manual, diningLink, form, details, calls, events, model, context,
    click: button => host.events.click({target: button, preventDefault() { calls.push(['preventDefault']); }})};
}
const fresh = fixture();
assert.deepEqual(fresh.calls, [], 'opening a page performs no task');
assert(fresh.manual.disabled, 'saved-place planning explains its empty state');
assert.match(fresh.count.textContent, /0곳/);
fresh.click(fresh.manual);assert.deepEqual(fresh.calls, []);
fresh.click(fresh.automatic);
assert.deepEqual(fresh.calls, [['plan', 'automatic']]);
assert.match(fresh.status.textContent, /출발지와 여행 시간/);
assert.equal(fresh.form.value, 'existing trip inputs');
fresh.model.saved = [{id: 'a'}, {id: 'b'}];fresh.events['jeju:saved']();
assert(!fresh.manual.disabled);assert.match(fresh.count.textContent, /2곳/);
fresh.click(fresh.manual);assert.deepEqual(fresh.calls.at(-1), ['plan', 'saved']);
assert.equal(fresh.model.saved.length, 2, 'selecting an action preserves the saved collection');
fresh.model.beginResult = false;fresh.click(fresh.automatic);
assert.match(fresh.status.textContent, /필요한 조건/);
const before = fresh.calls.length;
fresh.host.contains = () => true;
fresh.click({dataset: {aiPlan: 'device'}, closest() { return this; }});
assert.equal(fresh.calls.length, before, 'unknown plan modes do not invoke the bridge');
fresh.model.saved = [];fresh.events['jeju:reset']();
assert.equal(fresh.status.textContent, '');assert(fresh.manual.disabled);
fresh.events['jeju:pagechange']();assert.deepEqual(fresh.model.saved, []);
fresh.events['jeju:saved']({detail: {count: 2, items: []}});
assert.match(fresh.count.textContent, /2곳/);assert(!fresh.manual.disabled);
assert.match(fresh.help.textContent, /확인 중인 장소/);
fresh.events['jeju:saved']({detail: {count: 999}});
assert.match(fresh.count.textContent, /0곳/);assert(fresh.manual.disabled);
fresh.click(fresh.diningLink);assert.deepEqual(fresh.calls.slice(-2), [['preventDefault'], ['dining']]);
assert.match(fresh.status.textContent, /관심 월과 업종/);
delete fresh.context.JejuDataGuide;
const noDiningBridge = fresh.calls.length;fresh.click(fresh.diningLink);
assert.equal(fresh.calls.length, noDiningBridge, 'a missing dining bridge leaves the normal link available');

const fallback = fixture({bridge: false});
assert.deepEqual(fallback.calls, []);
fallback.click(fallback.automatic);
assert(fallback.details.open);assert.equal(fallback.form.value, 'existing trip inputs');
assert.equal(fallback.calls[0][0], 'reveal');assert.equal(fallback.calls[1][0], 'scroll');
assert.equal(fallback.calls[2][0], 'focus');
assert.match(fallback.status.textContent, /직접 확인/);
assert.equal(fallback.form.attributes.tabindex, '-1');
const absent = fixture({bridge: false, formPresent: false});absent.click(absent.automatic);
assert.match(absent.status.textContent, /아래 일정 입력/);
const throwing = fixture();throwing.context.JejuTripBridge.beginPlan = () => { throw new Error('internal API diagnostic'); };
throwing.click(throwing.automatic);assert(!throwing.status.textContent.includes('internal'));
assert.doesNotThrow(() => fixture({hostPresent: false}));

const html = fs.readFileSync(path.join(__dirname, '../ui/index.html'), 'utf8');
assert(html.indexOf('id="ai-start"') < html.indexOf('id="planner"'));
assert(html.indexOf('src="/ai-journey.js"') > html.indexOf('src="/app.js"'));
assert(html.indexOf('src="/ai-journey.js"') > html.indexOf('src="/discovery.js"'));
assert.match(html, /href="\/planner#official-guide"/);
assert.match(html, /href="\/explore#data-guide"/);
assert.match(html, /href="\/planner#ai-start" class="journey-door"/);
assert.match(html, /href="\/planner#ai-start">여행 계획해 보기/);
console.log('PASS task hub explicit start, empty saved state, mode-only bridge, safe fallback, reset, no location/storage/network, and page links.');
