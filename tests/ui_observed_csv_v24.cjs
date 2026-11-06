const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {parseHub1048, observe, compareMonths} = require('../ui/observed-csv.js');

const root = path.resolve(__dirname, '..');
const real = parseHub1048(fs.readFileSync(path.join(root,'data_raw/hub/hub_1048_5832.csv')));
assert.equal(real.months.length, 90);
assert.equal(real.used, 3466);
const resident = observe(real, '202506', '제주도민');
assert.equal(resident.total, 785479);
assert.equal(resident.rows.length, 8);
assert.ok(Math.abs(resident.rows.reduce((sum,row)=>sum+row.percent,0)-100)<1e-9);
assert.equal(observe(real, '202507', '제주도민'), null);
const comparison = compareMonths(real, '202506', '202406', '제주도민');
assert.equal(comparison.selected.total, 785479);
assert.equal(comparison.baseline.total, observe(real, '202406', '제주도민').total);
assert.ok(Math.abs(comparison.rows.reduce((sum,row)=>sum+row.deltaPoints,0))<1e-9);
assert.equal(compareMonths(real, '202506', '202507', '제주도민').baseline, null);

const header = 'base_year_month,biz_nm,user_type,sex,use_count\r\n';
const sample = '202506,"한식 음식점업","제주도민","남성",12\r\n';
assert.equal(observe(parseHub1048(Buffer.from(header+sample)), '202506', '제주도민'), null);
assert.throws(()=>parseHub1048(Buffer.from(header+sample+sample)), /중복/);
assert.throws(()=>parseHub1048(Buffer.from(header+sample.replace(',12', ',NA'))), /결측/);
assert.throws(()=>parseHub1048(Buffer.from('wrong,format\r\n1,2\r\n')), /필수|원본/);
console.log('1048 browser CSV: real observation totals, missing cells and malformed input verified');
