(function () {
  'use strict';
  const labels={prompt:'확인 필요 · 요청 시 브라우저가 결정',granted:'허용됨 · 새 권한창이 생략될 수 있음',denied:'차단됨 · 사이트 또는 앱 설정 확인',unknown:'확인할 수 없음 · 요청으로 확인 가능'};
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  function mount({button,statusElement,host,onStart=()=>{},onSuccess=()=>{},onRevoked=()=>{}}={}) {
    if(!button||!statusElement||!host)return null;
    let generation=0,pending=false,watchdog=null,destroyed=false,permission='unknown',permissionObject=null,diagnosticVersion=0,usedLocation=false;
    const waiters=[];
    function settle(result){for(const resolve of waiters.splice(0))resolve(result);}
    const originalLabel=button.textContent;
    const details=el('details','location-diagnostics');details.id='location-diagnostics';
    details.append(el('summary','','위치 권한·설정 확인'));
    const body=el('div','location-diagnostics-body'),facts=el('dl'),rows={};
    for(const [key,label] of [['origin','현재 사이트'],['secure','보안 연결 조건'],['api','위치 기능'],['policy','문서의 위치 정책'],['permission','브라우저 위치 권한'],['request','위치 요청 상태']]){
      const row=el('div');row.append(el('dt','',label));rows[key]=el('dd');rows[key].id='location-'+key+'-state';row.append(rows[key]);facts.append(row);
    }
    rows.request.textContent='아직 요청하지 않았습니다.';
    const refreshButton=el('button','location-action','위치 상태 확인');refreshButton.type='button';refreshButton.id='location-check';
    const guide=el('div','location-help');guide.append(el('strong','','팝업이 없거나 위치를 받지 못할 때'));
    const steps=el('ol');for(const text of ['Chrome 또는 Edge에서 아래 주소를 직접 엽니다. 앱 안의 브라우저와 비교해 볼 수 있습니다.','주소창 옆 사이트 정보 → 위치를 허용하고 페이지를 새로고침합니다. 이미 허용·차단된 사이트는 권한창이 다시 나오지 않을 수 있습니다.','Windows 설정 → 개인정보 및 보안(Windows 10은 개인정보) → 위치에서 위치 서비스를 확인합니다.','허용했어도 PC의 위치 공급자나 네트워크가 위치를 계산하지 못할 수 있습니다. 기준 장소를 직접 선택해 계속 이용할 수 있습니다.'])steps.append(el('li','',text));
    const address=el('code','location-browser-address',location.origin+'/');
    const links=el('p','location-help-links');for(const [title,url] of [['Chrome 위치 설정','https://support.google.com/chrome/answer/142065?hl=ko'],['Windows 위치 서비스','https://support.microsoft.com/en-us/windows/privacy/windows-location-service-and-privacy']]){const a=el('a','',title+' ↗');a.href=url;a.target='_blank';a.rel='noopener noreferrer';links.append(a);}
    guide.append(steps,address,links,el('p','','사이트는 브라우저·Windows의 차단을 대신 해제할 수 없습니다. 위치 상태 확인은 좌표를 요청하지 않습니다.'));
    body.append(facts,refreshButton,guide);details.append(body);host.append(details);
    const dialog=el('dialog','location-consent-dialog');dialog.id='location-consent-dialog';dialog.setAttribute('aria-labelledby','location-consent-title');
    const title=el('h2','','내 위치로 가까운 제주 찾기');title.id='location-consent-title';title.setAttribute('tabindex','-1');
    const close=el('button','location-consent-close','×');close.type='button';close.setAttribute('aria-label','위치 사용 안내 닫기');
    const copy=el('div','location-consent-copy');copy.append(el('p','','현재 위치를 사용해 지도 탐색과 여행 상담에서 가까운 관광지·먹거리를 찾고 직선거리와 반경을 계산합니다. 위치 사용은 선택 사항입니다.'));
    const list=el('ul');for(const text of ['받는 정보: 브라우저가 추정한 위도·경도와 정확도.','사용 범위: 이 탭과 이 PC의 로컬 추천 서버. 위치를 파일·모델·대화에 저장하거나 외부 지도에 보내지 않습니다.','위치 지우기·새 여행 시작·탭 종료로 앱의 위치 사용을 중단합니다. 브라우저 권한은 사이트 설정에서 별도로 취소할 수 있습니다.','PC에는 GPS가 없을 수 있으며 브라우저·OS의 위치 서비스가 네트워크를 사용할 수 있습니다. 허용해도 수신을 보장하지 않습니다.'])list.append(el('li','',text));copy.append(list);
    const preciseLabel=el('label','location-precise-choice'),precise=el('input');precise.type='checkbox';precise.id='location-precise';preciseLabel.append(precise,el('span','','정밀 위치로 시도 · 더 오래 걸릴 수 있어요'));
    const note=el('p','location-consent-note','이 버튼의 확인과 브라우저의 위치 권한 허용은 별도입니다. 이미 허용·차단된 경우 새 권한창이 나오지 않을 수 있습니다.');
    const actions=el('div','location-consent-actions'),agree=el('button','location-primary','동의하고 위치 요청'),decline=el('button','location-action','기준 장소로 찾기');agree.id='location-consent-agree';agree.type=decline.type='button';actions.append(agree,decline);
    dialog.append(close,title,copy,preciseLabel,note,actions);document.body.append(dialog);
    function policyAllowed(){try{const policy=document.permissionsPolicy||document.featurePolicy;return policy&&typeof policy.allowsFeature==='function'?policy.allowsFeature('geolocation'):null;}catch{return null;}}
    function environment(){rows.origin.textContent=location.origin;rows.secure.textContent=window.isSecureContext?'지원 · HTTPS 또는 신뢰할 수 있는 로컬 주소':'지원 안 됨 · HTTPS 또는 localhost 필요';rows.api.textContent=navigator.geolocation?'브라우저에 기능 있음':'브라우저에 기능 없음';const policy=policyAllowed();rows.policy.textContent=policy===false?'차단됨 · 상위 앱·프레임 또는 사이트 정책 확인':policy===true?'허용됨':'확인할 수 없음';rows.permission.textContent=labels[permission]||labels.unknown;}
    function permissionChanged(next){permission=['prompt','granted','denied'].includes(next)?next:'unknown';environment();if(permission==='denied'&&(usedLocation||pending)){cancel();onRevoked();statusElement.textContent='위치 권한이 철회되었거나 차단되었습니다. 앱의 위치를 지웠습니다. 기준 장소를 직접 선택할 수 있습니다.';rows.request.textContent='권한 변경으로 위치 사용 중지';}}
    async function refresh(){
      if(destroyed)return;const version=++diagnosticVersion;environment();
      if(!navigator.permissions||typeof navigator.permissions.query!=='function'){permission='unknown';environment();return;}
      try{const result=await navigator.permissions.query({name:'geolocation'});if(destroyed||version!==diagnosticVersion)return;if(permissionObject)permissionObject.onchange=null;permissionObject=result;permissionChanged(result.state);result.onchange=()=>{if(!destroyed)permissionChanged(result.state);};}
      catch{if(!destroyed&&version===diagnosticVersion){permission='unknown';environment();}}
    }
    function closeDialog(){if(dialog.open){dialog.close();if(button.isConnected!==false)button.focus();}}
    function open(){if(destroyed||pending)return;refresh();if(!dialog.open)dialog.showModal();dialog.scrollTop=0;title.focus();}
    function request(){if(destroyed)return Promise.resolve({status:'unavailable',reason:'destroyed'});return new Promise(resolve=>{waiters.push(resolve);open();});}
    function busy(value){pending=value;button.disabled=value;button.textContent=value?'위치를 확인하고 있어요…':originalLabel;}
    function cancel(reason='cancelled',{preserveLocation=false}={}){generation++;if(watchdog!==null){clearTimeout(watchdog);watchdog=null;}const wasActive=pending||usedLocation;usedLocation=preserveLocation&&usedLocation;busy(false);if(wasActive)rows.request.textContent=usedLocation?'위치 요청 취소 · 기존 위치 유지':'기기 위치 사용 중지';closeDialog();settle({status:'cancelled',reason});}
    function fail(code,noResponse=false){
      const messages={1:'브라우저·앱·Windows 중 하나에서 위치 사용이 허용되지 않았습니다. 위치 권한·설정 확인을 펼쳐 사이트 권한을 확인하세요.',2:'기기에서 위치를 계산하지 못했습니다. 권한이 허용되어도 Windows 위치 서비스·네트워크·위치 공급자 상태에 따라 실패할 수 있습니다.',3:'위치 확인 시간이 초과됐습니다. 위치 서비스와 네트워크를 확인한 뒤 다시 시도하거나 기준 장소를 선택하세요.'};
      statusElement.textContent=noResponse?'브라우저에서 위치 응답이 오지 않았습니다. 권한창이 열려 있다면 선택을 마친 후 다시 시도하세요. 앱 안에서 창이 나오지 않으면 Chrome/Edge에서 같은 주소를 열어 비교해 보세요.':messages[code]||'브라우저의 위치 요청을 실행하지 못했습니다. 기준 장소를 직접 선택해 주세요.';
      rows.request.textContent=noResponse?'응답 없음':code===1?'사용 불가 · 권한/정책 확인':code===2?'위치 공급자 수신 실패':code===3?'시간 초과':'요청 실패';details.open=true;settle({status:'error',reason:noResponse?'no-response':code===1?'denied':code===2?'unavailable':code===3?'timeout':'provider-error'});refresh();
    }
    function startRequest(){
      if(destroyed||pending)return;const high=precise.checked===true;closeDialog();onStart();
      if(!window.isSecureContext){statusElement.textContent='위치는 HTTPS 또는 이 PC의 localhost/127.0.0.1 주소에서 요청할 수 있습니다.';rows.request.textContent='보안 조건 미충족';details.open=true;settle({status:'unavailable',reason:'insecure'});refresh();return;}
      if(!navigator.geolocation){statusElement.textContent='이 브라우저는 위치 기능을 제공하지 않습니다. Chrome/Edge에서 같은 주소를 열거나 기준 장소를 골라주세요.';rows.request.textContent='브라우저 기능 없음';details.open=true;settle({status:'unavailable',reason:'missing-api'});refresh();return;}
      if(policyAllowed()===false){statusElement.textContent='이 화면의 문서 정책이 위치 사용을 차단합니다. 상위 앱·프레임에서 허용되어야 합니다. Chrome/Edge에서 사이트를 직접 열어 비교해 보세요.';rows.request.textContent='문서 정책 차단';details.open=true;settle({status:'unavailable',reason:'policy'});refresh();return;}
      const ticket=++generation,timeout=high?30000:20000;busy(true);rows.request.textContent='위치 요청 중';statusElement.textContent='브라우저 권한이 필요하면 허용을 선택해 주세요. 이미 허용된 경우 창 없이 위치를 확인합니다.';
      function finish(){if(destroyed||ticket!==generation||!pending)return false;generation++;clearTimeout(watchdog);watchdog=null;busy(false);return true;}
      watchdog=setTimeout(()=>{if(finish())fail(0,true);},timeout+15000);
      try{navigator.geolocation.getCurrentPosition(position=>{
        if(!finish())return;const c=position&&position.coords,latitude=c&&c.latitude,longitude=c&&c.longitude,accuracy=c&&c.accuracy;
        if(typeof latitude!=='number'||typeof longitude!=='number'||!Number.isFinite(latitude)||!Number.isFinite(longitude)||latitude< -90||latitude>90||longitude< -180||longitude>180){fail(0);return;}
        const inJeju=latitude>=32.9&&latitude<=33.8&&longitude>=126&&longitude<=127.05;usedLocation=inJeju;
        rows.request.textContent=inJeju?'위치 수신 완료 · 제주 권역':'위치 수신 완료 · 제주 권역 밖';
        statusElement.textContent=inJeju?`기기 추정 위치를 기준으로 직선거리를 계산합니다.${Number.isFinite(accuracy)&&accuracy>=0?` 기기 보고 정확도 약 ${Math.round(accuracy).toLocaleString('ko-KR')}m.`:''}`:'위치는 수신했지만 제주 권역 밖입니다. 현재 좌표로 제주 주변 추천을 계산하지 않습니다. 제주공항 등 기준 장소를 직접 선택해 주세요.';
        const point={latitude,longitude,...(Number.isFinite(accuracy)&&accuracy>=0?{accuracy_m:accuracy}:{})};settle({status:'success',position:point,inJeju});onSuccess(point);refresh();
      },error=>{if(finish())fail(error&&error.code);},{enableHighAccuracy:high,timeout,maximumAge:60000});}
      catch{if(finish())fail(0);}
    }
    agree.addEventListener('click',startRequest);close.addEventListener('click',()=>{closeDialog();settle({status:'cancelled',reason:'closed'});});decline.addEventListener('click',()=>{if(usedLocation){cancel('declined');onRevoked();}else{closeDialog();settle({status:'cancelled',reason:'declined'});}statusElement.textContent='기기 위치를 요청하지 않았습니다. 거리 계산의 기준 장소를 직접 선택해 주세요.';});dialog.addEventListener('cancel',event=>{event.preventDefault();closeDialog();settle({status:'cancelled',reason:'closed'});});refreshButton.addEventListener('click',refresh);refresh();
    return {open,request,cancel,refresh,destroy(){if(destroyed)return;cancel('destroyed');destroyed=true;++diagnosticVersion;if(permissionObject)permissionObject.onchange=null;dialog.remove();details.remove();}};
  }
  window.JejuLocation={mount};
}());
