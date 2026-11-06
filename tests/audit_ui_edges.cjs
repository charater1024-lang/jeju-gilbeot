'use strict';
// Isolated browser-state fixtures. No production data or browser storage is changed.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, '../ui/app.js'), 'utf8');

function fragment(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert(first >= 0 && last > first, start);
  return source.slice(first, last);
}

function fixture(savedPayload, failure = () => null) {
  const nodes = new Map();
  const calls = [];
  let stored = JSON.stringify(savedPayload);
  const featured = {id:'featured-test', name:'test feature', source_overlap_verified:true};
  const context = {
    destinations:[], URLSearchParams, Image:class {},
    $(selector) {
      if (!nodes.has(selector)) nodes.set(selector, {});
      return nodes.get(selector);
    },
    sessionStorage:{
      getItem:()=>stored,
      setItem(key, value){ stored = value; },
    },
    notify(){}, renderDestinations(){}, renderSaved(){}, sourceMarkup(){}, safeImage(){},
    itemID:point=>point.id,
    normalizeExtraPlace:point=>point.source_overlap_verified ? {...point, featured:false} : null,
    async getJSON(url) {
      if (url === '/api/destinations') return {items:[featured], sources:[{}]};
      const id = new URL(url, 'http://127.0.0.1').searchParams.get('id');
      calls.push(id);
      const error = failure(id);
      if (error) throw error;
      const canonical = id === 'old-alias' ? 'new-canonical' : id;
      return {item:{id:canonical, name:canonical, source_overlap_verified:id !== 'unverified-test'}};
    },
  };
  vm.createContext(context);
  vm.runInContext(
    fragment('const SESSION_KEY=', 'function notify(') +
    fragment('function persist()', 'function itemID(') +
    fragment('async function revalidateSavedExtras(', 'function statusDescription('),
    context,
  );
  return {
    calls,
    stored:()=>JSON.parse(stored),
    visible:()=>Array.from(vm.runInContext('destinations.filter(point=>saved.has(point.id)).map(itemID)', context)),
    restore:()=>context.loadDestinations(),
  };
}

async function main() {
  const cases = [];
  const record = (name, condition, evidence) => cases.push({name, status:condition ? 'pass' : 'issue', evidence});
  const ids = Array.from({length:25}, (_, index)=>'extra-'+(index+1));
  const items = ids.map(id=>({id, name:'old full metadata'}));

  const capacity = fixture({ids, extra_places:items});
  await capacity.restore();
  assert.deepEqual(capacity.visible(), ids.slice(0,24));
  record('25 stored inputs revalidate only the first 24', capacity.calls.length===24, {calls:capacity.calls.length});
  record('24 restored references persist as IDs', capacity.stored().extra_places.every(item=>Object.keys(item).join()==='id'), {count:capacity.stored().extra_places.length});

  const old = fixture({ids:['featured-test','old-alias'], extra_places:[{id:'old-alias', name:'old payload', latitude:33.5}]});
  await old.restore();
  record('legacy session payload migrates to canonical ID', old.stored().ids.join() === 'featured-test,new-canonical', old.stored());

  const unverified = fixture({ids:['featured-test','unverified-test'], extra_places:[{id:'unverified-test'}]});
  await unverified.restore();
  record('explicitly unverified records do not become route places', unverified.visible().join()==='featured-test', unverified.stored());

  for (const failure of ['503 temporary failure', 'AbortError during restore']) {
    const temporary = fixture({ids:['featured-test',...ids.slice(0,23)], extra_places:items.slice(0,23)},
      id => id === ids[8] ? new Error(failure) : null);
    await temporary.restore();
    const kept = temporary.stored().ids;
    record('temporary details failure preserves bookmark for retry: '+failure,
      kept.includes(ids[8]), {failedId:ids[8], savedBefore:24, savedAfter:kept.length, listed:temporary.visible().includes(ids[8])});
  }
  let unavailable = true;
  const retry = fixture({ids:['featured-test', ids[0]], extra_places:[items[0]]},
    id=>unavailable && id===ids[0] ? Object.assign(new Error('temporary response'), {status:503}) : null);
  await retry.restore();
  assert.deepEqual(retry.visible(), ['featured-test']);
  unavailable = false;
  await retry.restore();
  record('retry verifies and restores the pending bookmark', retry.visible().includes(ids[0]), retry.stored());

  const removed = fixture({ids:['featured-test', ids[0]], extra_places:[items[0]]},
    id=>id===ids[0] ? Object.assign(new Error('not found'), {status:404}) : null);
  await removed.restore();
  record('explicit not-found removes a stale reference', removed.stored().ids.join()==='featured-test', removed.stored());
  console.log(JSON.stringify({passed:cases.filter(item=>item.status==='pass').length, issues:cases.filter(item=>item.status==='issue').length, cases},null,2));
  if (process.argv.includes('--strict') && cases.some(item=>item.status==='issue')) process.exitCode = 1;
}
main().catch(error=>{console.error(error);process.exitCode=1;});
