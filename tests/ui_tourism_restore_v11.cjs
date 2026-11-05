// Public place fixtures only. No browser, real GPS, storage or network access.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/../ui/app.js','utf8');
function fragment(start,end){const a=source.indexOf(start),b=source.indexOf(end,a+start.length);assert(a>=0&&b>a);return source.slice(a,b);}
const point={name:'교차확인 해변',latitude:33.5,longitude:126.5,region:'north',category:'해변',kind:'attraction',source_overlap_verified:true};
const calls=[];
const responses={approved:{...point,id:'approved-current'},food:{...point,id:'food',kind:'food',source_overlap_verified:false},maponly:{...point,id:'maponly',source_overlap_verified:false},generic:{...point,id:'generic',kind:'reference',source_overlap_verified:false}};
const context={URL,URLSearchParams,Number,Object,Array,Promise,Set,MAX_SAVED:8,regions:{all:'전체',north:'북부'},location:{origin:'http://127.0.0.1:8765'},getJSON:async path=>{assert(path.startsWith('/api/place-details?'));const id=new URL(path,'http://127.0.0.1:8765').searchParams.get('id');calls.push(id);if(!(id in responses))throw Error('unavailable');return {item:responses[id]};}};
vm.createContext(context);
vm.runInContext(fragment('const safeLink =','const safeImage =')+fragment('function normalizeTourismGuide(raw)','function sourceOverlapMarkup(item)')+fragment('function normalizeOverlapEvidence(raw)','function renderAudience()')+fragment('async function revalidateSavedExtras(items)','async function loadDestinations()'),context);
(async()=>{
  const input=['approved','maponly','generic','food','missing'].map(id=>({id}));
  const restored=await context.revalidateSavedExtras(input);
  assert.deepEqual(Array.from(restored,item=>item.id),['approved-current','food']);
  assert.equal(restored[0].source_overlap_verified,true);assert.equal(restored[1].kind,'food');
  assert.equal(calls.length,5);
  const proof=context.normalizeOverlapEvidence({hub:{id:'hub',source_url:'javascript:alert(1)'},osm:{id:'osm',source_url:'https://www.openstreetmap.org/node/1'},distance_m:Infinity});
  assert.equal(proof.hub.source_url,'');assert.equal(proof.distance_m,null);
  console.log(JSON.stringify({passed:true,checks:['saved tourist records are revalidated against current local details before restoration','unverified map and generic registry records cannot reappear as saved attractions','approved canonical IDs and explicitly mapped food records remain usable','provenance URLs and nonfinite source-coordinate distances are bounded and sanitized'],realGPS:false,external_network:false}));
})().catch(error=>{console.error(error);process.exitCode=1});
