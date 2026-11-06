'use strict';

// Mutated CSV rows below exercise the parser only. The observational checks use the public 1048 source.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {parseHub1048, observe, compareMonths} = require('../ui/observed-csv.js');

const raw = fs.readFileSync(path.join(__dirname, '../data_raw/hub/hub_1048_5832.csv'));
const data = parseHub1048(raw);
const groups = ['제주도민', '내국인'];
const month = '202506';
const categories = [...data.panels.get(month + '/' + groups[0]).keys()];
const header = 'base_year_month,biz_nm,user_type,sex,use_count';
const original = raw.toString('utf8').split(/\r?\n/);
const completeRows = original
  .filter(line => categories.some(category => line.startsWith(month + ',' + category + ',제주도민,')))
  .map(line => {
    const [date, category, group, sex, , count] = line.split(',');
    return [date, category, group, sex, count].join(',');
  });
const parseRows = (rows, columns = header) => parseHub1048(Buffer.from([columns, ...rows].join('\r\n')));

let cases = 0;
function verify(name, check) {
  try {
    check();
    cases += 1;
  } catch (error) {
    throw new Error(name, {cause: error});
  }
}

for (const selected of data.months) {
  for (const group of groups) {
    verify(selected + '/' + group + ' actual monthly composition', () => {
      const actual = observe(data, selected, group);
      assert.equal(actual.rows.length, 8);
      assert.equal(actual.rows.reduce((total, row) => total + row.count, 0), actual.total);
      assert.ok(actual.total > 0);
      assert.ok(actual.rows.every(row => Number.isSafeInteger(row.count) && row.count >= 0));
      assert.ok(Math.abs(actual.rows.reduce((total, row) => total + row.percent, 0) - 100) < 1e-9);
    });
  }
}

verify('exact byte limit', () => {
  const maximum = Buffer.alloc(8 * 1024 * 1024, 10);
  raw.copy(maximum);
  assert.equal(parseHub1048(maximum).used, data.used);
  assert.throws(() => parseHub1048(Buffer.concat([maximum, Buffer.from('\n')])), /8MB/);
});
verify('empty file and header-only file', () => {
  assert.throws(() => parseHub1048(Buffer.alloc(0)), /8MB/);
  assert.throws(() => parseRows([]), /관측이 없습니다/);
});
verify('UTF-8 BOM and reordered header', () => {
  const reorder = row => row.split(',').reverse().join(',');
  const parsed = parseRows(completeRows.map(reorder), '\uFEFF' + reorder(header));
  assert.equal(observe(parsed, month, groups[0]).total, 785479);
});
verify('valid quoted field with newlines and escaped quotes', () => {
  const withNote = completeRows.map(row => row + ',"a,b\r\n""quoted"" field"');
  assert.equal(observe(parseRows(withNote, header + ',note'), month, groups[0]).total, 785479);
});
verify('duplicate header, duplicate identity and malformed quote', () => {
  assert.throws(() => parseRows(completeRows, header + ',sex'), /원본 CSV/);
  assert.throws(() => parseRows([...completeRows, completeRows[0]]), /중복 행/);
  assert.throws(() => parseRows([completeRows[0] + ',"unfinished'], header + ',note'), /닫히지 않은/);
  assert.throws(() => parseRows([completeRows[0] + ',"closed"x'], header + ',note'), /따옴표/);
});
verify('different row width and unsupported sex or date', () => {
  assert.throws(() => parseRows([completeRows[0] + ',extra']), /열 개수/);
  assert.throws(() => parseRows([completeRows[0].replace(month, '202513')]), /월 형식/);
  assert.throws(() => parseRows([completeRows[0].replace(/,(?:남성|여성|알수없음),/, ',합계,')]), /성별 분류/);
});
for (const invalid of ['', 'NA', '-1', '0.25', '1e3', '0x10', '9007199254740992', 'NaN', 'Infinity']) {
  verify('rejected test-only count ' + JSON.stringify(invalid), () => {
    const row = completeRows[0].replace(/,[^,]+$/, ',' + invalid);
    assert.throws(() => parseRows([row]), /정수|결측/);
  });
}
verify('missing required sex in just one industry cannot become a complete observation', () => {
  const requiredIndex = completeRows.findIndex(row => row.includes(',여성,'));
  assert.ok(requiredIndex >= 0);
  const partial = parseRows(completeRows.filter((_, index) => index !== requiredIndex));
  assert.equal(observe(partial, month, groups[0]), null);
});
verify('baseline absent and same-month delta', () => {
  const absent = compareMonths(data, month, '202507', groups[0]);
  assert.equal(absent.baseline, null);
  assert.ok(absent.rows.every(row => row.deltaPoints === null));
  const identical = compareMonths(data, month, month, groups[0]);
  assert.equal(identical.baseline, null);
  assert.equal(identical.baselineIssue, 'same_month');
  assert.ok(identical.rows.every(row => row.deltaPoints === null));
});

const zeroRows = completeRows.map(row => row.replace(/,[^,]+$/, ',0'));
const overflowRows = completeRows.map(row => row.replace(/,[^,]+$/, ',9007199254740991'));
verify('zero and overflowing observations are distinguished from missing records', () => {
  assert.equal(observe(parseRows(zeroRows), month, groups[0]).status, 'zero');
  assert.equal(observe(parseRows(overflowRows), month, groups[0]).status, 'overflow');
  assert.equal(observe(parseRows(completeRows.slice(0, 1)), month, groups[0]), null);
});
verify('baseline with zero or overflowing counts has a specific explanation', () => {
  for (const [rows, issue] of [[zeroRows, 'zero'], [overflowRows, 'overflow']]) {
    const months = parseRows([...completeRows, ...rows.map(row => row.replace(month, '202406'))]);
    const result = compareMonths(months, month, '202406', groups[0]);
    assert.equal(result.baseline, null);
    assert.equal(result.baselineIssue, issue);
    assert.ok(result.rows.every(row => row.deltaPoints === null));
  }
});
verify('optional sex coverage compares actual category sets from both months', () => {
  const comparison = compareMonths(data, '202212', '202211', groups[0]);
  assert.equal(comparison.selected.unknownCategories.length, 5);
  assert.equal(comparison.baseline.unknownCategories.length, 0);
  assert.equal(comparison.unknownCoverageDiffers, true);
});

function csvUi() {
  function node(tag) {
    return {
      tag, value:'', textContent:'', children:[], handlers:{},
      append(...children) {
        if (this.tag === 'select' && this.children.length === 0) this.value = children[0].value;
        this.children.push(...children);
      },
      replaceChildren() { this.children = []; },
      cloneNode() { return {...this}; },
      addEventListener(event, handle) { this.handlers[event] = handle; },
    };
  }
  const nodes = new Map();
  function get(name) {
    if (!nodes.has(name)) nodes.set(name, node(['month','baseline','group'].includes(name) ? 'select' : 'div'));
    return nodes.get(name);
  }
  get('group').value = groups[0];
  const code = fs.readFileSync(path.join(__dirname, '../ui/observed-csv.js'), 'utf8');
  const document = {getElementById:id => get(id.replace(/^observed-csv-/, '')), createElement:node};
  vm.runInNewContext(code, {document, TextDecoder, window:{addEventListener(){}}});
  async function upload(bytes) {
    get('file').files = [{size:bytes.length, arrayBuffer:async () => bytes}];
    await get('file').handlers.change();
  }
  function text(root) { return [root.textContent, ...root.children.map(text)].join(' '); }
  return {get, upload, text};
}

async function checkUi() {
  const ui = csvUi();
  const text = key => ui.text(ui.get(key));
  const toFile = rows => Buffer.from([header, ...rows].join('\r\n'));
  await ui.upload(toFile(zeroRows));
  verify('zero UI displays observed total without a composition', () => {
    assert.match(text('status'), /합계가 0건/);
    assert.equal(ui.get('reference').disabled, true);
  });
  await ui.upload(toFile(overflowRows));
  verify('overflow UI describes the numeric range', () => assert.match(text('status'), /정수 범위를 초과/));
  await ui.upload(toFile(completeRows.slice(0, 1)));
  verify('incomplete UI describes missing observations', () => assert.match(text('status'), /완전한 8업종 관측이 없습니다/));
  await ui.upload(raw);
  ui.get('month').value = '202212';
  ui.get('month').handlers.change();
  ui.get('baseline').value = '202211';
  ui.get('baseline').handlers.change();
  verify('unequal real coverage is visible beside the comparison', () => {
    assert.match(text('result'), /선택 월 5\/8개, 기준 월 0\/8개/);
    assert.match(text('result'), /집계 범위 차이/);
  });
  ui.get('baseline').value = '202212';
  ui.get('baseline').handlers.change();
  verify('same-month UI removes the change verdict', () => {
    assert.match(text('result'), /두 월이 같아 선택 월만 표시/);
    assert.doesNotMatch(text('result'), /비중 변화가 가장 큰/);
    assert.doesNotMatch(text('result'), /기준 월 이용건수/);
  });
  await ui.upload(toFile([...completeRows, ...completeRows.map(row => row.replace(month, '202406'))]));
  verify('two identical compositions show 0.00 rather than a largest change', () => {
    assert.match(text('result'), /모두 0\.00%p/);
    assert.doesNotMatch(text('result'), /비중 변화가 가장 큰/);
  });
  console.log(JSON.stringify({cases, realMonthlyPanels:data.months.length * groups.length}));
}
checkUi().catch(error => { console.error(error); process.exitCode = 1; });
