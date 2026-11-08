(function () {
  'use strict';
  const $=s=>document.querySelector(s), escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const safeURL=value=>{if(typeof value!=='string'||!value.trim())return '';try{const u=new URL(value,location.origin);return ['https:','http:'].includes(u.protocol)?u.href:'';}catch{return '';}};
  const formatDistance=value=>value!==null&&value!==undefined&&Number.isFinite(Number(value))?`직선 ${Number(value).toFixed(1)}km`:'거리 미확인';
  let locationUI,map,featured=[],mapPoints=[],lastPoints=[],routePoints=[],lastResponse=null,origin=null,originKind='',requestId=0;
  const pointCache=new Map();
  let exploreTab='tourism',tourismItems=[],tourismCursor=null,tourismRequest=0,tourismBBox=null,submittedTourismQuery='',lastGeometry=null,geometryRequest=0,mapViewRevision=0;
  function reveal(target,options={behavior:'smooth',block:'start'}){if(target?.tagName==='DETAILS')target.open=true;window.JejuPages?.reveal(target);target?.scrollIntoView(options);}
  function setTab(value){exploreTab=value==='food'?'food':'tourism';$('#tourism-form').hidden=exploreTab!=='tourism';$('#discovery-form').hidden=exploreTab!=='food';$('#tourism-summary').hidden=exploreTab!=='tourism';$('#tourism-results').hidden=exploreTab!=='tourism';$('#tourism-more').hidden=exploreTab!=='tourism'||!tourismCursor;$('#tourism-model-evidence').hidden=exploreTab!=='tourism';$('.food-results-wrap').hidden=exploreTab!=='food';document.querySelectorAll('[data-explore-tab]').forEach(b=>{const active=b.dataset.exploreTab===exploreTab;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});}
  async function loadTourism(replace=true,useBounds=false){
    const query=$('#tourism-query').value.trim();
    if(!replace&&query!==submittedTourismQuery)return loadTourism(true);
    if(!replace&&!tourismCursor)return;
    const viewAtRequest=mapViewRevision;
    const ticket=++tourismRequest;if(replace){submittedTourismQuery=query;tourismItems=[];tourismCursor=null;tourismBBox=useBounds?map?.getBounds?.():null;}$('#tourism-submit').disabled=true;$('#tourism-more').disabled=true;$('#tourism-summary').textContent='검증된 관광지 명부에서 조건을 확인하고 있어요…';
    const body={query,region:$('#tourism-region').value,category:$('#tourism-category').value,kind:'attraction',limit:6,radius_km:Number($('#discovery-radius').value),location:origin?{latitude:origin.latitude,longitude:origin.longitude}:null,...(tourismBBox?{bbox:tourismBBox}:{}),...(!replace&&tourismCursor?{cursor:tourismCursor}:{})};
    try{const response=await fetch('/api/tourism',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});const data=await response.json();if(ticket!==tourismRequest)return;if(!response.ok)throw new Error(data.error||'관광지 검색을 확인하지 못했습니다.');
      const seen=new Set(tourismItems.map(p=>p.id));for(const point of data.items||[])if(point.source_overlap_verified===true&&!seen.has(point.id)){tourismItems.push(point);seen.add(point.id);}tourismCursor=tourismItems.length<500?data.next_cursor:null;remember(tourismItems);
      const selection=$('#tourism-category').value;$('#tourism-category').replaceChildren();const all=document.createElement('option');all.value='all';all.textContent='전체 분류';$('#tourism-category').append(all);for(const cat of data.available_categories||[]){const option=document.createElement('option');option.value=cat.value;option.textContent=`${cat.label} (${cat.count})`;$('#tourism-category').append(option);}$('#tourism-category').value=selection||'all';if(!$('#tourism-category').value)$('#tourism-category').value='all';
      $('#tourism-summary').textContent=`교차확인 관광지${query?` · 검색어 ‘${query}’`:''} · 조건에 맞는 ${Number(data.total||0).toLocaleString('ko-KR')}개 기록 중 ${tourismItems.length}개 표시${data.radius_applied?' · 선택 위치 반경 적용':''}${tourismBBox?' · 현재 지도 범위':''}`;
      $('#tourism-results').innerHTML=tourismItems.length?tourismItems.map(p=>card(p,'tourism')).join(''):'<p class="discovery-empty">이 조건에 맞는 기록이 없습니다. 검색어·지역·반경을 넓혀 보세요.</p>';
      $('#tourism-more').hidden=exploreTab!=='tourism'||!tourismCursor;updateTourismMoreLabel();
      $('#tourism-model-evidence').textContent=`교차확인 명부의 이름·분류와 선택한 지역·거리 조건으로 조회했습니다. ${(data.warnings||[]).slice(0,2).join(' ')}`;
      if(viewAtRequest===mapViewRevision)showPlaces(tourismItems,{label:'교차확인 관광지 탐색 결과',view:'tourism'});
    }catch(error){if(ticket===tourismRequest){$('#tourism-summary').textContent=error.message;$('#tourism-results').innerHTML='';}}finally{if(ticket===tourismRequest){$('#tourism-submit').disabled=false;$('#tourism-more').disabled=false;}}
  }
  function updateTourismMoreLabel(){
    $('#tourism-more').textContent=$('#tourism-query').value.trim()===submittedTourismQuery?'관광지 6개 더 보기':'변경한 검색어로 찾기';
  }
  function modelMetricText(selected){
    if(!selected||typeof selected!=="object")return "정답 검색 성능은 아직 별도 평가하지 않았습니다.";
    const parts=[];
    if(Number.isFinite(selected.mae_share))parts.push(`구성비 MAE ${(selected.mae_share*100).toFixed(3)}%p`);
    if(Number.isFinite(selected.mae_per_hour))parts.push(`시간당 MAE ${selected.mae_per_hour.toFixed(2)}명/시간`);
    if(Number.isFinite(selected.wape_bucket_counts))parts.push(`구간 인원 WAPE ${(selected.wape_bucket_counts*100).toFixed(2)}%`);
    if(Number.isFinite(selected.rmse_per_hour))parts.push(`시간당 RMSE ${selected.rmse_per_hour.toFixed(2)}명/시간`);
    return parts.length?parts.join(' · '):"검증 보고서에서 평가 범위를 확인하세요.";
  }
  async function loadModels(){
    try{
      const response=await fetch('/api/models-info',{cache:'no-store'});if(!response.ok)throw new Error();
      const payload=await response.json();
      if(payload.service_version===23){
        const destinations={audience_distribution:'/explore#restaurants',dining_detail:'/explore#data-guide',assistant_guide_tfidf:'/planner#official-guide'};
        $('#model-cards').innerHTML=(payload.cards||[]).filter(c=>Object.hasOwn(destinations,c.id)).map(c=>{
          const score=Number.isFinite(c.metric?.percent)?`${c.metric.percent.toFixed(2)}% (${c.metric.hits}/${c.metric.total})`:'평가 확인 필요';
          return `<article class="model-card"><h3>${escape(c.title)}</h3><p>${escape(c.usage)}</p><strong>${escape(score)}</strong><small>${escape(c.metric?.name||'')}</small><details><summary>평가 범위</summary><p>${escape(c.evaluation_scope)}</p></details><a class="place-map-button" href="${destinations[c.id]}">기능 열기 ↗</a></article>`;
        }).join('');
        return;
      }
      const allowed=new Set(['tourism_tfidf','food_tfidf','audience_distribution','mobility_pattern']);
      $('#model-cards').innerHTML=(payload.cards||[]).filter(c=>allowed.has(c.id)).map(c=>{
        const dates=[...new Set(Object.values(c.period||{}).flat().filter(v=>typeof v==='string').map(v=>v.slice(0,10)))];
        const unit=c.training_rows_unit||'학습 기록',metric=modelMetricText(c.metrics?.selected_test);
        const split=c.split||{},test=split.test||{},testStart=test.start||split.test_start,testEnd=test.end||split.test_end;
        const evaluationPeriod=testStart&&testEnd?`평가 기간 ${testStart}–${testEnd} · 과거 관측 평가`:'';
        return `<article class="model-card"><div><span>${c.selected_serving_model?'검증으로 선택한 실자료 모델':'실데이터 검색 모델'}</span><b>${c.available?'준비됨':'미준비'}</b></div><h3>${escape(c.title)}</h3><p>${escape(c.usage||'')}</p><strong>${Number.isFinite(c.sample_count)?Number(c.sample_count).toLocaleString('ko-KR')+'개 '+escape(unit):'관측 기간과 검증 정보 제공'}</strong><small>${escape(dates.join(' / '))}</small><details><summary>학습 방법·검증·한계</summary><p>${escape(c.algorithm||'')}</p><p>${escape(metric)}</p>${evaluationPeriod?`<p>${escape(evaluationPeriod)}</p>`:''}<p>${escape(c.caveat||'')}</p></details><button type="button" class="place-map-button" data-model-use="${escape(c.id)}">이 모델을 쓰는 기능 열기 ↗</button></article>`;
      }).join('');
    }catch{$('#model-cards').textContent='모델 상태를 불러오지 못했습니다. 검색과 데이터 연결 상태를 확인하세요.';}
  }
  async function routeFor(result,focus=false){
    const ticket=++geometryRequest;routePoints=result?.status==='ok'&&result.data_mode==='reference'?(result.stops||[]).map(p=>({...p,id:p.poi_id})):[];lastGeometry=null;
    if(!routePoints.length){map?.clearRoute?.();$('#route-geometry-status').textContent=result?.message||'여행에 장소를 담아 방문 순서를 만들어 주세요.';return;}
    showPlaces(routePoints,{label:'내 일정의 방문 장소와 연결 경로',view:'route',focus});map?.setRoute?.({kind:'straight_line',stops:routePoints});$('#route-geometry-status').textContent='로컬 도로망에서 연결 경로를 계산하고 있어요…';
    const req=result.request||{},body={destination_ids:routePoints.map(p=>p.id),transport:req.transport||'car'};if(Number.isFinite(req.start_lat)&&Number.isFinite(req.start_lon))body.origin={latitude:req.start_lat,longitude:req.start_lon};if(Number.isFinite(req.end_lat)&&Number.isFinite(req.end_lon))body.destination={latitude:req.end_lat,longitude:req.end_lon};
    try{let geometry;if(result.route_geometry&&typeof result.route_geometry==='object'&&Array.isArray(result.route_geometry.stops)){geometry={...result.route_geometry};}else{const response=await fetch('/api/route-geometry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});geometry=await response.json();if(!response.ok)throw new Error(geometry.error||'도로 연결을 확인하지 못했어요.');}if(ticket!==geometryRequest)return;geometry.contains_private_location=Boolean(geometry.contains_private_location||body.origin||body.destination);if(body.origin)geometry.origin={...body.origin,private:true};if(body.destination)geometry.destination={...body.destination,private:true};lastGeometry=geometry;map?.setRoute?.(geometry);$('#route-geometry-status').textContent=`${geometry.kind==='road'?'OSM 도로 연결 참고 경로':'방문 순서 직선 연결'} · ${Number(geometry.distance_km||0).toFixed(1)}km. ${(geometry.warnings||[]).join(' ')}`;}catch(error){if(ticket===geometryRequest){lastGeometry={kind:'straight_line',stops:routePoints};map?.setRoute?.(lastGeometry);$('#route-geometry-status').textContent=`${error.message} 실제 도로 대신 방문 순서 점선을 표시합니다.`;}}
  }
  function updateSaved(items){const count=Array.isArray(items)?items.length:0;$('#map-trip-summary').textContent=count?`여행에 담은 ${count}곳 · 현재 일정 조건으로 순서와 경로를 만듭니다.`:'장소 상세나 결과 카드에서 여행에 담기를 눌러 주세요.';$('#map-create-route').disabled=!count;}

  function validPoint(point){return point&&point.latitude!==null&&point.longitude!==null&&Number.isFinite(Number(point.latitude))&&Number.isFinite(Number(point.longitude))&&Number(point.latitude)>=32.9&&Number(point.latitude)<=33.8&&Number(point.longitude)>=126&&Number(point.longitude)<=127.05;}
  function guideFor(item){const raw=item.tourism_guide;if(!raw||typeof raw.summary!=='string'||!raw.summary.trim()||typeof raw.source_url!=='string'||!/^https?:\/\//i.test(raw.source_url))return null;const url=safeURL(raw.source_url);if(!url)return null;try{if(/(^|\.)openstreetmap\.org$/i.test(new URL(url).hostname))return null;}catch{return null;}return {summary:raw.summary.trim().slice(0,1600),source_url:url};}
  function guideCardMarkup(item){const guide=guideFor(item);if(!guide)return '';const summary=guide.summary.length>100?guide.summary.slice(0,100)+'…':guide.summary;return `<p class="tourism-guide-preview">${escape(summary)}</p>`;}
  function sourceLink(item){const url=safeURL(item.source_url),guide=guideFor(item);let label='출처 원문';if(url){const host=new URL(url).hostname;label=/(^|\.)openstreetmap\.org$/i.test(host)?'지도 원문':/(^|\.)jejudatahub\.net$/i.test(host)?'명부 원문':/(^|\.)visitjeju\.net$/i.test(host)?'관광 안내 원문':label;}return `${guide?`<a class="tourism-guide-link" href="${escape(guide.source_url)}" target="_blank" rel="noopener noreferrer">관광 안내 원문 ↗</a>`:''}${url&&url!==guide?.source_url?`<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`:''}`;}
  function overlapMarkup(item){
    const proof=item.cross_source;if(item.source_overlap_verified!==true||!proof||typeof proof!=='object')return '';
    const hub=safeURL(proof.hub?.source_url),osm=safeURL(proof.osm?.source_url);
    const delta=typeof proof.distance_m==='number'&&Number.isFinite(proof.distance_m)&&proof.distance_m>=0?` · 두 자료의 좌표 차이 ${Math.round(proof.distance_m).toLocaleString('ko-KR')}m`:'';
    return `<details class="source-overlap"><summary>명부·지도 교차확인</summary><p>이름 정규화 일치${escape(delta)}. 두 자료에서 이름·위치가 일치한 기록이며 명부 주소·현재 운영·실제 입구의 정확성을 보증하지 않습니다.</p><div>${hub?`<a href="${escape(hub)}" target="_blank" rel="noopener noreferrer">빅데이터 명부 ↗</a>`:''}${osm?`<a href="${escape(osm)}" target="_blank" rel="noopener noreferrer">지도 원문 ↗</a>`:''}</div></details>`;
  }
  function addressLink(item){return item.address?`<a class="place-map-button" href="https://www.openstreetmap.org/search?${escape(new URLSearchParams({query:item.address}).toString())}" target="_blank" rel="noopener noreferrer">주소로 외부 지도 검색 ↗</a>`:'';}
  function remember(points){for(const p of points)if(p&&p.id)pointCache.set(String(p.id),p);while(pointCache.size>2500)pointCache.delete(pointCache.keys().next().value);}
  function mapView(name){document.querySelectorAll('[data-map-view]').forEach(b=>{const active=b.dataset.mapView===name;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});}
  function showPlaces(points,{focus=false,label='선택한 장소 위치',view='discovery'}={}){
    const clean=Array.isArray(points)?points.filter(validPoint).slice(0,500):[];remember(clean);mapPoints=clean;++mapViewRevision;if(view!=="route"){++geometryRequest;map?.clearRoute?.();}map?.setPlaces(clean);mapView(view);
    $('#map-context').textContent=`${label} · 좌표가 있는 ${clean.length}곳${clean.length?'':' · 지도에 표시할 위치가 없습니다.'}`;
    if(focus)reveal($('#map-explorer'),{behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
  }
  function onPointSelect(point){
    const key=String(point.id||'');map?.setSelectedIds([key]);
    const card=document.querySelector(`[data-discovery-card="${CSS.escape(key)}"]`);
    document.querySelectorAll('.discovery-card.selected').forEach(p=>p.classList.remove('selected'));
    if(card)card.classList.add('selected');
  }
  function canPlan(item){if((item.kind==='attraction'||String(item.id||'').startsWith('osm_tourism_'))&&item.source_overlap_verified!==true)return false;return featured.some(p=>p.id===item.id)||typeof item.plan_place_id==='string'&&(/^(hub1349_|osm_(?:tourism_)?(?:node|way|relation)_)/).test(item.plan_place_id);}
  function card(item,type='restaurant'){
    const mapped=validPoint(item),id=String(item.id),reason=[item.ranking_reason,Array.isArray(item.match_reason)?item.match_reason.join(' · '):item.match_reason||item.reason||''].filter(Boolean).join(' · ');
    const credit=mapped?(item.coordinate_quality||'명부 간 상호·주소 일치 좌표 · 실제 입구 미확인'):'좌표 없음 · 거리와 반경 미검증';
    const osm=item.source_platform==='openstreetmap'||item.source_overlap_verified===true&&Boolean(item.cross_source?.osm);
    return `<article class="discovery-card ${type==='destination'?'discovery-attraction':''}" data-discovery-card="${escape(id)}"><div class="discovery-card-top"><span>${type==='destination'?'함께 둘러볼 교차확인 관광지':type==='tourism'?'교차확인 관광지 · '+escape(item.category||'관광지'):escape(item.category||'음식점 명부')}</span><b>${formatDistance(item.distance_km)}</b></div><h3>${escape(item.name)}</h3>${guideCardMarkup(item)}<p>${escape(item.address||'원자료에 주소가 없습니다.')}</p>${item.requires_access_point?'<p class="access-note">탐방 입구·차량 접근 별도 확인</p>':""}<p class="coordinate-note">${escape(type==='destination'||type==='tourism'?'현재 영업·실제 입구는 방문 전 확인':mapped?'참조 좌표 · 현재 영업·실제 입구 별도 확인':'주소 기록 · 거리와 반경 미검증')}</p>${item.source_date?`<p class="coordinate-note">${osm?"지도 기록 편집":"자료 기준"} · ${escape(String(item.source_date).slice(0,10))}</p>`:""}<details class="discovery-more-info"><summary>검색 근거와 출처 보기</summary>${overlapMarkup(item)}${reason?`<p class="discovery-reason">${escape(reason)}</p>`:''}${item.evidence_terms?.length?`<p class="evidence-terms">학습 표현 · ${item.evidence_terms.slice(0,6).map(v=>escape(typeof v==="string"?v:v.term||"")).filter(Boolean).join(" · ")}</p>`:""}<p class="coordinate-note">${escape(credit)}</p>${item.source_date?`<p class="coordinate-note">${osm?(type==='tourism'?'지도 기록 편집':'지도 수집'):'기록 갱신'} · ${escape(String(item.source_date).slice(0,10))}</p>`:''}<div class="discovery-source-links">${sourceLink(item)}</div></details>${osm?'<p class="coordinate-note discovery-attribution"><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a> · <a href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noopener noreferrer">ODbL</a></p>':''}<div class="discovery-card-actions"><button type="button" class="place-map-button" data-place-detail="${escape(id)}">상세 보기</button>${mapped?`<button class="place-map-button" type="button" data-discovery-map="${escape(id)}">지도에서 보기 ↗</button>`:addressLink(item)}${canPlan(item)?`<button class="discovery-add" type="button" data-discovery-add="${escape(id)}">여행에 담기 ＋</button>`:''}</div></article>`;
  }
  function render(payload){
    lastResponse=payload;
    const foods=Array.isArray(payload.restaurants)?payload.restaurants:[],unknown=Array.isArray(payload.unmapped_restaurants)?payload.unmapped_restaurants:[],attractions=Array.isArray(payload.nearby_destinations)?payload.nearby_destinations.filter(p=>p.source_overlap_verified===true):[];
    remember([...foods,...unknown,...attractions]);lastPoints=[...foods,...attractions].filter(validPoint);
    const positioned=foods.filter(validPoint).length;
    $('#discovery-summary').textContent=`${payload.query?`‘${payload.query}’ 관련 기록`:'선택한 위치의 주변 기록'} · 식당 위치 기록 ${positioned}곳${unknown.length?` · 주소 기록 ${unknown.length}곳`:''} · 함께 볼 관광지 ${attractions.length}곳${payload.query?' · 음식어 일치 우선, 같은 단계는 '+(origin?'거리순':'텍스트 관련도순'):''}`;
    const basis=payload.nearby_basis||{};const attractionLabel=basis.type==='restaurant_reference_coordinate'?`‘${basis.restaurant_name}’ 주변 관광지 · 아래 거리는 식당 위치 기준입니다`:'선택한 기준 위치 주변의 대표 관광지';
    const hubFood=foods.filter(p=>p.source_platform==='jeju_datahub');
    const mapFood=foods.filter(p=>p.source_platform!=='jeju_datahub');
    const mapLabel=mapFood.every(p=>p.source_platform==='openstreetmap')?'OpenStreetMap 보조 위치 기록':'보조 위치 기록';
    $('#discovery-results').innerHTML=foods.length||attractions.length?`${hubFood.length?`<div class="discovery-result-label">제주데이터허브 음식점 · 확인된 참조 좌표</div>${hubFood.map(p=>card(p)).join('')}`:''}${mapFood.length?`<div class="discovery-result-label">${mapLabel} · 메뉴·영업 별도 확인</div>${mapFood.map(p=>card(p)).join('')}`:''}${attractions.length?`<div class="discovery-result-label">${escape(attractionLabel)}</div>${attractions.map(p=>card(p,'destination')).join('')}`:''}`:'<p class="discovery-empty">조건에 맞는 위치 기록이 없어요. 지역·거리 범위를 넓히거나 주소 기록을 살펴보세요.</p>';
    const addressDetails=$('#unmapped-food-details');
    addressDetails.hidden=!unknown.length;
    addressDetails.open=false;
    $('#unmapped-food-label').textContent=unknown.length&&unknown.every(p=>p.source_platform==='jeju_datahub')?'제주데이터허브 음식점 인허가 기록 · 주소':'관련 음식점 주소 기록';
    $('#unmapped-count').textContent=`${unknown.length}곳 표시`;
    $('#unmapped-food-results').innerHTML=unknown.map(p=>card(p)).join('');
    $('#discovery-warnings').textContent=(Array.isArray(payload.warnings)?payload.warnings:[]).join(' ');
    $("#food-model-evidence").textContent="명부에 기록된 음식점 이름·업종·주소와 선택 조건으로 조회했습니다.";
    showPlaces(lastPoints,{label:'최근 음식 취향·거리 탐색 결과'});
  }
  async function discover(){
    const ticket=++requestId;$('#discover-submit').disabled=true;$('#discovery-summary').textContent='취향과 기준 위치를 살펴보고 있어요…';
    const body={query:$('#food-wish').value.trim(),region:$('#discovery-region').value,radius_km:Number($('#discovery-radius').value),limit:6,location:origin?{latitude:origin.latitude,longitude:origin.longitude,...(Number.isFinite(origin.accuracy_m)?{accuracy_m:origin.accuracy_m}:{})}:null};
    try{
      const r=await fetch('/api/discover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});const result=await r.json();
      if(ticket!==requestId)return;if(!r.ok)throw new Error(result.error||'추천 기록을 불러오지 못했어요.');render(result);
    }catch(error){if(ticket===requestId){$('#discovery-summary').textContent=error.message||'연결 상태를 확인하세요.';$('#discovery-results').innerHTML='';$('#unmapped-food-details').hidden=true;}}
    finally{if(ticket===requestId)$('#discover-submit').disabled=false;}
  }
  function invalidateResults(message){
    ++requestId;++tourismRequest;lastPoints=[];lastResponse=null;$('#tourism-submit').disabled=false;$('#tourism-results').innerHTML='';$('#tourism-more').hidden=true;$('#tourism-model-evidence').textContent='';$('#tourism-summary').textContent='기준 위치나 조건이 바뀌었어요. 관광지 찾기를 눌러주세요.';tourismItems=[];tourismCursor=null;$('#discover-submit').disabled=false;$('#discovery-results').innerHTML='';$('#unmapped-food-results').innerHTML='';$('#unmapped-food-details').hidden=true;$('#discovery-warnings').textContent='';$('#discovery-summary').textContent=message||'조건이 바뀌었어요. 취향에 맞는 제주 찾기를 눌러주세요.';showPlaces(featured,{label:'대표 관광지 위치',view:'featured'});
  }
  function clearOrigin({message=true,cancelRequest=true}={}){
    if(cancelRequest)locationUI?.cancel();
    origin=null;originKind='';window.JejuLocationContext?.clear(cancelRequest?'clear':'request-start',{cancelRequest:false});map?.clearUserLocation();$('#origin-landmark').value='';$('#clear-location').hidden=true;$('#use-location').disabled=false;
    invalidateResults('위치 없이 검색하거나 기준 장소를 골라주세요.');
    if(message)$('#location-status').textContent='위치를 지웠습니다. 위치 권한 없이도 관광지와 음식을 검색할 수 있어요.';
  }
  function geolocate(){
    if(locationUI)locationUI.open();else $('#location-status').textContent='위치 안내를 불러오지 못했습니다. 페이지를 새로고침하거나 기준 장소를 선택해 주세요.';
  }
  function reset(){
    ++requestId;clearOrigin({message:false});pointCache.clear();remember(featured);$('#discovery-form').reset();$('#location-status').textContent='위치 권한 없이도 검색할 수 있어요. 센터 PC에서는 기준 장소를 직접 골라도 좋습니다.';
    $('#discover-submit').disabled=false;$('#discovery-results').innerHTML='';$('#unmapped-food-results').innerHTML='';$('#unmapped-food-details').hidden=true;$('#unmapped-food-details').open=false;$('#discovery-warnings').textContent='';$('#discovery-summary').textContent='음식이나 기준 장소를 고르면 연결 가능한 식당과 여행지를 찾아드려요.';
    lastPoints=[];routePoints=[];lastResponse=null;++geometryRequest;lastGeometry=null;$("#tourism-form").reset();tourismItems=[];tourismCursor=null;map?.clearRoute?.();$("#route-geometry-status").textContent="";setTab("tourism");map?.clearUserLocation();map?.setSelectedIds([]);showPlaces(featured,{label:'대표 관광지 위치',view:'featured'});map?.disableOnline?.();loadTourism(true);
  }
  $('#discovery-form').addEventListener('submit',event=>{event.preventDefault();discover();});
  $('#use-location').addEventListener('click',geolocate);
  $('#clear-location').addEventListener('click',()=>{clearOrigin();});
  $('#origin-landmark').addEventListener('change',event=>{
    const chosen=event.target.value;locationUI?.cancel();$('#use-location').disabled=false;map?.clearUserLocation();
    const p=chosen==='airport'?{latitude:33.506,longitude:126.492,name:'제주공항 부근'}:featured.find(p=>p.id===chosen);
    origin=p?{latitude:Number(p.latitude),longitude:Number(p.longitude)}:null;originKind=p?'manual':'';$('#clear-location').hidden=!p;
    if(p)window.JejuLocationContext?.setManual({...origin,label:p.name});else window.JejuLocationContext?.clear('manual-cleared');
    invalidateResults();
    $('#location-status').textContent=p?`${p.name} 기준으로 직선거리를 계산합니다. 실제 내 위치가 아닙니다.`:'위치 없이 관광지와 음식 기록을 찾습니다.';
  });
  $('#discovery-region').addEventListener('change',()=>invalidateResults());
  $('#discovery-radius').addEventListener('change',()=>invalidateResults());
  document.addEventListener('click',event=>{
    const tab=event.target.closest('[data-explore-tab]');if(tab){setTab(tab.dataset.exploreTab);if(exploreTab==='tourism')loadTourism(true);return;}const theme=event.target.closest('[data-tourism-theme]');if(theme){setTab('tourism');$('#tourism-query').value=theme.dataset.tourismTheme;loadTourism(true);return;}const detail=event.target.closest('[data-place-detail]');if(detail){const p=pointCache.get(detail.dataset.placeDetail);if(p)window.JejuTripBridge?.openPlace(p);return;}const modelUse=event.target.closest('[data-model-use]');if(modelUse){const id=modelUse.dataset.modelUse;if(id==='tourism_tfidf'||id==='food_tfidf'){setTab(id==='tourism_tfidf'?'tourism':'food');reveal($('#map-explorer'),{behavior:'smooth'});}else reveal($(id==='mobility_pattern'?'#mobility':id==='audience_distribution'?'#restaurants':'#planner'),{behavior:'smooth'});return;}const chip=event.target.closest('[data-food-wish]');if(chip){$('#food-wish').value=chip.dataset.foodWish;discover();return;}
    const view=event.target.closest('[data-map-view]');if(view){const key=view.dataset.mapView;if(key==='tourism'){setTab('tourism');if(tourismItems.length)showPlaces(tourismItems,{label:'교차확인 관광지 탐색 결과',view:'tourism'});else loadTourism(true);}else if(key==='featured')showPlaces(featured,{label:'대표 관광지 위치',view:key});else if(key==='discovery')showPlaces(lastPoints,{label:'최근 탐색 결과',view:key});else {window.JejuExplore.showRoute();}return;}
    const focus=event.target.closest('[data-discovery-map]');if(focus){const p=pointCache.get(focus.dataset.discoveryMap);if(p){showPlaces([p],{focus:true,label:`${p.name} 위치`});map?.setSelectedIds([String(p.id)]);}return;}
    const add=event.target.closest('[data-discovery-add]');if(add){const p=pointCache.get(add.dataset.discoveryAdd);if(p){const osm=p.source_platform==='openstreetmap';const point=featured.find(x=>x.id===p.id)||{...p,id:p.plan_place_id,featured:false,tags:['음식'],category:p.category||'음식점',description:osm?'OpenStreetMap 공동 편집 지도에 기록된 업소 위치입니다. 메뉴·현재 영업·실제 입구는 별도 확인하세요.':'인허가 명부의 상호·주소와 여행장소 좌표를 연결한 참조 위치입니다. 운영·메뉴·실제 입구는 별도 확인하세요.',source_name:osm?'© OpenStreetMap contributors · ODbL':'제주데이터허브 여행장소 좌표 참조',source_url:p.coordinate_source_url||p.source_url||'https://www.jejudatahub.net/data/view/data/1349'};if(p.kind==='attraction'||p.kind==='reference'){point.tags=Array.isArray(p.tags)?p.tags:[];point.category=p.category||'관광·자연 장소';point.description=p.description||'공개 원자료의 관광·여행장소 기록입니다. 방문 조건과 실제 입구는 원문에서 확인하세요.';}window.JejuTripBridge?.addPlace(point);}return;}
  });
  window.addEventListener('jeju:reset',reset);
  window.addEventListener('jeju:route',event=>routeFor(event.detail));
  window.addEventListener('jeju:saved',event=>updateSaved(event.detail.items));
  window.addEventListener('jeju:pagechange',event=>{if(event.detail?.path==='/explore')map?.refresh?.();});
  window.addEventListener('jeju:locationchange',event=>{
    const next=event.detail?.location||null;
    const same=(!next&&!origin)||(next&&origin&&next.latitude===origin.latitude&&next.longitude===origin.longitude&&originKind===(next.source==='device'?'gps':'manual'));
    if(same)return;origin=next?{latitude:next.latitude,longitude:next.longitude,...(Number.isFinite(next.accuracy_m)?{accuracy_m:next.accuracy_m}:{})}:null;originKind=next?(next.source==='device'?'gps':'manual'):'';
    if(originKind==='gps')map?.setUserLocation(origin);else map?.clearUserLocation();
    $('#clear-location').hidden=!next;if(originKind!=='manual')$('#origin-landmark').value='';
    if(next)$('#location-status').textContent=next.source==='device'?'기기 추정 위치를 지도 탐색과 상담에 함께 사용합니다.':`${next.label||'선택한 장소'} 기준입니다. 실제 내 위치가 아닙니다.`;
    invalidateResults('기준 위치가 바뀌었습니다. 조건에 맞는 장소를 다시 찾아주세요.');
  });
  window.addEventListener('pagehide',()=>{locationUI?.cancel();origin=null;originKind='';map?.clearUserLocation();});
  window.addEventListener('pageshow',event=>{if(event.persisted)reset();});
  function showReturnRoute(geometry){
    if(!geometry||!Array.isArray(geometry.coordinates)||geometry.coordinates.length<2||!map)return false;
    ++geometryRequest;
    map.disableOnline?.();
    showPlaces([],{focus:true,view:'route'});
    if(!map.setRoute({...geometry,stops:[],contains_private_location:true}))return false;
    map.fitRoute?.();
    $('#map-context').textContent='기존 도착지까지 돌아가는 참고 경로 · 오프라인 지도';
    $('#route-geometry-status').textContent=`${geometry.kind==='road'?'OSM 도로 연결 참고 경로':'출발·도착 직선 연결'} · ${Number(geometry.distance_km||0).toFixed(1)}km. ${(geometry.warnings||[]).join(' ')}`;
    return true;
  }
  function searchFoodFromQuery(query, region) {
    if (typeof query !== 'string' || !query.trim() || query.trim().length > 100) return false;
    if (region !== undefined && !['all', 'north', 'east', 'south', 'west'].includes(region)) return false;
    // Keep the user's already chosen origin; never request or infer device location.
    ++tourismRequest;
    setTab('food');
    $('#food-wish').value = query.trim();
    if (region !== undefined) $('#discovery-region').value = region;
    discover();
    reveal($('#map-explorer'), {behavior:'smooth', block:'start'});
    return true;
  }
  window.JejuExplore={searchFoodFromQuery,showPlaces,showReturnRoute,reset,showRoute(){if(lastGeometry){showPlaces(routePoints,{focus:true,label:'내 일정 연결 경로',view:'route'});map?.setRoute?.(lastGeometry);$('#route-geometry-status').textContent=`${lastGeometry.kind==='road'?'OSM 도로 연결 참고 경로':'방문 순서 직선 연결'} · ${Number(lastGeometry.distance_km||0).toFixed(1)}km. ${(lastGeometry.warnings||[]).join(' ')}`;}else {const result=window.JejuTripBridge?.getRoute();if(result)routeFor(result,true);else {$('#route-geometry-status').textContent='여행에 장소를 담은 뒤 경로 만들기를 눌러주세요.';reveal($('#map-explorer'),{behavior:'smooth'});}}},searchTourismFromQuery(query,region){setTab('tourism');$('#tourism-query').value=query;$('#tourism-region').value=region;loadTourism(true);reveal($('#map-explorer'),{behavior:'smooth'});}};
  $('#tourism-query').addEventListener('input',updateTourismMoreLabel);
  $('#tourism-form').addEventListener('submit',event=>{event.preventDefault();loadTourism(true);});$('#tourism-more').addEventListener('click',()=>loadTourism(false));$('#tourism-bounds').addEventListener('click',()=>loadTourism(true,true));$('#tourism-region').addEventListener('change',()=>loadTourism(true));$('#tourism-category').addEventListener('change',()=>loadTourism(true));$('#tourism-kind').addEventListener('change',()=>{$('#tourism-category').value='all';loadTourism(true);});
  $('#map-create-route').addEventListener('click',async()=>{$('#map-create-route').disabled=true;$('#route-geometry-status').textContent='담은 장소의 방문 순서를 만들고 있어요…';try{const result=await window.JejuTripBridge?.createMapRoute();if(result?.status!=='ok')$('#route-geometry-status').textContent=result?.message||'시간과 장소 조건을 확인하세요.';}catch(error){$('#route-geometry-status').textContent=error.message;}finally{updateSaved(window.JejuTripBridge?.getSaved());}});
  async function init(){
    map=window.JejuMap?.mount($('#jeju-map'),{onSelect:onPointSelect,onOpenDetail:point=>window.JejuTripBridge?.openPlace(point)});
    locationUI=window.JejuLocation?.mount({button:$('#use-location'),statusElement:$('#location-status'),host:$('.shared-origin'),
      onStart(){clearOrigin({message:false,cancelRequest:false});},
      onSuccess(point){
        const {latitude,longitude,accuracy_m}=point;
        const inJeju=Number.isFinite(latitude)&&Number.isFinite(longitude)&&latitude>=32.9&&latitude<=33.8&&longitude>=126&&longitude<=127.05;
        origin=inJeju?{latitude,longitude,...(Number.isFinite(accuracy_m)?{accuracy_m}:{} )}:null;originKind=inJeju?'gps':'';
        $('#origin-landmark').value='';$('#clear-location').hidden=!inJeju;
        window.JejuLocationContext?.setDevice(point);
        if(inJeju)map?.setUserLocation(origin);else map?.clearUserLocation();
        if(exploreTab==='tourism')loadTourism(true);else discover();
      },
      onRevoked(){clearOrigin({message:false,cancelRequest:false});}
    });
    window.JejuLocationContext?.bind(locationUI);
    fetch('/api/offline-roads',{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>map?.setRoads?.(data)).catch(()=>{});loadModels();updateSaved(window.JejuTripBridge?.getSaved());setTab('tourism');
    if(!map)$('#map-context').textContent='지도 모듈을 불러오지 못했습니다. 주소·출처 검색을 이용해 주세요.';
    try{const r=await fetch('/api/destinations',{cache:'no-store'});if(!r.ok)throw new Error();const data=await r.json();featured=(data.items||[]).filter(p=>p.source_overlap_verified===true&&p.featured!==false&&validPoint(p));remember(featured);for(const p of featured){const option=document.createElement('option');option.value=p.id;option.textContent=p.name;$('#origin-landmark').append(option);}loadTourism(true);}catch{$('#map-context').textContent='관광지 위치를 불러오지 못했어요. 연결 상태를 확인하세요.';}
  }
  init();
}());
