(function () {
  'use strict';
  const MAX_TURNS=30,MAX_INPUT=300;
  const menu=[['관광지 추천','관광지 추천'],['먹거리 추천','먹거리 추천'],['장소 정보','장소 정보'],['일정 사용법','일정 사용법'],['데이터 안내','데이터 안내']];
  const $id=id=>document.getElementById(id);
  function el(tag,className,text){const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=String(text);return node;}
  function button(text,className,action){const node=el('button',className,text);node.type='button';if(action)node.addEventListener('click',action);return node;}
  const launcher=button('길벗 상담','jc-launcher',toggle);launcher.id='jeju-chat-launcher';launcher.setAttribute('aria-label','길벗 여행 상담 열기');launcher.setAttribute('aria-haspopup','dialog');launcher.setAttribute('aria-expanded','false');launcher.setAttribute('aria-controls','jeju-chat-dialog');
  const bubble=el('span','jc-launcher-symbol','말');bubble.setAttribute('aria-hidden','true');launcher.prepend(bubble);
  const panel=el('dialog','jc-panel');panel.id='jeju-chat-dialog';panel.setAttribute('aria-labelledby','jeju-chat-title');panel.setAttribute('aria-describedby','jeju-chat-intro');
  const header=el('header','jc-header'),heading=el('div');heading.append(el('small','jc-eyebrow','YOUR JEJU COMPANION'));const title=el('h2','','길벗 여행 상담');title.id='jeju-chat-title';heading.append(title);
  const closeButton=button('×','jc-close',close);closeButton.setAttribute('aria-label','길벗 상담 닫기');header.append(heading,closeButton);
  const intro=el('p','jc-intro','버튼과 짧은 질문으로 안내하는 오프라인 상담');intro.id='jeju-chat-intro';
  const tools=el('div','jc-tools');const menuButton=button('처음 메뉴','jc-tool',()=>send('처음으로'));const resetButton=button('새 대화','jc-tool',()=>reset(true));const tripButton=button('내 일정 보기 ↗','jc-tool',()=>{close(false);if(window.JejuTripBridge?.getRoute())window.JejuExplore?.showRoute();else {window.JejuPages?.reveal($id('planner'));$id('planner')?.scrollIntoView({behavior:'smooth',block:'start'});}});tools.append(menuButton,resetButton,tripButton);
  const locationBar=el('div','jc-location');
  const locationNote=el('p','jc-location-note');locationNote.id='chat-location-status';locationNote.setAttribute('role','status');
  const locationActions=el('div','jc-location-actions');
  const useLocation=button('내 위치 사용','jc-location-use',()=>requestLocation());useLocation.id='chat-use-location';
  const chooseLocation=button('기준 장소 선택','jc-tool',()=>{close(false);window.JejuPages?.reveal($id('map-explorer'));$id('map-explorer')?.scrollIntoView({behavior:'smooth',block:'start'});$id('origin-landmark')?.focus();});
  const clearLocation=button('위치 지우기','jc-tool',()=>{window.JejuLocationContext?.clear('chat-clear');locationDeclined=true;updateLocation();});clearLocation.id='chat-clear-location';
  locationActions.append(useLocation,chooseLocation,clearLocation);locationBar.append(locationNote,locationActions);
  const log=el('div','jc-log');log.id='jeju-chat-log';log.setAttribute('role','log');log.setAttribute('aria-label','길벗 상담 대화');log.setAttribute('aria-live','polite');log.setAttribute('aria-relevant','additions text');log.setAttribute('tabindex','0');
  const status=el('p','jc-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const errorBox=el('div','jc-error');errorBox.hidden=true;const errorText=el('p');errorText.setAttribute('role','alert');const retryButton=button('다시 시도','jc-retry',()=>{if(lastRequest)send(lastRequest.message,{repeat:true,requestState:lastRequest.state});});errorBox.append(errorText,retryButton);
  const form=el('form','jc-form');form.setAttribute('aria-label','여행 상담 질문');const inputLabel=el('label','jc-sr-only','짧은 여행 질문');inputLabel.htmlFor='jeju-chat-input';const input=el('input','jc-input');input.id='jeju-chat-input';input.type='text';input.maxLength=MAX_INPUT;input.placeholder='예: 북부 해변 추천해 줘';input.autocomplete='off';input.setAttribute('aria-describedby','jeju-chat-help');const sendButton=button('보내기','jc-send');sendButton.type='submit';form.append(inputLabel,input,sendButton);
  const help=el('p','jc-help','질문은 300자까지 입력할 수 있어요. 대화는 이 탭에서만 유지됩니다.');help.id='jeju-chat-help';
  const method=el('details','jc-method');method.append(el('summary','','어떻게 안내하나요?'));const methodCopy=el('p','','상담은 질문의 단어를 규칙으로 읽고, 준비된 이용 안내와 공개 장소 명부를 찾습니다. 현재 운영 여부는 방문 전 확인해 주세요.');const guideLink=el('a','jc-place-source','학습 모델로 공식 관광지 소개 찾기 ↗');guideLink.href='/planner#official-guide';guideLink.addEventListener('click',()=>close(false));const stats=el('p','jc-stats','준비된 안내와 공개 장소 자료를 찾아 답합니다.');method.append(methodCopy,guideLink,stats);
  panel.append(header,intro,tools,locationBar,log,status,errorBox,form,help,method);document.body.append(launcher,panel);
  let state={},generation=0,pending=null,lastRequest=null,returnFocus=null,statusLoaded=false,nextReplyStart=null,locationDeclined=false,waitingLocation=false,requestLocationKey=null, lastNearbyLocationKey=null;
  function safeState(raw){const clean={};if(!raw||typeof raw!=='object'||Array.isArray(raw))return clean;if(['all','east','west','south','north'].includes(raw.region))clean.region=raw.region;if(typeof raw.nearby==='boolean')clean.nearby=raw.nearby;if(typeof raw.topic==='string')clean.topic=raw.topic.slice(0,40);if(typeof raw.last_place_id==='string')clean.last_place_id=raw.last_place_id.slice(0,120);if(Array.isArray(raw.choice_ids))clean.choice_ids=raw.choice_ids.filter(v=>typeof v==='string'&&v.length<=120).slice(0,10);if(typeof raw.last_query==='string')clean.last_query=raw.last_query.slice(0,100);if(Number.isInteger(raw.offset)&&raw.offset>=0&&raw.offset<=1000)clean.offset=raw.offset;
    if(Number.isFinite(raw.radius_km)&&raw.radius_km>=1&&raw.radius_km<=100)clean.radius_km=raw.radius_km;
    if(Number.isInteger(raw.result_limit)&&raw.result_limit>=1&&raw.result_limit<=5)clean.result_limit=raw.result_limit;
    return clean;}
  function sourceURL(raw){if(typeof raw!=='string'||raw.length>2000)return '';try{const url=new URL(raw);return ['https:','http:'].includes(url.protocol)?url.href:'';}catch{return '';}}
  function mapped(item){return typeof item.latitude==='number'&&typeof item.longitude==='number'&&Number.isFinite(item.latitude)&&Number.isFinite(item.longitude)&&item.latitude>=32.9&&item.latitude<=33.8&&item.longitude>=126&&item.longitude<=127.1&&typeof item.plan_place_id==='string'&&item.plan_place_id.length>0&&item.plan_place_id.length<=120;}
  function updateSavedButtons(items = window.JejuTripBridge?.getSaved?.()) {
    if (!Array.isArray(items)) return;
    const ids = new Set(items.map(item=>String(item.id ?? item.poi_id)));
    for (const control of log.querySelectorAll('.jc-place-add')) {
      const saved = ids.has(control.getAttribute('data-place-id'));
      control.disabled = saved;
      control.textContent = saved ? '여행에 담았어요' : '여행에 담기 ＋';
    }
  }
  function setBusy(value){useLocation.disabled=value;chooseLocation.disabled=value;clearLocation.disabled=value;sendButton.disabled=value;input.disabled=value;menuButton.disabled=value;retryButton.disabled=value;log.setAttribute('aria-busy',String(value));panel.querySelectorAll('.jc-quick').forEach(node=>node.disabled=value);status.textContent=value?'자료에서 답변을 찾고 있어요…':'';}
  function scrollLatest(){log.scrollTop=log.scrollHeight;}
  function scrollReplyStart(article){if(!article||article.parentElement!==log)return;const top=article.getBoundingClientRect().top-log.getBoundingClientRect().top+log.scrollTop;log.scrollTop=Math.max(0,top-10);}
  function appendTurn(role,text,cards=[],replies=[]){
    const article=el('article','jc-turn jc-'+role);article.append(el('span','jc-speaker',role==='user'?'나':'길벗'));article.append(el('p','jc-text',String(text||'').slice(0,12000)));
    if(role==='assistant'){
      log.querySelectorAll('.jc-quick-replies').forEach(node=>node.remove());
      (Array.isArray(cards)?cards:[]).slice(0,6).forEach((raw,index)=>{if(!raw||typeof raw!=='object'||typeof raw.id!=='string'||typeof raw.name!=='string')return;const item={...raw};const card=el('section','jc-place');card.append(el('h3','',`${index+1}. ${item.name.slice(0,180)}`));const line=[item.region_label||({north:'북부',east:'동부',west:'서부',south:'남부'})[item.region],item.category].filter(v=>typeof v==='string'&&v).join(' · ');if(line)card.append(el('p','jc-place-meta',line));if(Number.isFinite(item.distance_km))card.append(el('p','jc-place-distance',`기준 위치에서 직선 ${item.distance_km.toFixed(1)}km`));if(item.address)card.append(el('p','jc-place-address',String(item.address).slice(0,350)));if(item.match_reason)card.append(el('p','jc-place-reason',Array.isArray(item.match_reason)?item.match_reason.join(' · '):String(item.match_reason).slice(0,500)));
        const actions=el('div','jc-place-actions');actions.append(button('상세 보기','jc-place-action',()=>{close(false);window.JejuTripBridge?.openPlace(item);}));
        const visitReview = item.visit_review?.required === true ? item.visit_review : null;
        if (visitReview) {
          const notice = el('div','jc-place-reason');
          notice.append(el('strong','','일정에 담기 전에 방문 조건 확인'));
          const reasons = Array.isArray(visitReview.reasons) ? visitReview.reasons : [];
          for (const reason of reasons.slice(0, 6)) {
            if (typeof reason?.message === 'string') notice.append(el('p','',reason.message.slice(0, 500)));
          }
          const reviewURL = sourceURL(visitReview.source_url);
          if (reviewURL) {
            const link = el('a','jc-place-source','방문 조건 출처 ↗');
            link.href = reviewURL;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            notice.append(link);
          }
          card.append(notice);
        }
        if (mapped(item)) {
          actions.append(button('지도 보기','jc-place-action',()=>{
            close(false);
            window.JejuExplore?.showPlaces([{...item,id:item.plan_place_id}],{focus:true,label:item.name+' 위치',view:'discovery'});
          }));
          if (!visitReview) {
            const add = button('여행에 담기 ＋','jc-place-action jc-place-add',()=>{
              if (window.JejuTripBridge?.addPlace({...item,id:item.plan_place_id})) {
                add.textContent = '여행에 담았어요';
                add.disabled = true;
                status.textContent = item.name+'을 여행에 담았습니다.';
              }
            });
            add.setAttribute('data-place-id',item.plan_place_id);
            actions.append(add);
          }
        }
        if(item.source_overlap_verified===true&&item.cross_source){card.append(el('p','jc-place-reason','빅데이터 명부·지도에서 이름과 위치를 교차확인한 관광 후보'));const hubURL=sourceURL(item.cross_source.hub?.source_url);if(hubURL){const hubLink=el('a','jc-place-source','빅데이터 명부 ↗');hubLink.href=hubURL;hubLink.target='_blank';hubLink.rel='noopener noreferrer';actions.append(hubLink);}}
        const url=sourceURL(item.source_url);if(url){const link=el('a','jc-place-source','기록 출처 ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';actions.append(link);}card.append(actions);
        if(item.id.startsWith('osm_')||item.data_license==='ODbL-1.0'||item.source_platform==='openstreetmap'){const credit=el('p','jc-place-credit');const copyright=el('a','','OpenStreetMap contributors');copyright.href='https://www.openstreetmap.org/copyright';copyright.target='_blank';copyright.rel='noopener noreferrer';const license=el('a','','ODbL');license.href='https://opendatacommons.org/licenses/odbl/1-0/';license.target='_blank';license.rel='noopener noreferrer';credit.append(el('span','','© '),copyright,el('span','',' · '),license);card.append(credit);}article.append(card);
      });
      const quick=el('div','jc-quick-replies');(Array.isArray(replies)?replies:[]).slice(0,8).forEach(raw=>{if(!raw||typeof raw.label!=='string'||typeof raw.message!=='string'||!raw.message.trim()||raw.message.length>MAX_INPUT)return;quick.append(button(raw.label.slice(0,60),'jc-quick',()=>send(raw.message)));});if(quick.children.length)article.append(quick);
    }
    log.append(article);if(role==='assistant')updateSavedButtons();while(log.children.length>MAX_TURNS)log.firstElementChild.remove();if(role==='assistant'){if(panel.open){nextReplyStart=null;scrollReplyStart(article);}else nextReplyStart=article;}else scrollLatest();return article;
  }
  function welcome(){appendTurn('assistant','안녕하세요, 길벗이에요. 어떤 제주를 찾고 계세요?\n“내 주변 관광지 추천”, “가까운 흑돼지 식당”처럼 물어보세요. 위치 사용에 동의하면 반경 20km의 좌표 확인 기록을 찾아드려요. 위치 없이 지역을 골라도 좋습니다.',[],menu.map(([label,message])=>({label,message})));}
  async function loadStatus(){if(statusLoaded)return;statusLoaded=true;try{const response=await fetch('/api/chat/status',{cache:'no-store'});if(!response.ok)return;const data=await response.json();if(Number.isInteger(data.prepared_answers)&&data.prepared_answers>=0){stats.textContent=`준비된 장소 안내 ${data.prepared_answers.toLocaleString('ko-KR')}개 출처 기록${Number.isInteger(data.faq_count)?` · 이용 안내 ${data.faq_count}개`:''}. 같은 실제 장소의 출처별 기록이 포함될 수 있어요.`;}}catch{/* The conversation can still be used if the status check fails. */}}
  function open(){if(!panel.open){const active=document.activeElement;returnFocus=active&&!panel.contains(active)?active:launcher;if(typeof panel.show==='function')panel.show();else panel.setAttribute('open','');}launcher.setAttribute('aria-expanded','true');launcher.setAttribute('aria-label','길벗 여행 상담 닫기');bubble.textContent='×';loadStatus();if(!pending)input.focus();else closeButton.focus();if(nextReplyStart){scrollReplyStart(nextReplyStart);nextReplyStart=null;}}
  function close(restore=true){if(panel.open){if(typeof panel.close==='function')panel.close();else panel.removeAttribute('open');}launcher.setAttribute('aria-expanded','false');launcher.setAttribute('aria-label','길벗 여행 상담 열기');bubble.textContent='말';if(restore){const target=returnFocus&&returnFocus.isConnected&&(!returnFocus.getClientRects||returnFocus.getClientRects().length)?returnFocus:launcher;target.focus();}}
  function toggle(){if(panel.open)close();else open();}
  function reset(focus=false){generation++;if(pending){clearTimeout(pending.timeout);pending.controller?.abort();pending=null;}if(waitingLocation)window.JejuLocationContext?.cancel?.('chat-reset');waitingLocation=false;requestLocationKey=null;lastNearbyLocationKey=null;state={};lastRequest=null;nextReplyStart=null;input.value='';errorBox.hidden=true;errorText.textContent='';log.replaceChildren();setBusy(false);welcome();if(focus&&panel.open)input.focus();}
  function currentLocation(){return window.JejuLocationContext?.get()||null;}
  function locationKey(point=currentLocation()){return point?`${point.source}:${point.latitude}:${point.longitude}`:'';}
  function updateLocation(note){
    const point=currentLocation();clearLocation.hidden=!point;
    locationNote.textContent=note||(point?(point.source==='manual'?`${point.label||'선택한 장소'} 기준 · 실제 내 위치가 아닙니다.`:'주변을 물으면 동의한 기기 위치를 기준으로 찾아요.'):'위치 없이 상담 중 · 추천할 때 위치 사용을 선택할 수 있어요.');
    useLocation.textContent=point?'내 위치 다시 확인':'내 위치 사용';
  }
  function locationMessage(result){return result.status==='outside-jeju'?'제주 권역 밖의 위치입니다. 제주 내 기준 장소를 선택하거나 지역별로 찾아주세요.':result.status==='cancelled'?'위치 사용을 건너뛰었습니다. 지역·음식 조건으로 계속 찾아드려요.':'위치를 받지 못했습니다. 지도 탐색의 위치 권한·설정 확인을 살펴보거나 기준 장소를 선택해 주세요.';}
  async function obtainLocation(){
    waitingLocation=true;status.textContent='위치 사용 안내에서 동의 여부를 선택해 주세요.';
    try{return window.JejuLocationContext?await window.JejuLocationContext.request():{status:'unavailable'};}
    catch{return {status:'error'};}
    finally{waitingLocation=false;}
  }
  async function requestLocation(){
    if(pending)return;const ticket=++generation;pending={controller:null,timeout:null};setBusy(true);
    const result=await obtainLocation();if(ticket!==generation)return;
    pending=null;setBusy(false);locationDeclined=result.status!=='success';updateLocation(result.status==='success'?null:locationMessage(result));
    if(result.status==='success')appendTurn('assistant','위치를 확인했어요. 가까운 관광지나 먹거리를 골라주세요. 거리는 직선거리로 표시합니다.',[],[{label:'가까운 관광지','message':'내 주변 관광지 추천'},{label:'가까운 맛집','message':'내 주변 맛집 추천'}]);
  }
  async function send(raw,{repeat=false,requestState}={}){
    if(pending)return;const message=typeof raw==='string'?raw.trim():'';if(!message){status.textContent='질문을 입력하거나 메뉴를 골라주세요.';input.focus();return;}if(message.length>MAX_INPUT){status.textContent='질문을 300자 이내로 줄여주세요.';return;}
    const bodyState=safeState(requestState||state),ticket=++generation,controller=new AbortController();pending={controller,timeout:null};lastRequest={message,state:bodyState};if(!repeat)appendTurn('user',message);input.value='';errorBox.hidden=true;setBusy(true);
    try{
      let didAsk = false;
      let shareLocation = false;
      while (ticket === generation) {
        const selected = currentLocation();
        const point = shareLocation ? selected : null;
        requestLocationKey = point ? locationKey(point) : null;
        const body = {message, state:bodyState};
        if (lastNearbyLocationKey !== null && lastNearbyLocationKey !== locationKey(selected)) body.restart_page = true;
        if (point) {
          body.location = {
            latitude:point.latitude, longitude:point.longitude, source:point.source,
            ...(point.source === 'manual' && point.label ? {label:point.label} : {}),
            ...(Number.isFinite(point.accuracy_m) ? {accuracy_m:point.accuracy_m} : {}),
          };
        } else if (!selected && locationDeclined) {
          body.location_declined = true;
        }
        pending.timeout=setTimeout(()=>controller.abort(),30000);
        const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store',signal:controller.signal});const data=await response.json();clearTimeout(pending?.timeout);
        if(ticket!==generation)return;if(!response.ok||typeof data.reply!=='string')throw new Error('chat_unavailable');
        if (data.needs_location && !didAsk) {
          didAsk = true;
          if (currentLocation()) {
            shareLocation = true;
            continue;
          }
          if (!locationDeclined && window.JejuLocationContext) {
            const consent = await obtainLocation();
            if (ticket !== generation) return;
            shareLocation = consent.status === 'success';
            locationDeclined = !shareLocation;
            updateLocation(shareLocation ? null : locationMessage(consent));
            continue;
          }
        }
        state = safeState(data.state);
        if (data.location_used && point) lastNearbyLocationKey = locationKey(point);
        else if (!state.nearby) lastNearbyLocationKey = null;
        appendTurn('assistant',data.reply,data.cards,data.quick_replies);
        break;
      }
    }
    catch{if(ticket!==generation)return;errorText.textContent='상담 연결을 확인하지 못했어요. 잠시 후 다시 시도해 주세요.';errorBox.hidden=false;scrollLatest();}
    finally{if(ticket===generation){clearTimeout(pending?.timeout);pending=null;requestLocationKey=null;setBusy(false);if(panel.open)input.focus();}}
  }
  window.addEventListener('jeju:saved',event=>updateSavedButtons(event.detail?.items));
  window.addEventListener('jeju:locationchange',()=>{
    if(currentLocation())locationDeclined=false;
    updateLocation();
    if(pending&&!waitingLocation&&requestLocationKey!==null&&requestLocationKey!==locationKey()){
      generation++;clearTimeout(pending.timeout);pending.controller?.abort();pending=null;requestLocationKey=null;lastRequest=null;setBusy(false);status.textContent='기준 위치가 바뀌어 이전 추천 요청을 취소했어요. 다시 질문해 주세요.';
    }
  });
  form.addEventListener('submit',event=>{event.preventDefault();send(input.value);});panel.addEventListener('cancel',event=>{event.preventDefault();close();});panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();close();}});
  window.addEventListener('jeju:reset',()=>{reset(false);locationDeclined=false;updateLocation();});window.addEventListener('pagehide',()=>reset(false));window.JejuChat={open,close,toggle,reset:()=>reset(true)};welcome();updateLocation();if(window.JejuPages?.consumeChatRequest?.())open();
}());
