/* Distinct local pages keep the current tab's trip and search state in memory. */
(function (global) {
  'use strict';
  const pages={
    '/':{title:'탐라따라 — 나에게 맞는 속도로'},
    '/explore':{title:'지도·먹거리 | 탐라따라',eyebrow:'FIND YOUR NEXT PLACE',heading:'가까이 있는 제주를 찾아보세요.',description:'지도에서 위치를 확인하고, 마음에 드는 관광지와 먹거리를 여행에 담아보세요.'},
    '/planner':{title:'내 여행 | 탐라따라',eyebrow:'YOUR DAY IN JEJU',heading:'마음에 담은 곳으로, 나만의 하루.',description:'확인한 출발지와 시간에 맞춰 방문 순서를 만들어 보세요.'},
    '/climate':{title:'AI 여행시기 기온 참고 | 탐라따라',navPath:'/planner',eyebrow:'A SEASON TO DISCOVER',heading:'어느 계절의 제주를 만나고 싶나요?',description:'과거 관측을 학습한 모델로 네 관측지점의 계절별 기온 경향을 비교하세요. 현재 날씨 예보는 제공하지 않습니다.'},
    '/flowers':{title:'꽃으로 고르는 여행 시기 | 탐라따라',navPath:'/planner',eyebrow:'JEJU, IN BLOOM',heading:'마음에 드는 꽃으로, 계절을 골라보세요.',description:'과거 공개 꽃행사 일정과 기온 AI를 함께 비교하고, 확인된 개화 관측과 온라인 예보를 따로 살펴보세요.'},
    '/insights':{title:'관광지 방문 흐름 | 탐라따라',eyebrow:'JEJU, THROUGH THE DATA',heading:'계절마다 달라지는 제주의 방문 흐름.',description:'검증한 관광지의 과거 월별 입장객 수와 계절별 경향을 살펴보세요.'},
    '/about':{title:'데이터 안내 | 탐라따라',eyebrow:'THE DATA BEHIND YOUR JOURNEY',heading:'우리의 추천은 어디에서 왔을까요?',description:'사용한 공개 자료와 학습 모델, 안내할 수 있는 범위를 확인하세요.'}
  };
  const anchors={top:'/',destinations:'/',regions:'/',planner:'/planner','trip-result':'/planner',mobility:'/planner','map-explorer':'/explore',restaurants:'/explore','place-explorer':'/explore',sources:'/about','model-lab':'/about',data:'/about'};
  const sections=Array.from(document.querySelectorAll('[data-page]'));
  const nav=Array.from(document.querySelectorAll('[data-page-link]'));
  const main=document.getElementById('main-content'),intro=document.getElementById('page-intro');
  let current=null,pendingChat=false;
  const savedScroll=new Map();
  function normalize(path){const clean=path.length>1?path.replace(/\/+$/,''):path;return clean==='/chat'||Object.hasOwn(pages,clean)?clean:null;}
  function routeForAnchor(hash){
    let id;try{id=decodeURIComponent(hash.replace(/^#/,''));}catch{return null;}
    if(id==='assistant')id='planner-form';
    const target=document.getElementById(id);
    const route=anchors[id]||target?.closest('[data-page]')?.dataset.page;
    return route?{path:route,hash:target?'#'+encodeURIComponent(id):''}:null;
  }
  function resolve(raw){
    let url;try{url=new URL(raw,global.location.href);}catch{return null;}
    if(url.origin!==global.location.origin||url.search)return null;
    const path=normalize(url.pathname);if(path===null)return null;
    if(path==='/chat')return {path:'/',hash:'',url:'/',chat:true};
    const anchored=url.hash&&routeForAnchor(url.hash);
    if(anchored)return {...anchored,url:anchored.path+anchored.hash};
    if(url.hash&&url.hash!=='#main-content')return null;
    return {path,hash:url.hash,url:path+url.hash};
  }
  function openParents(node){for(let parent=node?.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;}
  function paint(route,{focus=true,scroll=true,pop=false}={}){
    if(current!==null)savedScroll.set(current,global.scrollY||0);
    current=route.path;const info=pages[current];
    sections.forEach(section=>{section.hidden=section.dataset.page!==current;});
    nav.forEach(link=>{const active=link.dataset.pageLink===(info.navPath||current);link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
    document.body.dataset.page=current;document.title=info.title;
    intro.hidden=current==='/';
    if(!intro.hidden){document.getElementById('page-eyebrow').textContent=info.eyebrow;document.getElementById('page-title').textContent=info.heading;document.getElementById('page-description').textContent=info.description;}
    document.querySelector('.main-nav')?.classList.remove('open');
    const menu=document.getElementById('mobile-menu');if(menu){menu.setAttribute('aria-expanded','false');menu.setAttribute('aria-label','메뉴 열기');}
    global.dispatchEvent(new CustomEvent('jeju:pagechange',{detail:{path:current}}));
    let target=null;if(route.hash){try{target=document.getElementById(decodeURIComponent(route.hash.slice(1)));}catch{/* Ignore malformed anchors. */}}
    if(target)openParents(target);
    if(focus){const heading=current==='/'?document.getElementById('hero-title'):document.getElementById('page-title');const focusTarget=target||heading||main;if(!focusTarget.hasAttribute('tabindex'))focusTarget.setAttribute('tabindex','-1');focusTarget.focus({preventScroll:true});}
    if(scroll){if(target)target.scrollIntoView({behavior:'auto',block:'start'});else global.scrollTo({top:pop?(savedScroll.get(current)||0):0,behavior:'auto'});}
  }
  function navigate(raw,options={}){
    const route=resolve(raw);if(!route)return false;
    if(route.chat){
      document.querySelector('.main-nav')?.classList.remove('open');
      const menu=document.getElementById('mobile-menu');if(menu){menu.setAttribute('aria-expanded','false');menu.setAttribute('aria-label','메뉴 열기');}
      if(global.JejuChat){if(typeof global.JejuChat.toggle==='function')global.JejuChat.toggle();else global.JejuChat.open();}else pendingChat=true;return true;
    }
    if(options.replace)global.history.replaceState({jejuPage:route.path},'',route.url);
    else if(global.location.pathname+global.location.hash!==route.url)global.history.pushState({jejuPage:route.path},'',route.url);
    paint(route,options);return true;
  }
  function reveal(target,options={}){
    let node=target;if(typeof node==='string'){try{node=document.querySelector(node);}catch{return null;}}
    if(!node)return null;
    const path=node.closest('[data-page]')?.dataset.page;
    if(path&&path!==current)navigate(path,{focus:true,scroll:false,...options});
    openParents(node);return node;
  }
  document.addEventListener('click',event=>{
    if(event.defaultPrevented||event.button>0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
    const link=event.target.closest('a[href]');if(!link||link.hasAttribute('download')||(link.target&&link.target!=='_self'))return;
    const href=link.getAttribute('href');if(href==='#main-content'){event.preventDefault();main.focus();return;}
    if(!resolve(href))return;event.preventDefault();navigate(href);
  });
  global.addEventListener('popstate',()=>{const route=resolve(global.location.href);if(route){if(route.chat){navigate('/',{replace:true});navigate('/chat');}else paint(route,{pop:true});}});
  global.addEventListener('hashchange',()=>{const route=resolve(global.location.href);if(route)navigate(route.url,{replace:true});});
  global.JejuPages=Object.freeze({navigate,reveal,getPath:()=>current,consumeChatRequest(){const requested=pendingChat;pendingChat=false;return requested;}});
  const initial=resolve(global.location.href)||{path:'/',hash:'',url:'/'};
  if(initial.chat)pendingChat=true;
  if(global.location.pathname+global.location.hash!==initial.url)global.history.replaceState({jejuPage:initial.path},'',initial.url);
  paint(initial,{focus:false,scroll:Boolean(initial.hash)});
})(window);
