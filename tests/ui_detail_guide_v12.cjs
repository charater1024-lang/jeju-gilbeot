// Detail rendering uses public fixtures; no browser, location, storage or network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync(__dirname+'/../ui/app.js','utf8');
const helpers=app.slice(app.indexOf('function normalizeTourismGuide('),app.indexOf('function sourceOverlapMarkup('));
const detail=app.slice(app.indexOf('async function showRichDetail('),app.indexOf('async function getJSON('));
const escaped=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const safeLink=value=>{if(typeof value!=='string'||!value.trim())return '';try{const url=new URL(value,'http://127.0.0.1:8765');return ['https:','http:'].includes(url.protocol)?url.href:'';}catch{return '';}};
const sourceURL='https://www.openstreetmap.org/node/123',guideURL='https://www.visitjeju.net/kr/detail/view?contentsid=PUBLIC_FIXTURE';
const fixture={id:'osm_tourism_node_123',name:'시험 해변',kind:'attraction',source_overlap_verified:true,category:'해변',region:'north',latitude:33.5,longitude:126.5,address:'공개 시험 주소',source_platform:'openstreetmap',source_url:sourceURL,description:'MAP_ONLY_NOTE',description_provenance:'observed_osm_description_tag',tourism_guide:{summary:'바다와 산책을 만나는 공개 시험 설명 <img src=x onerror=alert(1)>',source_url:guideURL,source_name:'관광 안내기관 <b>시험</b>',source_content_id:'PUBLIC_FIXTURE',summary_method:'source_based_editorial_paraphrase'}};
async function render(item){
  const nodes=new Map([['#destination-dialog',{open:true}],['#destination-detail',{innerHTML:''}]]);
  const context={URL,Number,String,Object,Array,Set,detailRequest:0,destinations:[],saved:new Set(),escapeHTML:escaped,safeLink,safeImage:()=>'',itemID:item=>item.id,itemRegion:()=> '북부',icon:()=>'',photoMarkup:()=>'',normalizeExtraPlace:item=>({...item}),sourceOverlapMarkup:()=>'',handleImageFailures(){},getJSON:async()=>({item}),openDialog:node=>node.open=true,$:selector=>nodes.get(selector)};
  vm.createContext(context);vm.runInContext(helpers+'\n'+detail,context);await context.showRichDetail(item);
  return {html:nodes.get('#destination-detail').innerHTML,context};
}
(async()=>{
  const checks=[];
  let {html,context}=await render(fixture);
  assert(html.includes('class="detail-tourism-guide"'));assert(html.includes('관광 안내 원문 ↗'));assert(html.includes(guideURL));assert(html.includes(sourceURL));assert(html.includes('지도 원문 ↗'));
  assert(html.indexOf('detail-tourism-guide')<html.indexOf('detail-facts'));assert(html.indexOf('바다와 산책')<html.indexOf('MAP_ONLY_NOTE'));assert(html.includes('지도에 기록된 메모'));
  checks.push('source-backed guide is the primary introduction; map source and optional observed memo remain separately labelled');
  assert(!html.includes('<img src=x'));assert(html.includes('&lt;img'));assert(!html.includes('<b>시험</b>'));assert(html.includes('&lt;b&gt;시험&lt;/b&gt;'));
  checks.push('guide content and provider labels remain escaped text rather than executable HTML');
  ({html}=await render({...fixture,tourism_guide:null}));assert(html.includes('관광 소개문을 아직 연결하지 못했어요.'));assert(!html.includes('class="detail-tourism-guide"'));assert(html.includes('지도에 기록된 메모'));assert(!html.includes('관광 안내 원문 ↗'));
  checks.push('missing tourist guide is disclosed instead of presenting a map note as a tourism description');
  ({html}=await render({...fixture,tourism_guide:{...fixture.tourism_guide,source_url:sourceURL,summary:'FORGED_GUIDE'}}));assert(!html.includes('FORGED_GUIDE'));assert(html.includes('관광 소개문을 아직 연결하지 못했어요.'));
  checks.push('OpenStreetMap URLs cannot masquerade as tourism-guide provenance');
  ({html}=await render({...fixture,tourism_guide:{...fixture.tourism_guide,source_url:'javascript:alert(1)',summary:'UNSAFE_GUIDE'}}));assert(!html.includes('javascript:'));assert(!html.includes('UNSAFE_GUIDE'));
  assert.equal(context.normalizeTourismGuide({...fixture.tourism_guide,source_url:'/local-without-original'}),null);assert.equal(context.normalizeTourismGuide({...fixture.tourism_guide,source_url:'data:text/html,test'}),null);
  const bounded=context.normalizeTourismGuide({...fixture.tourism_guide,summary:'가'.repeat(3000),source_name:'기'.repeat(200)});assert.equal(bounded.summary.length,1600);assert.equal(bounded.source_name.length,100);
  checks.push('guide links require an absolute HTTP original and public guide fields have bounded lengths');
  ({html}=await render({...fixture,source_url:guideURL}));assert.equal(html.split(guideURL).length-1,1);assert(!html.includes('지도 원문 ↗'));
  checks.push('the same tourism original is linked once when it is also the record source');
  ({html}=await render({...fixture,id:'food_123',kind:'food',source_overlap_verified:false,source_platform:'jeju_datahub',source_url:'https://www.jejudatahub.net/data/view/data/780',description:'인허가 명부에 있는 업소 기록',description_provenance:'permit_record',tourism_guide:null}));assert(html.includes('인허가 명부에 있는 업소 기록'));assert(html.includes('명부 원문 ↗'));assert(!html.includes('관광 소개문을 아직 연결하지 못했어요.'));
  checks.push('food details keep their own record description and registry source without a missing-tourism notice');
  const discovery=fs.readFileSync(__dirname+'/../ui/discovery.js','utf8');const functions=discovery.slice(discovery.indexOf('  function guideFor('),discovery.indexOf('  function overlapMarkup('));
  const ctx={URL,escape:escaped,safeURL:safeLink};vm.createContext(ctx);vm.runInContext(functions,ctx);
  const source=ctx.sourceLink(fixture);assert(source.includes('관광 안내 원문'));assert(source.includes('지도 원문'));const card=ctx.guideCardMarkup(fixture);assert(card.includes('&lt;img'));assert(!card.includes('<img'));assert.equal(ctx.guideCardMarkup({...fixture,tourism_guide:{...fixture.tourism_guide,source_url:sourceURL}}),'');
  checks.push('search cards use the same guide precedence, safe preview text and distinct tourism/map original links');
  console.log(JSON.stringify({passed:true,checks,real_device_location_requested:false,external_network:false,storage_used:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
