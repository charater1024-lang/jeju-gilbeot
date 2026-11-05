// Public map fixtures only. No browser GPS, tiles, storage, or network.
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
  constructor(tag){this.tagName=tag;this.children=[];this.attributes={};this.listeners=new Map();this.style={};this._text='';this.className='';this.clientWidth=500;this.hidden=false;this.disabled=false;this.classList={add:(...v)=>this.classes(v,[]),remove:(...v)=>this.classes([],v),toggle:(v,force)=>{const found=this.className.split(/\s+/).includes(v),next=force===undefined?!found:force;this.classes(next?[v]:[],next?[]:[v]);return next;},contains:v=>this.className.split(/\s+/).includes(v)};}
  classes(add,remove){this.className=[...new Set(this.className.split(/\s+/).filter(v=>v&&!remove.includes(v)).concat(add))].join(' ');}
  set textContent(value){this._text=String(value);this.children=[];}get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
  append(...nodes){for(const n of nodes){this.children.push(n);n.parentElement=this;}}replaceChildren(...nodes){this.children=[];this._text='';this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=String(v);if(k==='class')this.className=String(v);}getAttribute(k){return this.attributes[k]??null;}
  addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(fn);}removeEventListener(type,fn){this.listeners.get(type)?.delete(fn);}
  fire(type,extra={}){if(type==='click'&&this.disabled)return;const event={type,target:this,preventDefault(){},...extra};for(const fn of this.listeners.get(type)||[])fn(event);}
  matches(s){return s.startsWith('.')?this.classList.contains(s.slice(1)):this.tagName===s;}
  querySelectorAll(selector){const selectors=selector.split(',').map(s=>s.trim()),found=[];const visit=n=>{for(const child of n.children){if(selectors.some(s=>child.matches(s)))found.push(child);visit(child);}};visit(this);return found;}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  closest(selector){const selectors=selector.split(',').map(s=>s.trim());for(let n=this;n;n=n.parentElement)if(selectors.some(s=>n.matches(s)))return n;return null;}
  getBoundingClientRect(){return {width:500,height:310,left:0,top:0};}setPointerCapture(){}
}
const point=(id,latitude=33.45,longitude=126.5)=>({id,name:'장소 '+id,latitude,longitude,category:'관광 후보',source_url:'https://example.test/'+id});
function setup({online=false,onSelect,onOpenDetail}={}){
  const log={maps:0,tiles:0,markers:[],events:new Map(),resizes:[],fits:[],removed:0};
  const document={createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),createTextNode:text=>{const node=new Element('#text');node.textContent=text;return node;}};
  const window={setTimeout:()=>1,clearTimeout(){},ResizeObserver:class{constructor(cb){log.resizes.push(cb);}observe(){}disconnect(){}}};
  if(online){const map={setView(){return this;},fitBounds(coords){log.fits.push(coords);log.events.get('zoomend moveend')?.();return this;},on(k,fn){log.events.set(k,fn);return this;},remove(){log.removed++;},invalidateSize(){log.events.get('zoomend moveend')?.();},latLngToContainerPoint:([lat,lon])=>({x:(lon-126)*1000,y:(34-lat)*1000})};
    window.L={map(){log.maps++;return map;},tileLayer(){log.tiles++;return{addTo(){return this;},on(){return this;}};},layerGroup(){return{layers:[],addTo(){return this;},clearLayers(){this.layers=[];}};},divIcon:o=>o,marker(coords,options){const marker={coords,options,events:{},addTo(group){group.layers.push(this);return this;},bindTooltip(){return this;},on(k,fn){this.events[k]=fn;return this;}};log.markers.push(marker);return marker;},polyline(){return{addTo(){return this;}};}};
  }
  vm.runInNewContext(fs.readFileSync(__dirname+'/../ui/jeju-map.js','utf8'),{window,document,URL,console,globalThis:window});
  const host=new Element('div');let controller;
  controller=window.JejuMap.mount(host,{onSelect:p=>{onSelect?.(p);controller.setSelectedIds([p.id]);},onOpenDetail});
  return {host,controller,log};
}
const checks=[];
(async()=>{
  {
    const picked=[],opened=[],{host,controller:m,log}=setup({onSelect:p=>picked.push(p.id),onOpenDetail:p=>{opened.push(p.id);}});
    m.setPlaces([point('a'),point('b')]);
    assert.equal(m.getState().publicPlaceCount,2);assert.equal(m.getState().detailPlaceCount,2);assert.equal(host.querySelectorAll('.jm-place-choice').length,2);assert.equal(host.querySelector('.jm-place-listing').tagName,'details');assert.equal(host.querySelector('.jm-place-listing').open,false,'the all-place list starts closed');
    assert.equal(host.querySelector('.jm-cluster').querySelector('text').textContent,'2곳');
    host.querySelector('.jm-cluster').fire('click');
    assert.deepEqual(Array.from(m.getState().clusterIds),['a','b']);assert.equal(host.querySelector('.jm-cluster-list').children.length,2);
    host.querySelector('.jm-place-choice').fire('click');assert.equal(m.getState().activeId,'a');assert.equal(m.getState().clusterCount,1,'choosing/saving an equal-coordinate place cannot split a cluster into overlapping markers');assert.equal(host.querySelector('.jm-cluster-list').children.length,2);
    host.querySelectorAll('.jm-place-choice')[1].fire('click');assert.equal(m.getState().activeId,'b');assert.equal(host.querySelector('.jm-detail-name').textContent,'장소 b');host.querySelector('.jm-detail-button').fire('click');assert.deepEqual(opened,['b']);assert.deepEqual(picked,['a','b']);
    m.refresh();log.resizes.forEach(fn=>fn());host.querySelector('.jm-zoom-out').fire('click');m.fit();assert.equal(host.querySelector('.jm-cluster-list').children.length,2);assert.equal(m.getState().activeId,'b');
    host.querySelector('.jm-show-all').fire('click');assert.equal(m.getState().clusterIds.length,0);assert.equal(host.querySelector('.jm-place-listing').open,true,'explicit show-all opens the full list');assert.equal(host.querySelectorAll('.jm-place-choice').length,2);
    checks.push('two co-located places remain a two-place bottom list while selecting either, opening details, saving, resizing, refreshing and zooming');
  }
  {
    const {host,controller:m}=setup();m.setPlaces(Array.from({length:500},(_,i)=>point('p'+i)));host.querySelector('.jm-cluster').fire('click');
    const found=new Set();let pages=0;
    do{host.querySelectorAll('.jm-place-choice').forEach(b=>found.add(b.textContent));pages++;if(host.querySelector('.jm-list-next').disabled)break;host.querySelector('.jm-list-next').fire('click');}while(pages<30);
    assert.equal(found.size,500);assert.equal(pages,25);assert.equal(m.getState().detailPage,24);assert.equal(host.querySelector('.jm-list-pagination').textContent.includes('481–500 / 500곳'),true);
    host.querySelector('.jm-list-previous').fire('click');m.refresh();assert.equal(m.getState().detailPage,23);assert.equal(m.getState().detailPlaceCount,500);
    m.setPlaces([point('different',33.3,126.7)]);assert.equal(m.getState().clusterIds.length,0);assert.equal(m.getState().activeId,null);assert.equal(host.querySelectorAll('.jm-place-choice').length,1);assert.equal(host.querySelector('.jm-marker').querySelector('text').textContent,'#1');assert(!host.querySelector('.jm-place-detail').textContent.includes('p499'));
    checks.push('all 500 cluster members are reachable through 20-place pages and a new search discards stale cluster names and pagination');
  }
  {
    const {host,controller:m,log}=setup({online:true});m.setPlaces([point('a'),point('b')]);assert.equal(log.tiles,0);m.enableOnline();
    const cluster=log.markers.at(-1);assert.equal(cluster.options.icon.html,'<span>2곳</span>');cluster.events.click();assert.equal(m.getState().clusterIds.length,2);assert.equal(host.querySelector('.jm-cluster-list').children.length,2);assert.equal(log.fits.length,1);
    host.querySelector('.jm-place-choice').fire('click');m.refresh();log.events.get('zoomend moveend')();log.resizes.forEach(fn=>fn());assert.equal(m.getState().activeId,'a');assert.equal(m.getState().clusterCount,1);assert.equal(host.querySelector('.jm-cluster-list').children.length,2);assert.equal(log.markers.at(-1).options.icon.html,'<span>2곳</span>');m.disableOnline();assert.equal(host.querySelector('.jm-cluster-list').children.length,2);
    checks.push('online fitBounds, move/zoom callbacks and resize keep the selected two-place group instead of replacing it with one detail');
  }
  {
    const {host,controller:m}=setup();m.setPlaces([point('a',33.4,126.3),point('b',33.5,126.7)]);m.setRoute({kind:'straight_line',stops:[point('route-a',33.4,126.3),point('route-b',33.5,126.7)]});assert.equal(m.getState().publicPlaceCount,4);assert.equal(host.querySelectorAll('.jm-place-choice').length,4);assert.equal(host.querySelector('.jm-count').textContent,'표시 장소 4곳');
    host.querySelectorAll('.jm-place-choice')[3].fire('click');assert.equal(m.getState().activeId,'route-b');m.clearRoute();assert.equal(m.getState().activeId,null);assert.equal(m.getState().publicPlaceCount,2);assert.equal(host.querySelectorAll('.jm-place-choice').length,2);assert(!host.querySelector('.jm-place-detail').textContent.includes('route-b'));m.reset();assert.equal(m.getState().detailPlaceCount,0);assert.equal(host.querySelectorAll('.jm-place-choice').length,0);
    checks.push('bottom and header count the union of displayed places and route stops, and removing a route clears its selected detail');
  }
  {
    const {host,controller:m}=setup({onOpenDetail:()=>Promise.reject(new Error('fixture failure'))});m.setPlaces([point('old')]);host.querySelector('.jm-marker').fire('click');host.querySelector('.jm-detail-button').fire('click');m.setPlaces([point('new')]);await new Promise(resolve=>setImmediate(resolve));assert(!host.querySelector('.jm-place-detail').textContent.includes('장소 old'));assert.equal(host.querySelector('.jm-local-detail'),null);
    checks.push('a failed late detail callback cannot restore a place removed by a newer search');
  }
  {
    for(const fixture of [
      {source:'https://www.openstreetmap.org/node/1',guide:{summary:'검증한 관광 안내문',source_url:'https://www.visitjeju.net/kr/detail/view?contentsid=TEST'},label:'관광 안내 원문 ↗',href:'https://www.visitjeju.net/kr/detail/view?contentsid=TEST',summary:'검증한 관광 안내문'},
      {source:'https://www.openstreetmap.org/node/1',guide:{summary:'지도를 관광 소개로 오인하면 안 됩니다',source_url:'https://www.openstreetmap.org/node/1'},label:'지도 원문 ↗',href:'https://www.openstreetmap.org/node/1',summary:'지도 메모'},
      {source:'https://www.jejudatahub.net/data/view/data/1349',guide:{summary:'실행할 수 없는 출처',source_url:'javascript:alert(1)'},label:'명부 원문 ↗',href:'https://www.jejudatahub.net/data/view/data/1349',summary:'지도 메모'}
    ]){const {host,controller:m}=setup({onOpenDetail:()=>false});m.setPlaces([{...point('source'),source_url:fixture.source,description:'지도 메모',tourism_guide:fixture.guide}]);host.querySelector('.jm-marker').fire('click');host.querySelector('.jm-detail-button').fire('click');const link=host.querySelector('.jm-detail-link');assert.equal(link.textContent,fixture.label);assert.equal(link.href,fixture.href);assert(host.querySelector('.jm-local-detail').textContent.includes(fixture.summary));assert.equal(link.rel,'noopener noreferrer');}
    checks.push('local fallback prefers a real tourism guide and labels map/registry sources accurately while rejecting false or unsafe guide links');
  }
  console.log(JSON.stringify({passed:true,checks,real_gps_used:false,external_network:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
