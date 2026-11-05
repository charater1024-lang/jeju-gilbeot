/* Local source-approved hero. Main hero copy and the existing application stay intact. */
(function (global) {
  "use strict";
  const VERIFIED = Object.freeze({"seongsan":{"name":"성산일출봉","region_label":"성산 동부","image":"/assets/seongsan.jpg","source_id":"visitjeju_CONT_000000000500349"},"hyeopjae":{"name":"협재해수욕장","region_label":"한림 서부","image":"/assets/hyeopjae.jpg","source_id":"visitjeju_CONT_000000000500697"},"hamdeok":{"name":"함덕해수욕장","region_label":"조천 북동부","image":"/assets/hamdeok.jpg","source_id":"visitjeju_CONT_000000000500693"},"hallasan":{"name":"한라산국립공원","region_label":"한라산 중산간","image":"/assets/hallasan.jpg","source_id":"visitjeju_CONT_000000000500685"},"saryeoni":{"name":"사려니숲길","region_label":"조천 중산간","image":"/assets/saryeoni.jpg","source_id":"visitjeju_CONT_000000000500281"},"cheonjiyeon":{"name":"천지연폭포","region_label":"서귀포 남부","image":"/assets/cheonjiyeon.jpg","source_id":"visitjeju_CONT_000000000500618"},"jeongbang":{"name":"정방폭포","region_label":"서귀포 남부","image":"/assets/jeongbang.jpg","source_id":"visitjeju_CONT_000000000500531"},"seopjikoji":{"name":"섭지코지","region_label":"성산 동부","image":"/assets/seopjikoji.jpg","source_id":"visitjeju_CONT_000000000500343"},"udo":{"name":"우도(해양도립공원)","region_label":"우도","image":"/assets/udo.jpg","source_id":"visitjeju_CONT_000000000500477"},"osulloc":{"name":"오설록 티 뮤지엄","region_label":"안덕 서부","image":"/assets/osulloc.jpg","source_id":"visitjeju_CONT_000000000500457"}});
  const ANCHORS = new Set(["#destinations","#regions","#planner","#sources"]);
  const nameKey=value=>value.normalize("NFKC").toLocaleLowerCase("ko-KR").replace(/[^\p{L}\p{N}]/gu,"");
  const instances = new WeakMap();

  function fallbackConfig() {
    return {schema_version:1,interval_ms:5000,autoplay:true,slides:Object.entries(VERIFIED).map(([id,slide])=>({id,...slide,caption:slide.name,href:"#destinations",focal_x:id==="cheonjiyeon"?65:50,focal_y:id==="seongsan"?54:50}))};
  }
  function validateConfig(raw) {
    if(!raw||typeof raw!=="object"||Array.isArray(raw)||raw.schema_version!==1||!Array.isArray(raw.slides)||(raw.slides.length<1||raw.slides.length>10))throw new Error("풍경 설정 형식이 올바르지 않습니다.");
    if(!Number.isInteger(raw.interval_ms)||raw.interval_ms<5000||raw.interval_ms>12000||typeof raw.autoplay!=="boolean")throw new Error("풍경 전환 설정을 확인하세요.");
    const seen=new Set();
    const slides=raw.slides.map(slide=>{
      if(!slide||typeof slide!=="object"||!Object.hasOwn(VERIFIED,slide.id)||seen.has(slide.id))throw new Error("확인되지 않았거나 중복된 관광지입니다.");
      const canonical=VERIFIED[slide.id];
      if(slide.image!==canonical.image||slide.source_id!==canonical.source_id||slide.region_label!==canonical.region_label||!ANCHORS.has(slide.href))throw new Error("확인된 로컬 사진과 관광지 출처만 사용할 수 있습니다.");
      if(typeof slide.name!=="string"||!slide.name.trim()||slide.name.length>60||/[<>\u0000-\u001f\u007f]/.test(slide.name)||nameKey(slide.name)!==nameKey(canonical.name))throw new Error("확인한 관광지와 같은 명칭만 사용할 수 있습니다.");
      if(typeof slide.caption!=="string"||!slide.caption.trim()||slide.caption.length>60)throw new Error("풍경 설명은 60자 이내여야 합니다.");
      for(const key of ["focal_x","focal_y"])if(typeof slide[key]!=="number"||!Number.isFinite(slide[key])||slide[key]<0||slide[key]>100)throw new Error("사진 초점 범위를 확인하세요.");
      seen.add(slide.id);
      return {id:slide.id,...canonical,name:slide.name.trim(),caption:slide.caption.trim(),href:slide.href,focal_x:slide.focal_x,focal_y:slide.focal_y};
    });
    return {schema_version:1,interval_ms:raw.interval_ms,autoplay:raw.autoplay,slides};
  }
  async function readConfig(options) {
    if(options.config)return validateConfig(options.config);
    const target=new URL(options.configUrl||"/api/hero-slides",global.location.origin);
    if(target.origin!==global.location.origin||target.pathname!=="/api/hero-slides"||target.search||target.hash)throw new Error("로컬 풍경 설정 경로만 사용할 수 있습니다.");
    const controller=new AbortController(),timer=global.setTimeout(()=>controller.abort(),4500);
    try {
      const response=await global.fetch(target.href,{signal:controller.signal,credentials:"same-origin",headers:{Accept:"application/json"},cache:"no-store"});
      if(!response.ok)throw new Error("풍경 설정 응답을 확인하지 못했습니다.");
      return validateConfig(await response.json());
    } finally {global.clearTimeout(timer);}
  }
  function element(tag,className,text) {
    const node=global.document.createElement(tag);
    if(className)node.className=className;
    if(text!==undefined)node.textContent=text;
    return node;
  }
  function button(className,text,label) {
    const node=element("button",className,text);node.type="button";node.setAttribute("aria-label",label);return node;
  }
  async function build(hero,options) {
    let config;
    try {config=await readConfig(options);}catch{return null;}
    const slides=config.slides,cache=new Map(),failed=new Set(),listeners=[];
    let current=0,activeLayer=0,timer=null,autoplay=config.autoplay,hovered=false,focused=false,destroyed=false,serial=0;
    const motion=global.matchMedia?global.matchMedia("(prefers-reduced-motion: reduce)"):null;
    if(motion?.matches)autoplay=false;
    function preload(index) {
      const image=slides[index].image;
      if(cache.has(image))return cache.get(image);
      const ready=new Promise(resolve=>{
        const img=new global.Image();let settled=false;
        const timeout=global.setTimeout(()=>finish(false),8000);
        function finish(ok){if(settled)return;settled=true;global.clearTimeout(timeout);img.onload=null;img.onerror=null;resolve(ok);}
        img.onload=()=>finish(img.naturalWidth>0);img.onerror=()=>finish(false);img.decoding="async";img.src=image;
        if(img.complete&&img.naturalWidth>0)finish(true);
      });
      cache.set(image,ready);return ready;
    }
    // If no initial real image loads, preserve the original static hero.
    if(!await preload(0)){instances.delete(hero);return null;}
    const oldPhoto=hero.querySelector("#hero-photo"),oldCaption=hero.querySelector(".hero-caption");
    const oldHidden=oldCaption?.hidden,oldAria=oldPhoto?.getAttribute("aria-hidden");
    const visual=element("div","hero-carousel-visual");visual.setAttribute("role","img");
    const layers=[element("div","hero-carousel-layer is-visible"),element("div","hero-carousel-layer")];
    layers.forEach(layer=>{layer.setAttribute("aria-hidden","true");visual.append(layer);});
    const ui=element("div","hero-carousel-ui");ui.setAttribute("role","group");ui.setAttribute("aria-roledescription","사진 슬라이드");ui.setAttribute("aria-label","교차확인 관광지의 풍경");
    const caption=element("div","hero-carousel-caption"),region=element("p","hero-carousel-region"),link=element("a","hero-carousel-name"),count=element("span","hero-carousel-count");
    caption.append(region,link,count);
    const controls=element("div","hero-carousel-controls"),previous=button("hero-carousel-arrow","‹","이전 풍경 사진"),next=button("hero-carousel-arrow","›","다음 풍경 사진"),dots=element("div","hero-carousel-dots");
    dots.setAttribute("role","group");dots.setAttribute("aria-label","풍경 사진 선택");
    const dotButtons=slides.map((slide,index)=>{const dot=button("hero-carousel-dot","",`${index+1} / ${slides.length} ${slide.name}`);dots.append(dot);return dot;});
    const toggle=button("hero-carousel-toggle","정지","사진 자동 전환 일시정지");
    toggle.title="마우스나 키보드로 조작하는 동안 자동 전환을 잠시 멈춥니다.";
    const live=element("p","hero-carousel-live");live.setAttribute("role","status");live.setAttribute("aria-live","polite");live.setAttribute("aria-atomic","true");
    controls.append(previous,dots,next,toggle);ui.append(caption,controls,live);
    const shade=hero.querySelector(".hero-shade");hero.insertBefore(visual,shade||hero.firstChild);hero.append(ui);
    hero.classList.add("hero-has-carousel");hero.classList.toggle("hero-carousel-reduced",Boolean(motion?.matches));
    if(oldCaption)oldCaption.hidden=true;if(oldPhoto)oldPhoto.setAttribute("aria-hidden","true");
    function paintLayer(layer,index) {
      const slide=slides[index];layer.style.backgroundImage=`url("${slide.image}")`;layer.style.backgroundPosition=`${slide.focal_x}% ${slide.focal_y}%`;layer.dataset.sourceId=slide.source_id;
    }
    function canPlay(){return autoplay&&!hovered&&!focused&&!global.document.hidden&&!destroyed;}
    function stopTimer(){if(timer!==null)global.clearTimeout(timer);timer=null;}
    function syncControls() {
      dotButtons.forEach((dot,index)=>{dot.classList.toggle("active",index===current);dot.setAttribute("aria-pressed",String(index===current));dot.disabled=failed.has(index);});
      toggle.textContent=autoplay?"정지":"재생";toggle.setAttribute("aria-label",autoplay?"사진 자동 전환 일시정지":"사진 자동 전환 시작");toggle.setAttribute("aria-pressed",String(autoplay));
      const slide=slides[current];region.textContent=slide.region_label;link.textContent=slide.caption;link.href=slide.href;link.dataset.sourceId=slide.source_id;
      link.setAttribute("aria-label",`${slide.name} · ${slide.region_label} · 여행지 둘러보기`);count.textContent=`${current+1} / ${slides.length}`;
      visual.setAttribute("aria-label",`${current+1} / ${slides.length} · ${slide.name} · ${slide.region_label} 실제 풍경 사진`);hero.dataset.heroSlide=slide.id;hero.dataset.heroSourceId=slide.source_id;
      ui.dataset.playing=String(canPlay());
    }
    function schedule(){stopTimer();syncControls();if(canPlay())timer=global.setTimeout(()=>advance(1,false),config.interval_ms);}
    async function goTo(index,manual=true) {
      stopTimer();const ticket=++serial,target=((index%slides.length)+slides.length)%slides.length;
      if(target===current){schedule();return true;}
      const loaded=await preload(target);
      if(destroyed||ticket!==serial)return false;
      if(!loaded){failed.add(target);if(manual)live.textContent="선택한 풍경 사진을 불러오지 못했습니다. 다른 사진을 골라주세요.";schedule();return false;}
      const incoming=1-activeLayer;paintLayer(layers[incoming],target);layers[incoming].classList.add("is-visible");layers[activeLayer].classList.remove("is-visible");activeLayer=incoming;current=target;
      syncControls();if(manual)live.textContent=`${current+1} / ${slides.length} ${slides[current].name}, ${slides[current].region_label}`;schedule();return true;
    }
    async function advance(direction,manual=true) {
      for(let step=1;step<slides.length;step++){const target=(current+direction*step+slides.length)%slides.length;if(!failed.has(target)){await goTo(target,manual);return;}}
      autoplay=false;schedule();
    }
    function on(target,type,handler){target.addEventListener(type,handler);listeners.push(()=>target.removeEventListener(type,handler));}
    on(previous,"click",()=>advance(-1,true));on(next,"click",()=>advance(1,true));
    dotButtons.forEach((dot,index)=>on(dot,"click",()=>goTo(index,true)));
    on(toggle,"click",()=>{autoplay=!autoplay;live.textContent=autoplay?"자동 전환을 켰습니다. 조작을 마치면 시작합니다.":"자동 전환을 멈췄습니다.";schedule();});
    on(ui,"mouseenter",()=>{hovered=true;schedule();});on(ui,"mouseleave",()=>{hovered=false;schedule();});
    on(ui,"focusin",()=>{focused=true;schedule();});
    on(ui,"focusout",()=>{global.setTimeout(()=>{focused=ui.contains(global.document.activeElement);if(!destroyed)schedule();},0);});
    on(ui,"keydown",event=>{
      if(event.altKey||event.ctrlKey||event.metaKey)return;
      if(event.key==="ArrowLeft"){event.preventDefault();advance(-1,true);}
      else if(event.key==="ArrowRight"){event.preventDefault();advance(1,true);}
      else if(event.key==="Home"){event.preventDefault();goTo(0,true);}
      else if(event.key==="End"){event.preventDefault();goTo(slides.length-1,true);}
    });
    on(global.document,"visibilitychange",schedule);
    if(motion){const changed=()=>{hero.classList.toggle("hero-carousel-reduced",motion.matches);if(motion.matches)autoplay=false;schedule();};if(motion.addEventListener){on(motion,"change",changed);}else if(motion.addListener){motion.addListener(changed);listeners.push(()=>motion.removeListener(changed));}}
    focused=ui.contains(global.document.activeElement);
    try{hovered=ui.matches(":hover");}catch{/* Hover detection is optional on older kiosk browsers. */}
    paintLayer(layers[0],0);syncControls();schedule();
    slides.forEach((_,index)=>{if(index)preload(index).then(ok=>{if(!ok&&!destroyed){failed.add(index);syncControls();}});});
    return Object.freeze({
      next:()=>advance(1,true),previous:()=>advance(-1,true),goTo,
      pause:()=>{autoplay=false;schedule();},play:()=>{autoplay=true;schedule();},
      getState:()=>({index:current,id:slides[current].id,source_id:slides[current].source_id,autoplay,playing:canPlay(),reducedMotion:Boolean(motion?.matches)}),
      destroy:()=>{if(destroyed)return;destroyed=true;++serial;stopTimer();listeners.forEach(remove=>remove());visual.remove();ui.remove();hero.classList.remove("hero-has-carousel","hero-carousel-reduced");delete hero.dataset.heroSlide;delete hero.dataset.heroSourceId;if(oldCaption)oldCaption.hidden=oldHidden;if(oldPhoto){if(oldAria===null)oldPhoto.removeAttribute("aria-hidden");else oldPhoto.setAttribute("aria-hidden",oldAria);}instances.delete(hero);}
    });
  }
  function mountHeroCarousel(options={}) {
    const hero=options.hero||global.document.querySelector(".hero");
    if(!hero)return Promise.resolve(null);
    if(instances.has(hero))return instances.get(hero);
    const ready=build(hero,options).catch(()=>{instances.delete(hero);return null;});instances.set(hero,ready);return ready;
  }
  global.JejuHero=Object.freeze({mountHeroCarousel,validateConfig});
  if(global.document.readyState==="loading")global.document.addEventListener("DOMContentLoaded",()=>mountHeroCarousel(),{once:true});
  else global.setTimeout(()=>mountHeroCarousel(),0);
})(window);
