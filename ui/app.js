"use strict";

const $ = (selector, base = document) => base.querySelector(selector);
const $$ = (selector, base = document) => [...base.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const won = value => `${Math.round(Number(value) || 0).toLocaleString("ko-KR")}원`;
const clock = value => { const n=Number(value); return Number.isFinite(n)&&n>=0 ? `${String(Math.floor(n/60)).padStart(2,"0")}:${String(Math.floor(n%60)).padStart(2,"0")}` : "--:--"; };
const safeLink = value => { if(typeof value!=="string"||!value.trim())return ""; try { const url = new URL(value, location.origin); return ["http:", "https:"].includes(url.protocol) ? url.href : ""; } catch { return ""; } };
const safeImage = value => { const link = safeLink(value); return link && new URL(link).origin === location.origin ? link : ""; };
const regions = {all:"제주 전체", east:"동부", west:"서부", south:"남부", north:"북부"};
const categoryNames = {tourism:"자연과 풍경", attraction:"여행지", nature:"자연과 풍경", restaurant:"음식", cafe:"카페", experience:"체험과 문화", culture:"문화와 이야기", beach:"바다와 해변"};
let destinations = [], sourceRecords = [], region = "all", searchText = "", lastFocused = null, toastTimer, restaurantTimer, restaurantRequest = 0;
const SESSION_KEY="jeju-gilbeot-session-v3", MAX_SAVED=24;
let saved=new Set(), restoredExtras=[], audience="tourist", placeResults=[], lastRoute=null, lastTripRequest=null;
let destinationsLoading = false;
let placesRequest=0, parkingRequest=0, mobilityRequest=0, tripRequest=0, placesTimer;
let plannerOrigin=null;const autoExcludedIDs=new Set();
const replanRequests = new WeakMap();
const replanHistory = new WeakMap();
try { const text=sessionStorage.getItem(SESSION_KEY)||""; if(text.length<=65536){ const parsed=JSON.parse(text||"{}"); if(parsed&&typeof parsed==="object"&&!Array.isArray(parsed)){ saved=new Set((Array.isArray(parsed.ids)?parsed.ids:[]).filter(id=>typeof id==="string"&&id.length>0&&id.length<=120).slice(0,MAX_SAVED)); restoredExtras=(Array.isArray(parsed.extra_places)?parsed.extra_places:[]).slice(0,MAX_SAVED).filter(item=>item&&saved.has(item.id)).map(({id})=>({id})); } } } catch { /* Session storage is optional; no previous local storage is read. */ }

function notify(message) { const toast = $("#toast"); toast.textContent = message; toast.classList.add("visible"); clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove("visible"), 2600); }
function persist() {
  try {
    const extraIDs = new Set(restoredExtras.map(item=>item.id));
    for (const item of destinations) {
      if (item.featured === false) extraIDs.add(itemID(item));
    }
    const ids = [...saved].slice(0, MAX_SAVED);
    const extra_places = ids.filter(id=>extraIDs.has(id)).map(id=>({id}));
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ids, extra_places}));
  } catch {
    notify("이 탭의 저장 공간을 사용할 수 없어요. 목록은 체험 중에만 유지됩니다.");
  }
}
function itemID(item) { return String(item.id ?? item.poi_id ?? ""); }
function itemTags(item) { return Array.isArray(item.tags) ? item.tags : String(item.tags || "").split(/[|,]/).filter(Boolean); }
function itemRegion(item) { return regions[item.region] || item.region_label || item.region || "제주"; }
function resolveRegion(item) { if (Object.hasOwn(regions,item.region)) return item.region; const label = String(item.region_label || item.region || ""); if (/동부|성산|구좌|표선|우도/.test(label)) return "east"; if (/서부|애월|한림|한경|대정|안덕/.test(label)) return "west"; if (/남부|서귀포|중문|남원/.test(label)) return "south"; if (/북부|제주시|조천/.test(label)) return "north"; return "all"; }
function setRegion(value) { region=Object.hasOwn(regions,value)?value:"all"; $$(".region-chip").forEach(chip=>{const active=chip.dataset.region===region;chip.classList.toggle("active",active);chip.setAttribute("aria-pressed",String(active));}); $("#hero-region").value=region;$("#restaurant-region").value=region;$("#place-region").value=region;renderDestinations();loadRestaurants();if($("#place-query").value.trim().length>=2)loadPlaces();if($("#parking-details").open)loadParking(); }

function photoMarkup(item, className, extra="") { const src = safeImage(item.image); return src ? `<img class="${className}" src="${escapeHTML(src)}" alt="${escapeHTML(item.name)}" loading="lazy" ${extra}>` : `<div class="${className} image-fallback" role="img" aria-label="여행지 이미지 준비 중"></div>`; }
function favoriteMarkup(item) { const id = itemID(item), active = saved.has(id); return `<button class="favorite-button ${active?"saved":""}" data-save="${escapeHTML(id)}" aria-label="${escapeHTML(item.name)} ${active?"저장 취소":"저장"}" aria-pressed="${active}">${icon("heart")}</button>`; }
function normalizeTourismGuide(raw) {
  if(!raw||typeof raw!=="object"||Array.isArray(raw)||typeof raw.summary!=="string"||!raw.summary.trim()||typeof raw.source_url!=="string"||!/^https?:\/\//i.test(raw.source_url))return null;
  const url=safeLink(raw.source_url);if(!url)return null;
  try{if(/(^|\.)openstreetmap\.org$/i.test(new URL(url).hostname))return null;}catch{return null;}
  return {summary:raw.summary.trim().slice(0,1600),source_url:url,source_name:typeof raw.source_name==="string"?raw.source_name.slice(0,100):"관광 안내 출처",source_content_id:typeof raw.source_content_id==="string"?raw.source_content_id.slice(0,120):"",retrieved_at:typeof raw.retrieved_at==="string"?raw.retrieved_at.slice(0,40):"",summary_method:typeof raw.summary_method==="string"?raw.summary_method.slice(0,100):""};
}
function sourceActionLabel(item) {
  const url=safeLink(item.source_url);if(!url)return "출처 원문";
  const host=new URL(url).hostname;
  if(/(^|\.)openstreetmap\.org$/i.test(host))return "지도 원문";
  if(/(^|\.)jejudatahub\.net$/i.test(host))return "명부 원문";
  if(/(^|\.)visitjeju\.net$/i.test(host))return "관광 안내 원문";
  return "출처 원문";
}
function detailIntroductionMarkup(item) {
  const guide=normalizeTourismGuide(item.tourism_guide);
  const tourist=item.source_overlap_verified===true||item.kind==="attraction";
  if(guide)return `<section class="detail-tourism-guide" aria-label="관광 안내"><p class="guide-eyebrow">관광 안내</p><p class="detail-description">${escapeHTML(guide.summary)}</p><div class="guide-source"><span>${escapeHTML(guide.source_name)}</span><a class="guide-original" href="${escapeHTML(guide.source_url)}" target="_blank" rel="noopener noreferrer">관광 안내 원문 ↗</a></div></section>`;
  if(tourist)return '<section class="detail-guide-unavailable"><strong>관광 소개문을 아직 연결하지 못했어요.</strong><p>아래에서 확인된 분류·주소와 교차확인 출처를 살펴보세요.</p></section>';
  return `<p class="detail-description">${escapeHTML(item.description||"별도 소개문이 없습니다. 아래의 업소 기록과 출처를 확인해 주세요.")}</p>`;
}
function detailMapNoteMarkup(item) {
  if(!(item.source_overlap_verified===true||item.kind==="attraction")||!/^observed_osm_/.test(item.description_provenance||"")||!item.description)return "";
  const guide=normalizeTourismGuide(item.tourism_guide);if(guide&&guide.summary===item.description)return "";
  return `<details class="detail-map-note"><summary>지도에 기록된 메모</summary><p>${escapeHTML(String(item.description).slice(0,1600))}</p></details>`;
}
function sourceOverlapMarkup(item) {
  const proof=item.cross_source;if(item.source_overlap_verified!==true||!proof||typeof proof!=="object")return "";
  const hub=safeLink(proof.hub?.source_url),osm=safeLink(proof.osm?.source_url);
  const delta=typeof proof.distance_m==="number"&&Number.isFinite(proof.distance_m)&&proof.distance_m>=0?` · 두 자료의 좌표 차이 ${Math.round(proof.distance_m).toLocaleString("ko-KR")}m`:"";
  return `<details class="source-overlap"><summary>명부·지도 교차확인</summary><p>이름 정규화 일치${escapeHTML(delta)}. 현재 운영·실제 입구를 검증한 정보는 아닙니다.</p><div>${hub?`<a href="${escapeHTML(hub)}" target="_blank" rel="noopener noreferrer">빅데이터 명부 ↗</a>`:""}${osm?`<a href="${escapeHTML(osm)}" target="_blank" rel="noopener noreferrer">지도 원문 ↗</a>`:""}</div></details>`;
}
function cardMarkup(item, index) { return `<article class="destination-card" style="animation-delay:${Math.min(index*.04,.3)}s"><div class="card-image-wrap"><button class="card-open" data-detail="${escapeHTML(itemID(item))}" aria-label="${escapeHTML(item.name)} 상세 보기">${photoMarkup(item,"card-image")}<span class="card-region">${escapeHTML(itemRegion(item))} · JEJU</span></button>${favoriteMarkup(item)}</div><div class="card-copy"><p class="card-category">${escapeHTML(categoryNames[item.category] || item.category || "제주 여행지")}</p><button class="card-open" data-detail="${escapeHTML(itemID(item))}"><span class="card-title-row"><h3>${escapeHTML(item.name)}</h3>${icon("arrow")}</span></button><p class="card-description">${escapeHTML(normalizeTourismGuide(item.tourism_guide)?.summary || item.description || "관광 안내를 준비하고 있어요. 상세에서 확인된 장소 기록을 살펴보세요.")}</p>${item.source_overlap_verified===true?'<p class="overlap-badge">명부·지도 교차확인</p>':""}<div class="card-tags">${itemTags(item).slice(0,3).map(tag => `<span>${escapeHTML(tag)}</span>`).join("")}</div><button type="button" class="place-map-button" data-map-place="${escapeHTML(itemID(item))}">지도에서 보기 ↗</button></div></article>`; }
function handleImageFailures(base=document) { $$("img",base).forEach(img => { img.addEventListener("error",() => { img.removeAttribute("src"); img.classList.add("image-fallback"); img.alt = "여행지 이미지 준비 중"; },{once:true}); }); }
function renderDestinations() { const keyword = searchText.trim().toLocaleLowerCase("ko-KR"); const list = destinations.filter(item => item.featured!==false && (region === "all" || resolveRegion(item) === region) && (!keyword || [item.name,item.description,item.region_label,item.region,...itemTags(item)].join(" ").toLocaleLowerCase("ko-KR").includes(keyword))); $("#destination-grid").innerHTML = list.map(cardMarkup).join(""); $("#listing-count").textContent = `${regions[region]} · ${list.length}개의 여행지`; const message = $("#browse-message"); message.hidden = !!list.length; if (!list.length) message.textContent = destinations.length ? "아직 맞는 여행지가 없어요. 다른 지역이나 검색어를 골라보세요." : "여행지 데이터를 아직 불러오지 못했어요. 연결 상태와 데이터 출처를 확인해 주세요."; handleImageFailures($("#destination-grid")); }
function savedItemMarkup(item) { return `<div class="pocket-item">${photoMarkup(item,"pocket-thumb")}<div class="pocket-item-copy"><strong>${escapeHTML(item.name)}</strong><span>${escapeHTML(itemRegion(item))} · ${escapeHTML(itemTags(item).slice(0,2).join(" · "))}</span></div><button data-save="${escapeHTML(itemID(item))}" aria-label="${escapeHTML(item.name)} 저장 취소">×</button></div>`; }
function renderSaved() {
  const items = destinations.filter(item=>saved.has(itemID(item)));
  const unchecked = saved.size - items.length;
  const recovery = unchecked > 0 ? `
    <div class="empty-state">
      <p>저장한 ${unchecked}곳의 장소 정보를 확인해야 합니다.</p>
      ${destinationsLoading ? "<p>장소를 확인하고 있어요.</p>" : '<button type="button" class="place-map-button" data-retry-saved>다시 확인</button> <button type="button" class="place-map-button" data-drop-unchecked-saved>확인 대기 장소 빼기</button>'}
    </div>` : "";
  const list = items.map(savedItemMarkup).join("") + recovery;
  $("#saved-count").textContent = saved.size;
  $("#planner-saved").innerHTML = list;
  $("#pocket-empty").hidden = saved.size > 0;
  $("#saved-dialog-items").innerHTML = list || '<div class="empty-state">아직 모아둔 여행지가 없어요.<br>여행지를 둘러보고 하트를 눌러보세요.</div>';
  $("#saved-to-planner").disabled = !items.length;
  const hint = $("#collection-hint");
  hint.hidden = !items.length;
  if (items.length) {
    const selectedRegions = [...new Set(items.map(itemRegion))];
    hint.textContent = `관심 지역 ${selectedRegions.join(" · ")} / 확인한 장소 ${items.length}곳`;
  }
  $$("[data-save]").forEach(button => {
    if (!button.classList.contains("favorite-button")) return;
    const active = saved.has(button.dataset.save);
    button.classList.toggle("saved", active);
    button.setAttribute("aria-pressed", String(active));
    const item = destinations.find(place=>itemID(place)===button.dataset.save);
    if (item) button.setAttribute("aria-label", `${item.name} ${active?"저장 취소":"저장"}`);
  });
  const detailSave = $("#detail-save");
  if (detailSave) {
    const active = saved.has(detailSave.dataset.save);
    detailSave.innerHTML = `${icon(active?"check":"heart")} ${active?"여행에 담았어요":"내 여행에 담기"}`;
  }
  handleImageFailures($("#planner-saved"));
  handleImageFailures($("#saved-dialog-items"));
  window.dispatchEvent(new CustomEvent("jeju:saved", {detail:{count:saved.size,items}}));
}
function toggleSaved(id) { const item=destinations.find(d=>itemID(d)===id);if(!item)return;const removed=saved.has(id);if(removed)saved.delete(id);else{if(saved.size>=MAX_SAVED){notify("이 탭에는 최대 "+MAX_SAVED+"곳까지 담을 수 있어요.");return;}saved.add(id);}if($("#route-mode-auto")?.checked!==true||(lastRoute&&lastRoute.selection_mode!=="automatic")||Array.isArray(lastTripRequest?.destination_ids))clearPlannerResult();persist();renderSaved();renderPlaceResults();notify(removed?"모아둔 여행에서 꺼냈어요.":"마음에 드는 제주를 담았어요."); }
function openDialog(dialog) { lastFocused=document.activeElement; if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open",""); document.body.style.overflow="hidden"; }
function closeDialog(dialog) { if (typeof dialog.close === "function") dialog.close(); else dialog.removeAttribute("open"); document.body.style.overflow=""; lastFocused?.focus(); }
let detailRequest=0;
function showDetail(id){const item=destinations.find(p=>itemID(p)===id);if(item)showRichDetail(item);}
async function showRichDetail(raw, {allowTripAdd=true} = {}){
  const ticket=++detailRequest,dialog=$("#destination-dialog"),id=String(raw.plan_place_id||raw.id||"");
  $("#destination-detail").innerHTML=`<div class="detail-copy"><p class="eyebrow">PLACE DETAILS</p><h2>${escapeHTML(raw.name||"장소 정보")}</h2><p>원자료의 상세 정보를 불러오고 있어요…</p></div>`;
  if(!dialog.open)openDialog(dialog);
  let item=raw;
  try{const data=await getJSON(`/api/place-details?${new URLSearchParams({id})}`);item={...raw,...data.item,match_reason:raw.match_reason,evidence_terms:raw.evidence_terms,similarity_score:raw.similarity_score??raw.tfidf_similarity};}catch{item={...raw,detail_note:"상세 원문 연결을 확인하지 못했습니다. 아래는 현재 검색 결과의 기록입니다."};}
  if(ticket!==detailRequest||!dialog.open)return;
  const point=destinations.find(p=>itemID(p)===String(item.plan_place_id||item.id))||normalizeExtraPlace({...item,id:item.plan_place_id||item.id});
  const review = raw.visit_review?.required === true ? raw.visit_review : null;
  const canSave = allowTripAdd && !review && !!point;
  if (canSave && !destinations.some(p=>itemID(p)===point.id)) destinations.push(point);
  const source=safeLink(item.source_url),tags=item.observed_tags&&typeof item.observed_tags==="object"?item.observed_tags:{};
  const fields=[["주소",item.address],["원자료 분류",item.category],["기록 기준",item.individual_edit_timestamp||item.source_date],["자료 수집",item.snapshot_at],["원자료 영업시간 표기",tags.opening_hours],["원자료 전화",tags.phone||tags["contact:phone"]],["원자료 이용료 표기",tags.charge||tags.fee],["원자료 휠체어 표기",tags.wheelchair],["운영 주체 표기",tags.operator],["음식 분류 표기",item.cuisine||tags.cuisine]].filter(row=>row[1]);
  if(Number.isFinite(item.latitude)&&Number.isFinite(item.longitude))fields.splice(1,0,["기록 좌표",`${item.latitude.toFixed(5)}, ${item.longitude.toFixed(5)}`]);
  let website=tags.website||tags["contact:website"]||"";if(website&&!/^https?:\/\//i.test(website))website=/^[a-z0-9.-]+\.[a-z]{2,}(?:\/|$)/i.test(website)?`https://${website}`:"";website=safeLink(website);
  const why=Array.isArray(item.match_reason)?item.match_reason.join(" · "):item.match_reason||"",terms=Array.isArray(item.evidence_terms)?item.evidence_terms.slice(0,10).map(v=>typeof v==="string"?v:v?.term||"").filter(Boolean):[];
  const reviewURL = safeLink(review?.source_url);
  const reviewReasons = (Array.isArray(review?.reasons) ? review.reasons : [])
    .filter(reason=>typeof reason?.message==="string").slice(0,6);
  const reviewNote = review ? `<div class="detail-check-note"><strong>일정에 담기 전에 방문 조건 확인</strong>${reviewReasons.map(reason=>`<p>${escapeHTML(reason.message)}</p>`).join("")}${reviewURL?`<a href="${escapeHTML(reviewURL)}" target="_blank" rel="noopener noreferrer">방문 조건 출처 ↗</a>`:""}</div>` : "";
  const hasPhoto=!!safeImage(item.image);
  $("#destination-detail").innerHTML=`${hasPhoto?photoMarkup(item,"detail-image"):`<div class="detail-location-banner">${icon("pin")}<span>${normalizeTourismGuide(item.tourism_guide)?"제주 여행 안내":"제주 장소 기록"}</span><strong>${escapeHTML(item.category||"장소 기록")}</strong></div>`}<div class="detail-copy"><p class="detail-category">${escapeHTML(itemRegion(item))} / ${escapeHTML(item.category||"장소")}</p><h2>${escapeHTML(item.name)}</h2>${detailIntroductionMarkup(item)}${reviewNote}${detailMapNoteMarkup(item)}<dl class="detail-facts">${fields.map(([label,value])=>`<div><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd></div>`).join("")}</dl>${sourceOverlapMarkup(item)}${why||terms.length?`<div class="detail-model-reason"><strong>이번 검색에서 연결된 근거</strong><p>${escapeHTML(why)}</p>${terms.length?`<p>겹친 표현 · ${terms.map(escapeHTML).join(" · ")}</p>`:""}<small>텍스트 관련도이며 맛·인기·현재 영업 검증이 아닙니다.</small></div>`:""}<p class="detail-check-note">${escapeHTML(item.detail_note||"현재 영업·입구·요금·메뉴는 방문 전 원문과 운영기관에서 확인하세요.")}${item.requires_access_point?" 탐방로 입구·접근 조건을 별도로 확인해야 하는 장소입니다.":""}${item.requires_ferry?" 배편 확인이 필요한 섬 장소입니다.":""}</p><div class="detail-actions">${source&&source!==normalizeTourismGuide(item.tourism_guide)?.source_url?`<a class="place-map-button" href="${escapeHTML(source)}" target="_blank" rel="noopener noreferrer">${escapeHTML(sourceActionLabel(item))} ↗</a>`:""}${website?`<a class="place-map-button" href="${escapeHTML(website)}" target="_blank" rel="noopener noreferrer">기록된 웹사이트 ↗</a>`:""}${canSave?`<button type="button" class="button button-blue" id="detail-save" data-save="${escapeHTML(point.id)}">${saved.has(point.id)?"여행에 담았어요":"내 여행에 담기"}</button>`:(allowTripAdd&&!review?'<span>좌표 미확인 · 주소로 위치를 확인해 주세요.</span>':'<span>방문 조건을 별도로 확인할 장소입니다.</span>')}</div>${canSave?`<button type="button" class="place-map-button" data-map-place="${escapeHTML(point.id)}">이 장소 지도에서 보기 ↗</button>`:""}${item.data_license==="ODbL-1.0"||String(item.id).startsWith("osm_")?'<p class="detail-credit">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a> · ODbL</p>':item.image_credit?`<p class="detail-credit">사진 · ${escapeHTML(item.image_credit)}</p>`:""}</div>`;
  handleImageFailures($("#destination-detail"));
}

async function getJSON(path, options) {
  const controller = new AbortController();
  const timeout = setTimeout(()=>controller.abort(), 30000);
  try {
    const response = await fetch(path, {...options, signal:controller.signal,
      headers:{Accept:"application/json", ...options?.headers}});
    let result;
    try {
      result = await response.json();
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new Error("서버 응답을 읽지 못했어요. 로컬 실행 상태를 확인해 주세요.");
    }
    if (!response.ok) {
      const error = new Error(result?.error || result?.message || "요청을 처리하지 못했어요 ("+response.status+").");
      error.status = response.status;
      throw error;
    }
    return result;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("응답이 늦어지고 있어요. 잠시 후 다시 시도해 주세요.");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
function sourceMarkup(source) { const name=source.name||source.title||source.source_name||"데이터 출처"; const link=safeLink(source.url||source.source_url||source.homepage); return link?`<a href="${escapeHTML(link)}" target="_blank" rel="noopener noreferrer">${escapeHTML(name)} ↗</a>`:""; }
async function revalidateSavedExtras(items) {
  const checked = await Promise.all(items.slice(0, MAX_SAVED).map(async item=>{
    try {
      const query = new URLSearchParams({id:item.id});
      const {item:point} = await getJSON("/api/place-details?"+query);
      if (!point || (point.source_overlap_verified !== true && point.kind !== "food")) return null;
      const normalized = normalizeExtraPlace({...point, id:point.plan_place_id || point.id});
      return normalized ? {...normalized, restored_from_id:item.id} : null;
    } catch (error) {
      if (error.status === 404) return null;
      return {id:item.id, restored_from_id:item.id, needs_retry:true};
    }
  }));
  return checked.filter(Boolean);
}

async function loadDestinations() {
  if (destinationsLoading) return;
  destinationsLoading = true;
  renderSaved();
  try {
    const payload = await getJSON("/api/destinations");
    if (!Array.isArray(payload.items)) throw new Error("여행지 목록을 확인하지 못했어요.");
    const featured = payload.items
      .filter(item=>item?.source_overlap_verified === true && item.name && itemID(item))
      .map(item=>({...item, featured:true}));
    const featuredIDs = new Set(featured.map(itemID));
    destinations = [...featured, ...destinations.filter(item=>item.featured === false && !featuredIDs.has(itemID(item)))];

    const requested = restoredExtras.filter(item=>saved.has(item.id));
    const checked = await revalidateSavedExtras(requested);
    const byRequestedID = new Map(checked.map(item=>[item.restored_from_id, item]));
    const known = new Set(destinations.map(itemID));
    const requestedRefs = new Set(requested);
    const retry = [];
    for (const ref of restoredExtras) {
      if (!saved.has(ref.id) || known.has(ref.id)) continue;
      const point = byRequestedID.get(ref.id);
      if (!requestedRefs.has(ref) || point?.needs_retry) {
        retry.push(ref);
        continue;
      }
      if (!point) continue;
      if (point.id !== ref.id) {
        saved.delete(ref.id);
        saved.add(point.id);
      }
      if (!known.has(point.id)) {
        known.add(point.id);
        destinations.push(point);
      }
    }
    restoredExtras = retry;
    const pending = new Set(retry.map(item=>item.id));
    saved = new Set([...saved].filter(id=>known.has(id) || pending.has(id)));
    persist();
    renderDestinations();
    sourceRecords = Array.isArray(payload.sources) ? payload.sources : [];
    $("#source-destination-state").textContent = featured.length
      ? "교차확인 관광지 "+featured.length+"곳 · 이름·주소 검색 지원" : "여행지 데이터 연결 대기";
    if (!sourceRecords.length) {
      const unique = new Map(destinations.filter(item=>item.source_url)
        .map(item=>[item.source_url, {name:item.source_name, url:item.source_url}]));
      sourceRecords = [...unique.values()];
    }
    $("#source-links").innerHTML = sourceRecords.map(sourceMarkup).join("");
    const heroImage = new Image();
    heroImage.onload = ()=>{$("#hero-photo").style.backgroundImage = "url('/assets/hero-jeju.jpg')";};
    heroImage.onerror = ()=>{
      const alternative = destinations.find(item=>safeImage(item.image));
      if (alternative) {
        const image = safeImage(alternative.image).replace(/["\\]/g, "");
        $("#hero-photo").style.backgroundImage = "url("+JSON.stringify(image)+")";
        $("#hero-photo").setAttribute("aria-label", alternative.name+"의 제주 풍경");
      }
    };
    heroImage.src = "/assets/hero-jeju.jpg";
  } catch (error) {
    if (!destinations.length) {
      $("#destination-grid").innerHTML = "";
      $("#listing-count").textContent = "여행지 연결 대기";
      $("#browse-message").hidden = false;
      $("#browse-message").textContent = error.message || "여행지 정보를 불러오지 못했어요.";
    }
    $("#source-destination-state").textContent = "연결 상태 확인 필요";
  } finally {
    destinationsLoading = false;
    renderSaved();
  }
}

function dropUncheckedSaved() {
  const known = new Set(destinations.map(itemID));
  saved = new Set([...saved].filter(id=>known.has(id)));
  restoredExtras = [];
  clearPlannerResult();
  persist();
  renderSaved();
}

function statusDescription(value) { if(value===null||value===undefined)return""; if(typeof value==="string"||typeof value==="number")return String(value); if(Array.isArray(value))return value.map(statusDescription).filter(Boolean).join(" · "); if(typeof value==="object")return value.message||value.description||value.status||""; return ""; }
async function loadDataStatus() { try{ const status=await getJSON("/api/data-status"); const entries=[]; if(status.message)entries.push(status.message); const records=Array.isArray(status.sources)?status.sources:Array.isArray(status.items)?status.items:[]; records.forEach(item=>{const title=item.name||item.title||item.source_name;const state=item.message||item.access_status||item.status;const count=item.downloaded_count??item.row_count??item.rows;entries.push(`${title||"데이터"} · ${statusDescription(state)||"상태 확인 중"}${typeof count==="number"?` / 확보 ${count.toLocaleString("ko-KR")}행`:""}`);}); if(!entries.length){for(const key of ["data_mode","access_status","downloaded_at","updated_at"]){if(status[key])entries.push(`${({data_mode:"추천 데이터",access_status:"접근 상태",downloaded_at:"확보 기준",updated_at:"갱신 기준"})[key]} · ${statusDescription(status[key])}`);}}const report=status.real_model_report;if(report&&typeof report==="object"){const countText=Number.isFinite(Number(report.months))?`${Number(report.months)}개월` : "과거 관측 기간";const categoryText=Number.isFinite(Number(report.categories))?`${Number(report.categories)}업종`:"업종별";const start=String(report.observation_start||"").replace("-","."),end=String(report.observation_end||"").replace("-",".");const summary=document.createElement("p");summary.className="real-ml-summary";summary.textContent=`실데이터 소비 ML · ${countText} · ${categoryText} · ${start}~${end} · 현재 인기도를 뜻하지 않음`;$(".source-content").insertBefore(summary,$(".source-details"));if(report.scope_label)entries.push(report.scope_label);if(report.note)entries.push(report.note);} $("#data-status-details").innerHTML=entries.map(line=>`<p>${escapeHTML(line)}</p>`).join(""); }catch{$("#data-status-details").textContent="상세 데이터 연결 상태를 확인하지 못했습니다.";} }
async function loadModelStatus() { try { await getJSON("/api/status"); $("#source-model-state").textContent="검증된 소비 구성비 · 공식 관광지 소개 검색"; } catch { $("#source-model-state").textContent="추천 엔진 연결 확인 필요"; } }

function renderRoute(result, replanRequest = null, previousRoute = null) {
  if(!result||result.data_mode!=="reference"){lastRoute=null;notify("실제 장소 자료로 확인된 일정만 표시할 수 있어요.");return;}
  lastRoute=result;const container=$("#trip-result");container.hidden=false;
  if (replanRequest) replanRequests.set(result, replanRequest);
  if (previousRoute) {
    replanHistory.delete(previousRoute);
    replanHistory.set(result, previousRoute);
  }
  const statusLabel=value=>({completed:"완료",excluded:"제외",unsupported:"지원 범위 밖",unavailable:"정보 부족",failed:"확인 실패",skipped:"생략",ok:"완료",needs_review:"방문 조건 확인 필요",needs_clarification:"검색 조건 확인 필요"}[value]||"확인 필요");
  const automatic=result.selection_mode==="automatic",title=result.status==="ok"?(replanRequest?"남은 여행 코스":automatic?"확인한 자료로 구성한 추천 코스":"마음에 담은 장소로 그린 하루"):result.status==="unsupported"?"아직 연결이 필요한 여행이에요":result.status==="needs_review"?"방문 조건을 먼저 확인해 주세요":result.status==="needs_clarification"?"검색 조건을 확인해 주세요":"조건을 조금 바꿔볼까요?";
  const publicLink=value=>{if(typeof value!=="string"||!/^https?:\/\//i.test(value))return "";try{const url=new URL(value);return ["http:","https:"].includes(url.protocol)?url.href:"";}catch{return "";}};
  const evidence=Array.isArray(result.selected_place_evidence)?result.selected_place_evidence:[];
  const evidenceFor=stop=>evidence.find(item=>String(item.id)===String(stop.poi_id||stop.id))||stop.trust||{};
  const displayedStops=Array.isArray(result.stops)?result.stops:[];
  const warningsFor=stop=>(Array.isArray(evidenceFor(stop).warnings)?evidenceFor(stop).warnings:[]).filter(w=>typeof w==="string");
  const sharedWarnings=displayedStops.length>1?[...new Set(warningsFor(displayedStops[0]))].filter(w=>displayedStops.every(stop=>warningsFor(stop).includes(w))):[];
  const sharedWarningHTML=sharedWarnings.length?`<div class="route-shared-warning"><strong>모든 방문 장소에 공통으로 확인할 내용</strong>${sharedWarnings.map(w=>`<p>${escapeHTML(w)}</p>`).join("")}</div>`:"";
  const trustMarkup=stop=>{
    const proof=evidenceFor(stop);if(!automatic&&!Object.keys(proof).length)return "";const sources=Array.isArray(proof.sources)?proof.sources:[];
    const sourceLinks=sources.map(source=>{const link=publicLink(source.url||source.source_url);return link?`<a href="${escapeHTML(link)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.label||source.name||source.source_name||source.provider||"근거 원문")} ↗</a>${source.checked_at?` (${escapeHTML(source.checked_at)})`:""}`:"";}).filter(Boolean).join(" · ");
    const dates=[...new Set(sources.map(source=>source.checked_at||source.retrieved_at||source.verified_at||source.as_of).filter(value=>typeof value==="string"))];
    return `<div class="route-trust"><p>현재 영업과 실제 입구 별도 확인</p>${(Array.isArray(proof.warnings)?proof.warnings:[]).filter(w=>typeof w==="string"&&!sharedWarnings.includes(w)).slice(0,12).map(w=>`<p class="route-place-warning">${escapeHTML(w)}</p>`).join("")}<details class="route-proof"><summary>선정 근거와 출처 ${sources.length}개 보기</summary>${proof.selection_reason?`<p>선택 이유 · ${escapeHTML(proof.selection_reason)}</p>`:""}${sourceLinks?`<p>${sourceLinks}</p>`:""}${dates.length?`<p>자료 기준·소개 확인일 · ${escapeHTML(dates.join(" / "))}</p>`:""}</details>${automatic?`<button type="button" class="place-map-button" data-exclude-route="${escapeHTML(stop.poi_id||stop.id)}">이 장소 빼고 다시 추천</button>`:""}</div>`;
  };
  let body="";
  if(result.status==="ok"&&Array.isArray(result.stops)&&result.stops.length){
    const totals=result.totals||{};
    body=`<div class="result-summary"><span>방문 <strong>${result.stops.length}곳</strong></span><span>이동비 추정 <strong>${won(totals.travel_cost_krw)}</strong></span><span>소요 시간 <strong>${Math.floor((totals.duration_minutes||0)/60)}시간 ${(totals.duration_minutes||0)%60}분</strong></span><span>복귀 <strong>${clock(totals.end_arrival_minute)}</strong></span></div><p class="result-cost-note">입장료·식사비·렌터카·주차비는 포함되지 않습니다. 체류시간은 계획용 가정입니다. ${travelBasisText(result)} 실제 교통과 통행 조건을 출발 전에 확인해 주세요.</p>${sharedWarningHTML}<ol class="route-list">${result.stops.map((stop,index)=>`<li><span class="route-index">${index+1}</span><p class="route-time">${clock(stop.arrival_minute)} — ${clock(stop.departure_minute)} · ${stop.stay_minutes}분 머무르기</p><h4 class="route-name">${escapeHTML(stop.name)}</h4><div class="route-facts"><span>입장 비용 별도 확인</span><span>이동 약 ${stop.travel_minutes}분${Number.isFinite(stop.travel_km)?` · ${stop.travel_km.toFixed(2)}km`:""}</span></div>${trustMarkup(stop)}</li>`).join("")}</ol>`;
  }else body=`<p class="result-unavailable">${escapeHTML(result.message||"입력한 조건에서 경로를 만들지 못했어요.")}</p>`;
  const suggestions=Array.isArray(result.suggestions)?result.suggestions.filter(value=>typeof value==="string"&&value.trim()).slice(0,8):[];
  if(result.status!=="ok"&&suggestions.length)body+=`<section class="route-suggestions" aria-label="조건 조정 안내"><h4>이렇게 바꿔 보세요</h4><ul>${suggestions.map(value=>`<li>${escapeHTML(value.slice(0,1000))}</li>`).join("")}</ul></section>`;
  const warnings=Array.isArray(result.warnings)?result.warnings:[],trace=Array.isArray(result.trace)?result.trace:[],excluded=Array.isArray(result.exclusions)?result.exclusions:[],assumptions=Array.isArray(result.planning_assumptions)?result.planning_assumptions:[];
  const exclusionText=excluded.slice(0,68).map(item=>{const sources=Array.isArray(item.trust?.sources)?item.trust.sources:[],links=sources.map(source=>{const link=publicLink(source.url||source.source_url),checked=typeof source.checked_at==="string"&&source.checked_at?` (${source.date_kind==="guide_review"?"공식 소개 확인일":"자료 기준·확인일"} ${escapeHTML(source.checked_at)})`:"";return link?`<a href="${escapeHTML(link)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.label||source.name||source.source_name||"근거 원문")} ↗</a>${checked}`:"";}).filter(Boolean).join(" · ");return `<li>${escapeHTML(item.name||"장소 후보")} · ${escapeHTML((Array.isArray(item.reasons)?item.reasons:[item.reason||item.status||"추천 조건 미충족"]).map(reason=>typeof reason==="string"?reason:reason?.message||reason?.code||"추천 조건 미충족").join(" / "))}${(Array.isArray(item.trust?.warnings)?item.trust.warnings:[]).filter(w=>typeof w==="string").slice(0,12).map(w=>`<p>${escapeHTML(w)}</p>`).join("")}${links?`<p>${links}</p>`:""}</li>`;}).join("");
  const needsPlaceReview = result.status === "needs_review" && !automatic && !!exclusionText;
  if (needsPlaceReview) body += '<section class="route-suggestions" aria-label="일정이 멈춘 이유"><h4>일정이 멈춘 이유</h4><ul>'+exclusionText+'</ul></section>';
  container.innerHTML=`<div class="result-top"><div><p class="eyebrow">YOUR JEJU ITINERARY</p><h3>${title}</h3><p>${automatic?"출처를 확인한 실제 장소에서 시간과 이동비에 맞는 방문 순서를 골랐어요.":result.status==="ok"?"저장한 실제 여행지에서 시간과 추정 이동비 조건에 맞는 순서를 구성했어요.":"저장한 장소의 방문 조건과 시간·추정 이동비 조건을 확인한 결과입니다."} 관광객 인기도를 학습한 결과는 아닙니다.</p></div><span class="reference-label">${automatic?"실제 자료 · 조건 기반 자동 선택":"저장한 실제 장소 · 경로 구성"}</span></div>${body}<details class="result-detail"><summary>이 추천의 근거와 확인할 내용</summary><ul>${warnings.map(warning=>`<li>${escapeHTML(warning)}</li>`).join("")}</ul>${assumptions.length?`<ul>${assumptions.map(a=>`<li>${escapeHTML(typeof a==="string"?a:a.basis||a.item||"계획용 가정")}</li>`).join("")}</ul>`:""}<ol class="agent-trace-list">${trace.map(step=>`<li><strong>${escapeHTML(step.agent||step.stage||"처리 단계")}</strong> · ${escapeHTML(statusLabel(step.status||"completed"))}<p>${escapeHTML(step.detail||"")}</p></li>`).join("")}</ol>${exclusionText&&!needsPlaceReview?`<details><summary>추천에서 제외한 후보와 이유 ${excluded.length}곳</summary><ul>${exclusionText}</ul></details>`:""}</details>`;
  if(result.status==="ok"&&result.stops?.length)container.insertAdjacentHTML("beforeend",`<div class="result-export"><button type="button" class="place-map-button" data-show-route>지도에서 경로 보기 ↗</button><button type="button" class="button itinerary-download" data-download-trip>일정 파일 저장 ${icon("arrow")}</button>${automatic&&!replanRequest?'<button type="button" class="place-map-button" data-reset-auto-exclusions>제외 목록을 비우고 새로 추천</button>':""}<p>사진과 출발지 좌표 없이 일정·출처·확인할 내용을 HTML 파일로 저장합니다.</p></div>`);
  if (previousRoute) {
    $(".result-cost-note", container).insertAdjacentHTML("afterend", '<button type="button" class="place-map-button route-undo" data-undo-replan>이전 코스로 되돌리기</button>');
  }
  if (automatic && result.status === "ok" && window.JejuTripReplan) {
    const panel = window.JejuTripReplan.createPanel(result, {
      nowKST: `${todayKST()}T${new Intl.DateTimeFormat("en-GB", {
        timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23"
      }).format(new Date())}`,
      submit: (request, controls) => submitTripReplan(result, request, controls),
    });
    if (panel) $(".result-cost-note", container).after(panel);
    if (replanRequest) {
      const caption = document.createElement("p");
      caption.className = "trip-replan-caption";
      caption.textContent = `${result.request.origin_label} ${clock(result.request.start_minute)} 출발 · 기존 도착지 ${clock(result.request.end_minute)}까지`;
      $(".result-summary", container).before(caption);
    }
  }
  window.dispatchEvent(new CustomEvent("jeju:route",{detail:result}));window.JejuPages?.reveal(container);container.scrollIntoView({behavior:"smooth",block:"start"});
}
function travelBasisText(result) {
  return result.travel_estimate?.basis === "osm_road_distance"
    ? "이동시간과 비용은 OSM 도로 거리와 가정 속도로 추정했습니다."
    : "이동시간과 비용은 좌표 거리와 가정 속도로 추정했습니다.";
}

function showReturnEstimate(form, result) {
  if (!form) return;
  const section = document.createElement("section");
  section.className = "trip-replan-return-result";
  const heading = document.createElement("h4");
  heading.textContent = "기존 도착지로 바로 가는 경우";
  const detail = document.createElement("p");
  const {request, totals} = result;
  detail.textContent = `${request.origin_label} ${clock(request.start_minute)} 출발 · 예상 도착 ${clock(totals.end_arrival_minute)} · 이동 약 ${totals.travel_minutes}분 · 추정 이동비 ${won(totals.travel_cost_krw)}`;
  const basis = document.createElement("p");
  basis.textContent = `${travelBasisText(result)} 마감까지 ${totals.deadline_margin_minutes}분 여유가 있어요.`;
  section.append(heading, detail, basis);
  if (result.route_geometry?.coordinates?.length > 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "place-map-button";
    button.textContent = "복귀 경로 지도에서 보기";
    button.addEventListener("click", () => {
      if (!window.JejuExplore?.showReturnRoute(result.route_geometry)) notify("지금은 지도에서 복귀 경로를 열 수 없어요.");
    });
    section.append(button);
  }
  form.append(section);
}

async function submitTripReplan(base, request, { panel, form, status } = {}) {
  if (lastRoute !== base) return;
  const mainButton = $("#create-trip");
  if (mainButton.disabled) return;
  const ticket = ++tripRequest;
  const controls = form ? [...form.elements].filter(control => !control.disabled) : [];
  mainButton.disabled = true;
  for (const control of controls) control.disabled = true;
  if (panel) panel.open = true;
  form?.querySelector(".trip-replan-return-result")?.remove();
  if (status) status.textContent = "남은 일정과 돌아오는 시간을 계산하고 있어요…";
  try {
    const result = await getJSON("/api/agent/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    if (ticket !== tripRequest) return;
    if (request.return_only && result?.status === "ok" && result.selection_mode === "direct_return") {
      if (status) status.textContent = "복귀만 할 때의 예상 시간과 비용을 표시했어요.";
      showReturnEstimate(form, result);
      return;
    }
    if (result?.status !== "ok" || result.data_mode !== "reference" || !result.stops?.length) {
      const reason = result?.message || "남은 시간과 이동비에서 방문할 장소를 찾지 못했어요.";
      const next = result?.suggestions?.find(item => typeof item === "string" && item.trim());
      throw new Error(next ? `${reason} ${next}` : reason);
    }
    lastTripRequest = request;
    renderRoute(result, request, base);
    const heading = $("#trip-result .result-top h3");
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  } catch (error) {
    if (ticket !== tripRequest) return;
    const message = `${error.message || "남은 코스를 만들지 못했어요."} 기존 일정은 화면에 남아 있어요.`;
    if (status) status.textContent = message;
    else notify(message);
  } finally {
    if (ticket === tripRequest) {
      mainButton.disabled = false;
      for (const control of controls) control.disabled = false;
    }
  }
}

function undoReplan() {
  if ($("#create-trip").disabled) return;
  const previous = replanHistory.get(lastRoute);
  if (!previous) return;
  replanHistory.delete(lastRoute);
  const request = replanRequests.get(previous) || null;
  lastTripRequest = request || previous.request;
  renderRoute(previous, request);
  const heading = $("#trip-result .result-top h3");
  heading.tabIndex = -1;
  heading.focus({preventScroll:true});
}

function excludeRoutePlace(id) {
  if ($("#create-trip").disabled) return;
  const previous = replanRequests.get(lastRoute);
  if (previous) {
    const excluded = [...new Set([...previous.excluded_ids, id])];
    const panel = $("#trip-result .trip-replan");
    submitTripReplan(lastRoute, { ...previous, excluded_ids: excluded }, {
      panel, form: panel?.querySelector("form"), status: panel?.querySelector(".trip-replan-status"),
    });
    return;
  }
  autoExcludedIDs.add(id);
  $("#route-mode-auto").checked = true;
  $("#route-mode-saved").checked = false;
  updatePlanningMode();
  $("#planner-form").requestSubmit();
}

function updatePlanningMode() {
  const automatic=$("#route-mode-auto")?.checked===true;
  $("#create-trip span").textContent=automatic?"조건에 맞는 코스 추천":"저장한 장소로 여행 만들기";
  $("#auto-route-options").hidden=!automatic;
  const limit = $("[name=max_stops]");
  const allSaved = $("#max-stops-all");
  allSaved.hidden = allSaved.disabled = automatic;
  if (automatic && limit.value === "all") limit.value = "4";
  $("#planning-mode-note").innerHTML=automatic?"출처와 접근 조건을 확인한 관광 후보를 자동 선택합니다.<br>현재 영업과 실제 이동·체류시간은 방문 전 별도 확인해 주세요.":"시간과 이동비는 추정값입니다.<br>실시간 길찾기와 영업 여부는 방문 전 별도로 확인해 주세요.";
}
function formRequest() {
  const form=new FormData($("#planner-form")),origin=plannerOriginRequest(),minutes=value=>{const[hour,minute]=String(value).split(":").map(Number);return hour*60+minute;};
  const back=$("#planner-return-to-origin").checked,destination={latitude:back?origin.start_lat:Number(form.get("end_lat")),longitude:back?origin.start_lon:Number(form.get("end_lon"))};
  if(!plannerValidPoint(destination))throw new Error("도착지도 제주 권역의 유효한 좌표로 확인해 주세요.");
  const limit = form.get("max_stops");
  return {date:form.get("date"),transport:form.get("transport"),...origin,end_lat:destination.latitude,end_lon:destination.longitude,start_minute:minutes(form.get("start_time")),end_minute:minutes(form.get("end_time")),budget_krw:Number(form.get("budget_krw")),max_stops:limit==="all"?"all":Number(limit)};
}

function addSavedDestinations(request) {
  const ids = destinations.filter(item=>saved.has(itemID(item))).map(itemID);
  if (ids.length < saved.size) {
    throw new Error("확인 대기 중인 장소가 있어요. 담기 목록에서 다시 확인하거나 해당 장소를 빼 주세요.");
  }
  if (!ids.length) throw new Error("먼저 여행지에 하트를 눌러 마음에 드는 곳을 담아주세요.");
  if (request.max_stops !== "all" && ids.length > request.max_stops) {
    throw new Error("담아둔 장소가 "+ids.length+"곳이에요. ‘담아둔 장소 모두’를 선택하거나 목록에서 장소를 빼 주세요.");
  }
  request.destination_ids = ids;
}

// V15 planner origin is tab memory only. Applying a shared point is explicit.
function plannerValidPoint(point){return point&&typeof point.latitude==="number"&&typeof point.longitude==="number"&&Number.isFinite(point.latitude)&&Number.isFinite(point.longitude)&&point.latitude>=32.9&&point.latitude<=33.8&&point.longitude>=126&&point.longitude<=127.05;}
function clearPlannerResult(){++tripRequest;lastRoute=null;lastTripRequest=null;$("#trip-result").hidden=true;$("#trip-result").innerHTML="";$("#planner-error").hidden=true;$("#create-trip").disabled=false;updatePlanningMode();window.dispatchEvent(new CustomEvent("jeju:route",{detail:null}));}
function invalidatePlannerOrigin(message="출발지가 바뀌었어요. 다시 확인해 주세요."){
  plannerOrigin=null;autoExcludedIDs.clear();clearPlannerResult();$("#planner-origin-status").textContent=message;
  for(const name of ["start_lat","start_lon"]){const field=$(`[name=${name}]`);if(field.disabled){field.disabled=false;field.value=name==="start_lat"?"33.506":"126.492";}}
  window.dispatchEvent(new CustomEvent("jeju:planneroriginchange",{detail:null}));
}
function updatePlannerReturn(){const back=$("#planner-return-to-origin").checked;for(const name of ["end_lat","end_lon"])$("[name="+name+"]").disabled=back;}
function setPlannerOrigin(point,source,label,contextLinked=false){
  if(!plannerValidPoint(point))throw new Error("제주 권역의 유효한 출발지를 확인해 주세요.");
  clearPlannerResult();autoExcludedIDs.clear();plannerOrigin={latitude:point.latitude,longitude:point.longitude,source,label:String(label||"직접 고른 출발지").slice(0,100),contextLinked,...(typeof point.accuracy_m==="number"&&Number.isFinite(point.accuracy_m)&&point.accuracy_m>=0?{accuracy_m:point.accuracy_m}:{})};
  for(const [name,value] of [["start_lat",point.latitude],["start_lon",point.longitude]]){const field=$(`[name=${name}]`);field.disabled=source==="device";field.value=source==="device"?"":String(value);}
  $("#planner-origin-status").textContent=source==="device"?`기기 추정 위치를 출발지로 확인했습니다. ${Number.isFinite(plannerOrigin.accuracy_m)?"기기 추정 오차 약 "+Math.round(plannerOrigin.accuracy_m).toLocaleString("ko-KR")+" m":"기기 추정 오차 정보 미제공"} · 위치 수신 시각 미제공. ${plannerOrigin.accuracy_m>=5000?"오차가 5km 이상이므로 실제 출발지를 다시 확인하거나 기준 장소를 직접 선택해 주세요. ":""}정밀 좌표는 화면과 저장 파일에 표시하지 않습니다.`:`${plannerOrigin.label} 출발을 확인했습니다. 기기 위치로 간주하지 않습니다.`;
  updatePlannerReturn();window.dispatchEvent(new CustomEvent("jeju:planneroriginchange",{detail:null}));return true;
}
function plannerOriginRequest(){
  if(!plannerOrigin)throw new Error("실제 여행 출발지를 먼저 확인해 주세요.");
  if(plannerOrigin.contextLinked){const current=window.JejuLocationContext?.get();if(!plannerValidPoint(current)||current.latitude!==plannerOrigin.latitude||current.longitude!==plannerOrigin.longitude||(current.source==="device")!==(plannerOrigin.source==="device")){invalidatePlannerOrigin("탐색 위치가 해제되거나 바뀌었어요. 출발지를 다시 확인해 주세요.");throw new Error("출발지를 다시 확인해 주세요.");}}
  return {start_lat:plannerOrigin.latitude,start_lon:plannerOrigin.longitude,origin_confirmed:true,origin_source:plannerOrigin.source,origin_label:plannerOrigin.label,...(Number.isFinite(plannerOrigin.accuracy_m)?{origin_accuracy_m:plannerOrigin.accuracy_m}:{})};
}
function initPlannerOrigin(){
  $("#planner-apply-context").addEventListener("click",()=>{try{const current=window.JejuLocationContext?.get();if(!plannerValidPoint(current))throw new Error("먼저 지도/먹거리에서 기준 장소를 고르거나 위치 안내에 동의해 위치를 받아주세요.");setPlannerOrigin(current,current.source==="device"?"device":"landmark",current.source==="device"?"동의한 기기 추정 위치":current.label||"탐색에서 고른 기준 장소",true);}catch(error){$("#planner-origin-status").textContent=error.message;}});
  $("#planner-example-fill")?.addEventListener("click",()=>{
    $("#route-mode-auto").checked=true;
    $("#route-mode-saved").checked=false;
    $("#auto-route-query").value="";
    $("#auto-route-region").value="north";
    const example={date:todayKST(),transport:"car",start_time:"09:00",end_time:"18:00",budget_krw:"100000",max_stops:"3"};
    for(const [name,value] of Object.entries(example))$("[name="+name+"]").value=value;
    $("#planner-return-to-origin").checked=true;
    updatePlannerReturn();
    invalidatePlannerOrigin("예시 조건을 채웠어요. 제주공항 출발로 확인한 뒤 일정을 만들어 주세요.");
    $("#planner-confirm-airport").focus();
  });
  $("#planner-confirm-airport").addEventListener("click",()=>setPlannerOrigin({latitude:33.506,longitude:126.492},"landmark","제주공항 부근"));
  $("#planner-confirm-coordinates").addEventListener("click",()=>{try{const latitude=Number($("[name=start_lat]").value),longitude=Number($("[name=start_lon]").value);setPlannerOrigin({latitude,longitude},"manual","직접 입력한 출발지");}catch(error){$("#planner-origin-status").textContent=error.message;}});
  for(const name of ["start_lat","start_lon"]){$("[name="+name+"]").addEventListener("input",()=>invalidatePlannerOrigin());}
  for(const name of ["end_lat","end_lon"]){$("[name="+name+"]").addEventListener("input",clearPlannerResult);}
  $("#planner-return-to-origin").addEventListener("change",()=>{updatePlannerReturn();clearPlannerResult();});
  for(const id of ["#route-mode-saved","#route-mode-auto"]){$(id).addEventListener("change",()=>{updatePlanningMode();clearPlannerResult();});}
  for(const id of ["#auto-route-query","#auto-route-region"]){for(const event of ["input","change"])$(id).addEventListener(event,()=>{autoExcludedIDs.clear();clearPlannerResult();});}
  for(const name of ["date","transport","start_time","end_time","budget_krw","max_stops"]){for(const event of ["input","change"])$("[name="+name+"]").addEventListener(event,clearPlannerResult);}
  window.addEventListener("jeju:locationchange",()=>{if(plannerOrigin?.contextLinked){const current=window.JejuLocationContext?.get();if(!current||current.latitude!==plannerOrigin.latitude||current.longitude!==plannerOrigin.longitude||(current.source==="device")!==(plannerOrigin.source==="device"))invalidatePlannerOrigin("탐색 위치가 해제되거나 바뀌었어요. 출발지를 다시 확인해 주세요.");}});
  window.addEventListener("pagehide",()=>invalidatePlannerOrigin("출발지 정보가 초기화되었습니다."));
  window.addEventListener("jeju:reset",()=>{invalidatePlannerOrigin("새 여행의 출발지를 확인해 주세요.");updatePlannerReturn();});
  updatePlannerReturn();
}
// End V15 planner origin.

document.addEventListener("click", event=>{
  if (event.target.closest("[data-retry-saved]")) loadDestinations();
  if (event.target.closest("[data-drop-unchecked-saved]")) dropUncheckedSaved();
});
document.addEventListener("click",event=>{if(event.target.closest("[data-undo-replan]")){undoReplan();return;}const excluded=event.target.closest("[data-exclude-route]");if(excluded){excludeRoutePlace(String(excluded.dataset.excludeRoute));return;}if(event.target.closest("[data-reset-auto-exclusions]")){autoExcludedIDs.clear();$("#planner-form").requestSubmit();return;}if(event.target.closest("[data-show-route]")){window.JejuExplore?.showRoute();return;}const mapButton=event.target.closest("[data-map-place]");if(mapButton){const item=destinations.find(d=>itemID(d)===mapButton.dataset.mapPlace)||placeResults.find(d=>itemID(d)===mapButton.dataset.mapPlace);if(item){if($("#destination-dialog").open)closeDialog($("#destination-dialog"));window.JejuExplore?.showPlaces([item],{focus:true,label:`${item.name} 위치`});}return;}const exportButton=event.target.closest("[data-download-trip]");if(exportButton){saveItinerary();return;}const addPlace=event.target.closest("[data-place-add]");if(addPlace){const item=placeResults.find(p=>itemID(p)===addPlace.dataset.placeAdd);if(item){const normalized=normalizeExtraPlace(item);if(!normalized){notify("이 장소는 위치 정보를 확인할 수 없어 담지 못했어요.");return;}if(!destinations.some(p=>itemID(p)===normalized.id))destinations.push(normalized);toggleSaved(normalized.id);}return;}const mode=event.target.closest("[data-audience]");if(mode){audience=mode.dataset.audience==="resident"?"resident":"tourist";renderAudience();loadRestaurants();return;}const saveButton=event.target.closest("[data-save]");if(saveButton){event.preventDefault();toggleSaved(saveButton.dataset.save);return;}const detailButton=event.target.closest("[data-detail]");if(detailButton){showDetail(detailButton.dataset.detail);return;}const chip=event.target.closest("[data-region]");if(chip)setRegion(chip.dataset.region);});
$("#destination-search").addEventListener("input",event=>{searchText=event.target.value;$("#hero-keyword").value=searchText;renderDestinations();});
$("#restaurant-search").addEventListener("input",()=>{clearTimeout(restaurantTimer);restaurantTimer=setTimeout(loadRestaurants,250);});
$("#restaurant-region").addEventListener("change",event=>setRegion(event.target.value));
$("#hero-search").addEventListener("submit",event=>{event.preventDefault();searchText=$("#hero-keyword").value;$("#destination-search").value=searchText;setRegion($("#hero-region").value);window.JejuExplore?.searchTourismFromQuery(searchText,region);});
$("#mobile-menu").addEventListener("click",()=>{const open=$(".main-nav").classList.toggle("open");$("#mobile-menu").setAttribute("aria-expanded",String(open));$("#mobile-menu").setAttribute("aria-label",open?"메뉴 닫기":"메뉴 열기");});
$$(".main-nav a").forEach(link=>link.addEventListener("click",()=>{$(".main-nav").classList.remove("open");$("#mobile-menu").setAttribute("aria-expanded","false");}));
$("#open-saved").addEventListener("click",()=>{renderSaved();openDialog($("#saved-dialog"));});
$("#close-saved").addEventListener("click",()=>closeDialog($("#saved-dialog")));
$("#close-destination").addEventListener("click",()=>closeDialog($("#destination-dialog")));
$$("dialog").forEach(dialog=>{dialog.addEventListener("click",event=>{if(event.target===dialog){const bounds=dialog.getBoundingClientRect();if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)closeDialog(dialog);}});dialog.addEventListener("close",()=>{document.body.style.overflow="";});});
function beginGuidedPlan(mode) {
  if (mode !== "automatic" && mode !== "saved") return false;
  if ($("#create-trip").disabled) {
    notify("일정을 계산하고 있어요. 결과를 확인한 뒤 방식을 바꿔 주세요.");
    return false;
  }
  const automatic = mode === "automatic";
  if ($("#route-mode-auto").checked !== automatic) {
    $("#route-mode-auto").checked = automatic;
    $("#route-mode-saved").checked = !automatic;
    clearPlannerResult();
  } else {
    updatePlanningMode();
  }
  showPlannerInputs(
    !automatic && saved.size === 0 ? "먼저 관광지나 관련 음식점에서 마음에 드는 곳을 여행에 담아 주세요." : "",
    automatic ? "#auto-route-region" : "#route-mode-saved"
  );
  return true;
}
function showPlannerInputs(message, focusTarget) {
  const form = $("#planner-form");
  window.JejuPages?.reveal(form);
  if (message) {
    const error = $("#planner-error");
    error.textContent = message;
    error.hidden = false;
  }
  form.scrollIntoView({behavior:"smooth", block:"start"});
  $(focusTarget || (plannerOrigin ? "#create-trip" : "#planner-confirm-airport")).focus({preventScroll:true});
}
$("#saved-to-planner").addEventListener("click", () => {
  closeDialog($("#saved-dialog"));
  const limit = $("[name=max_stops]");
  if ($("#route-mode-auto").checked || limit.value !== "all") {
    $("#route-mode-auto").checked = false;
    $("#route-mode-saved").checked = true;
    limit.value = "all";
    clearPlannerResult();
  }
  showPlannerInputs();
});
$("#planner-form").addEventListener("submit",async event=>{
 event.preventDefault();const ticket=++tripRequest,button=$("#create-trip"),error=$("#planner-error");error.hidden=true;button.disabled=true;button.querySelector("span").textContent="당신의 하루를 그리고 있어요…";
 try{const request=formRequest(),automatic=$("#route-mode-auto")?.checked===true;if(request.start_minute>=request.end_minute)throw new Error("마치는 시간은 시작 시간보다 늦게 골라주세요.");if(automatic){request.query=$("#auto-route-query").value.trim();request.region=$("#auto-route-region").value;request.excluded_ids=[...autoExcludedIDs];}else{addSavedDestinations(request);}lastTripRequest=request;const result=await getJSON(automatic?"/api/agent/plan":"/api/plan-destinations",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(request)});if(ticket!==tripRequest)return;renderRoute(result);}catch(exc){if(ticket!==tripRequest)return;error.textContent=exc.message||"추천을 불러오지 못했어요.";error.hidden=false;}finally{if(ticket===tripRequest){button.disabled=false;updatePlanningMode();}}
});
// V3 feature declarations and startup follow.

function todayKST() {
  const parts=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Seoul",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date());
  const get=type=>parts.find(p=>p.type===type)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}
function dateLabel(value) {
  const text=String(value||"");
  if(/^\d{8}$/.test(text))return `${text.slice(0,4)}.${text.slice(4,6)}.${text.slice(6,8)}`;
  if(/^\d{6}$/.test(text))return `${text.slice(0,4)}.${text.slice(4,6)}`;
  return text.replace(/-/g,".");
}
function periodLabel(period) { return period?.start&&period?.end ? `${dateLabel(period.start)}–${dateLabel(period.end)}` : "자료 기준기간 확인 필요"; }
function normalizeOverlapEvidence(raw) {
  if(!raw||typeof raw!=="object"||Array.isArray(raw))return null;
  const source=value=>value&&typeof value==="object"&&!Array.isArray(value)?{id:String(value.id||"").slice(0,120),name:String(value.name||"").slice(0,180),source_url:safeLink(value.source_url)}:null;
  return {hub:source(raw.hub),osm:source(raw.osm),distance_m:typeof raw.distance_m==="number"&&Number.isFinite(raw.distance_m)&&raw.distance_m>=0?raw.distance_m:null,match_method:typeof raw.match_method==="string"?raw.match_method.slice(0,80):""};
}
function normalizeExtraPlace(raw) {
  if(!raw||typeof raw!=="object"||Array.isArray(raw))return null;
  const id=raw.id,name=raw.name,lat=raw.latitude,lon=raw.longitude;
  if((raw.kind==="attraction"||String(id||"").startsWith("osm_tourism_"))&&raw.source_overlap_verified!==true)return null;
  if(typeof id!=="string"||!id||id.length>120||typeof name!=="string"||!name.trim()||name.length>180)return null;
  if(typeof lat!=="number"||typeof lon!=="number"||!Number.isFinite(lat)||!Number.isFinite(lon)||lat<33||lat>34||lon<126||lon>127.5)return null;
  const short=(value,max)=>typeof value==="string"?value.slice(0,max):"";
  return {id,name:name.trim(),address:short(raw.address,350),latitude:lat,longitude:lon,
    region:Object.hasOwn(regions,raw.region)?raw.region:"all",region_label:short(raw.region_label,80),
    category:short(raw.category,60)||"장소참조",image:null,tags:Array.isArray(raw.tags)?raw.tags.filter(v=>typeof v==="string").slice(0,8).map(v=>v.slice(0,40)):[],
    description:short(raw.description,600),source_url:safeLink(raw.source_url),source_name:short(raw.source_name,100)||"제주데이터허브 장소 참조",
    source_date:short(raw.source_date,30),requires_ferry:raw.requires_ferry===true,requires_access_point:raw.requires_access_point===true,
    kind:short(raw.kind,30),source_overlap_verified:raw.source_overlap_verified===true,
    cross_source:normalizeOverlapEvidence(raw.cross_source),tourism_guide:normalizeTourismGuide(raw.tourism_guide),source_platform:short(raw.source_platform,60),data_license:short(raw.data_license,30),
    featured:false};
}
function renderAudience() {
  $$("[data-audience]").forEach(button=>{const active=button.dataset.audience===audience;button.classList.toggle("active",active);button.setAttribute("aria-pressed",String(active));});
}
function restaurantMarkup(item) {
  const source=safeLink(item.source_url);
  const affinity=typeof item.affinity_category==="string"?item.affinity_category:"";
  return `<article class="restaurant-card"><div class="restaurant-card-top"><span>${escapeHTML(item.category||"음식점 명부")}</span>${source?`<a href="${escapeHTML(source)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHTML(item.name)} 데이터 원문 보기">↗</a>`:""}</div><h3>${escapeHTML(item.name)}</h3><p>${escapeHTML(item.address||"주소 정보 확인 필요")}</p>${affinity?`<span class="restaurant-affinity">연결 업종 · ${escapeHTML(affinity)}</span>`:""}${item.status?`<span class="restaurant-record-status">자료상 상태 · ${escapeHTML(item.status)}</span>`:""}${item.source_date?`<span class="restaurant-record-status">기록 갱신 · ${escapeHTML(dateLabel(item.source_date))}</span>`:""}${item.address?`<a class="place-map-button external-address-map" href="https://www.openstreetmap.org/search?${escapeHTML(new URLSearchParams({query:item.address}).toString())}" target="_blank" rel="noopener noreferrer">주소로 외부 지도 검색 ↗</a>`:""}</article>`;
}
function renderFoodProfile(payload) {
  const categories=Array.isArray(payload.categories)?payload.categories.filter(c=>c&&typeof c.name==="string").slice(0,8):[];
  const selected=payload.model?.selected_serving_model,mean=selected==="audience_mean";
  const usesMonth=typeof payload.model?.monthly_periodicity==="boolean"?payload.model.monthly_periodicity:!mean;
  $("#food-month").disabled=!usesMonth;
  $(".food-month-label").hidden=!usesMonth;
  const methodNote=mean?"검증 기준으로 집단 평균 경향을 사용합니다. 월별 선택은 적용되지 않습니다.":selected==="recency_weighted_seasonal_ridge"?"최근 실측 자료에 가중치를 둔 월별 과거 소비 구성비입니다.":"과거 자료에서 학습한 집단별 업종 경향입니다.";
  $("#food-insight-summary").innerHTML=`<span>${escapeHTML(payload.audience_label||(audience==="resident"?"제주도민 분류":"내국인 분류"))} · ${escapeHTML(periodLabel(payload.observation_period))} 관측</span><p>${escapeHTML(payload.data_group_label||"")}${audience==="tourist"?" · 내국인 분류 전체를 모든 관광객의 선호로 해석할 수 없습니다.":""}</p><p>${escapeHTML(methodNote)} 현재보다 오래된 자료입니다.</p>`;
  $("#food-category-chips").innerHTML=categories.map(category=>{const share=Number(category.share);return `<div class="food-category-chip"><span>${escapeHTML(category.name)}</span><b>${Number.isFinite(share)&&share>=0&&share<=1?`${(share*100).toFixed(1)}%`:"확인 중"}</b></div>`;}).join("");
}
async function loadRestaurants() {
  const ticket=++restaurantRequest,query=$("#restaurant-search").value.trim();
  const month=$("#food-month").value||String(Number(todayKST().slice(5,7)));
  $("#restaurant-count").textContent="음식점 자료를 살펴보고 있어요";
  try {
    const [insight,matching]=await Promise.allSettled([
      getJSON(`/api/insights/food?${new URLSearchParams({audience,month,region})}`),
      query?getJSON(`/api/restaurants?${new URLSearchParams({region,query,limit:"6"})}`):Promise.resolve(null)
    ]);
    if(ticket!==restaurantRequest)return;
    let records,sourceDate="";
    if(insight.status==="fulfilled"&&insight.value?.status==="historical_pattern") {
      renderFoodProfile(insight.value);
      records=Array.isArray(insight.value.restaurants)?insight.value.restaurants:[];
    } else {
      $("#food-insight-summary").textContent="집단별 소비 경향 연결을 확인하지 못했어요. 음식점 명부는 계속 찾아볼 수 있습니다.";
      $("#food-category-chips").innerHTML="";
      $("#food-month").disabled=true;
      $(".food-month-label").hidden=true;
    }
    if(query) {
      if(matching.status!=="fulfilled")throw matching.reason;
      records=Array.isArray(matching.value.items)?matching.value.items:[];
      sourceDate=matching.value.source_date||"";
      $("#restaurant-count").textContent=`${regions[region]} · 이름·주소 검색 ${Number(matching.value.total??records.length).toLocaleString("ko-KR")}곳`;
    } else {
      if(!records){const fallback=await getJSON(`/api/restaurants?${new URLSearchParams({region,limit:"6"})}`);if(ticket!==restaurantRequest)return;records=Array.isArray(fallback.items)?fallback.items:[];sourceDate=fallback.source_date||"";}
      $("#restaurant-count").textContent=`${regions[region]} · 업종에 연결한 음식점 명부 ${Math.min(records.length,6)}곳`;
    }
    const items=records.filter(item=>item&&typeof item.name==="string").slice(0,6);
    $("#restaurant-grid").innerHTML=items.length?items.map(restaurantMarkup).join(""):`<div class="restaurant-empty">이 조건에 맞는 기록이 없어요. 다른 지역이나 식당 이름으로 찾아보세요.</div>`;
    $("#restaurant-note").textContent=`${sourceDate?`${dateLabel(sourceDate)} 기준 · `:""}과거 인허가 명부 · 개별 식당 인기 순위가 아닙니다. 현재 영업·메뉴·가격은 방문 전 확인하세요.`;
  } catch(error) {
    if(ticket!==restaurantRequest)return;
    $("#restaurant-count").textContent="음식점 자료 연결 확인 필요";
    $("#restaurant-grid").innerHTML=`<div class="restaurant-empty">${escapeHTML(error?.message||"음식점 자료를 불러오지 못했어요.")}</div>`;
  }
}
function renderPlaceResults() {
  $("#place-results").innerHTML=placeResults.map(item=>{const id=itemID(item),source=safeLink(item.source_url),active=saved.has(id);return `<article class="place-reference-card"><div class="place-reference-copy"><span class="place-reference-region">${escapeHTML(itemRegion(item))} · 교차확인 관광지</span><h3>${escapeHTML(item.name)}</h3><p>${escapeHTML(item.address||"주소 정보 확인 필요")}</p><div class="place-reference-meta">${item.source_date?`<span>${escapeHTML(dateLabel(item.source_date))} 기준</span>`:""}${item.requires_ferry?"<span>배편 확인 필요</span>":""}${item.requires_access_point?"<span>접근 입구 별도 확인</span>":""}${source?`<a href="${escapeHTML(source)}" target="_blank" rel="noopener noreferrer">자료 출처 ↗</a>`:""}<button type="button" class="place-map-button" data-map-place="${escapeHTML(id)}">지도에서 보기 ↗</button></div></div><button type="button" class="place-add ${active?"active":""}" data-place-add="${escapeHTML(id)}" aria-pressed="${active}">${icon(active?"check":"heart")} ${active?"담았어요":"여행에 담기"}</button></article>`;}).join("");
}
async function loadPlaces() {
  const ticket=++placesRequest,query=$("#place-query").value.trim(),selectedRegion=$("#place-region").value;
  if(query.length<2){placeResults=[];renderPlaceResults();$("#place-result-count").textContent=query?"두 글자 이상 입력해 주세요.":"";return;}
  $("#place-result-count").textContent="장소 참조 자료를 찾고 있어요…";
  try {
    const payload=await getJSON(`/api/places?${new URLSearchParams({query,region:selectedRegion,limit:"12"})}`);
    if(ticket!==placesRequest)return;
    placeResults=(Array.isArray(payload.items)?payload.items:[]).slice(0,12).map(normalizeExtraPlace).filter(item=>item&&item.source_overlap_verified===true);
    renderPlaceResults();
    const total=Number(payload.total);
    $("#place-result-count").textContent=placeResults.length?`검색 ${Number.isFinite(total)?total.toLocaleString("ko-KR"):placeResults.length}곳 중 ${placeResults.length}곳 표시${payload.source_date?` · ${dateLabel(payload.source_date)} 기준`:""}`:"해당 이름·주소의 기록이 없어요. 다른 검색어를 입력해 주세요.";
  } catch(error) {
    if(ticket!==placesRequest)return;
    placeResults=[];renderPlaceResults();$("#place-result-count").textContent=error.message||"장소 검색 연결을 확인하지 못했어요.";
  }
}
async function loadParking() {
  const ticket=++parkingRequest;
  $("#parking-results").textContent="주차장 위치 자료를 확인하고 있어요…";
  try {
    const payload=await getJSON(`/api/amenities?${new URLSearchParams({type:"parking",region:$("#place-region").value})}`);
    if(ticket!==parkingRequest)return;
    const items=(Array.isArray(payload.items)?payload.items:[]).slice(0,6);
    if(!items.length){$("#parking-details").hidden=true;return;}
    $("#parking-details").hidden=false;
    $("#parking-results").innerHTML=`<p class="parking-note">${escapeHTML(payload.source_date?`${dateLabel(payload.source_date)} 기준 · `:"")}위치 참조 목록입니다. 운영 여부·요금·실시간 잔여면수는 확인되지 않았습니다.</p><div class="parking-list">${items.map(item=>{const source=safeLink(item.source_url);return `<article><h4>${escapeHTML(item.name||"주차장")}</h4><p>${escapeHTML(item.address||"주소 정보 확인 필요")}</p>${source?`<a href="${escapeHTML(source)}" target="_blank" rel="noopener noreferrer">자료 출처 ↗</a>`:""}</article>`;}).join("")}</div>`;
  } catch {
    if(ticket===parkingRequest)$("#parking-details").hidden=true;
  }
}
function mobilitySlotMarkup(slot,max,recommendedLabel) {
  const rate=Number(slot.predicted_users_per_hour),hours=Number(slot.bucket_hours),bucket=Number(slot.predicted_bucket_users);
  const chosen=slot.label===recommendedLabel;
  const width=max>0?Math.min(100,Math.max(0,rate/max*100)):0;
  return `<li class="mobility-row ${chosen?"chosen":""}"><div class="mobility-row-head"><span>${escapeHTML(slot.label)} ${chosen?"<em>참고 시간대</em>":""}</span><strong>${rate.toLocaleString("ko-KR",{maximumFractionDigits:1})}<small>인원/시간</small></strong></div><div class="mobility-bar" aria-hidden="true"><span style="width:${width.toFixed(2)}%"></span></div><p>${Number.isFinite(hours)?`${hours}시간 구간`:""}${Number.isFinite(bucket)?` · 구간 합계 모델값 ${Math.round(bucket).toLocaleString("ko-KR")}`:""}</p></li>`;
}
async function loadMobility() {
  const ticket=++mobilityRequest,date=$("#mobility-date").value,period=$("#mobility-period").value,button=$("#mobility-submit");
  if(!/^\d{4}-\d{2}-\d{2}$/.test(date)){notify("참고할 날짜를 골라주세요.");return;}
  button.disabled=true;
  $("#mobility-result").innerHTML='<p class="insight-empty">과거 시간대 패턴을 비교하고 있어요…</p>';
  try {
    const payload=await getJSON(`/api/insights/mobility?${new URLSearchParams({date,period})}`);
    if(ticket!==mobilityRequest)return;
    const slots=(Array.isArray(payload.slots)?payload.slots:[]).filter(slot=>slot&&typeof slot.label==="string"&&Number.isFinite(Number(slot.predicted_users_per_hour))&&Number(slot.predicted_users_per_hour)>=0);
    if(payload.status!=="historical_pattern"||!slots.length)throw new Error(payload.message||"시간대 패턴 자료가 아직 연결되지 않았어요.");
    const max=Math.max(...slots.map(slot=>Number(slot.predicted_users_per_hour)));
    const preferred=slots.filter(slot=>slot.within_preferred_period===true),primary=preferred.length?preferred:slots.slice(0,3);
    const other=slots.filter(slot=>!primary.includes(slot));
    const recommendedLabel=typeof payload.recommended_slot==="string"?payload.recommended_slot:payload.recommended_slot?.label||"";
    const method=String(payload.model?.selected_serving_model||payload.model?.algorithm||"");
    const methodNote=/mean|average|baseline/.test(method)?"검증 기준으로 과거 요일·시간대 평균 패턴을 사용합니다.":method==="huber_calendar"?"과거 실측 자료의 요일·계절·시간대 관계를 학습한 모델입니다. 관측이 오래된 기간에는 한계가 있습니다.":"과거 일반 승차 자료의 학습 패턴입니다.";
    $("#mobility-result").innerHTML=`<div class="mobility-result-top"><span>${escapeHTML(dateLabel(date))}의 과거 패턴</span><p>${escapeHTML(payload.scope||"제주 전체 일반 승차 집계")} · 시간당 비교</p></div>${recommendedLabel?`<p class="mobility-recommendation">선택한 시간대 중 <strong>${escapeHTML(recommendedLabel)}</strong> 구간을 참고해 보세요.</p>`:""}<ol class="mobility-slots">${primary.map(slot=>mobilitySlotMarkup(slot,max,recommendedLabel)).join("")}</ol>${other.length?`<details class="mobility-other"><summary>다른 시간대 ${other.length}개도 보기 <span>+</span></summary><ol class="mobility-slots">${other.map(slot=>mobilitySlotMarkup(slot,max,recommendedLabel)).join("")}</ol></details>`:""}<p class="mobility-period-note">관측 ${escapeHTML(periodLabel(payload.observation_period))}${payload.is_stale?" · 현재보다 오래된 자료": ""}<br>${escapeHTML(methodNote)} 실시간 혼잡과 버스 운행시각은 별도로 확인하세요.</p>`;
  } catch(error) {
    if(ticket===mobilityRequest)$("#mobility-result").innerHTML=`<p class="insight-empty">${escapeHTML(error.message||"시간대 비교를 불러오지 못했어요.")}</p>`;
  } finally {if(ticket===mobilityRequest)button.disabled=false;}
}

function saveItinerary() {
  const result=lastRoute;
  if(!result||result.data_mode!=="reference"||result.status!=="ok"||!Array.isArray(result.stops)||!result.stops.length){notify("먼저 하루 일정을 만들어주세요.");return;}
  const req=result.request||lastTripRequest||{},totals=result.totals||{};
  const day=String(req.date||todayKST()),mode=result.selection_mode==="automatic"?"공식 소개·교차확인 자료를 검색하고 시간·거리 조건으로 선택한 실제 장소 일정 초안":"선택한 실제 장소의 방문 순서 초안";
  const revised = typeof req.origin_place_id === "string" && req.origin_place_id.length > 0;
  const journeyContext = revised
    ? `<p>남은 여행 코스 · ${escapeHTML(req.origin_label)} ${escapeHTML(clock(req.start_minute))} 출발 · 기존 도착지 ${escapeHTML(clock(req.end_minute))}까지</p>`
    : "";
  const distanceNote = result.travel_estimate?.basis === "osm_road_distance"
    ? "OSM 도로 거리와 가정 속도로 이동시간을 추정했습니다. 실제 교통·통행 조건과 방문지 운영은 별도로 확인하세요."
    : "좌표 거리와 가정 속도로 이동시간을 추정했습니다. 실제 도로·교통과 방문지 운영은 별도로 확인하세요.";
  const stopHTML=result.stops.map((stop,index)=>{
    const item=destinations.find(p=>itemID(p)===String(stop.poi_id||stop.id||""));
    const source=safeLink(stop.source_url||item?.source_url),unknown=true;
    const proof=stop.trust||{},guide=stop.tourism_guide||item?.tourism_guide,sources=Array.isArray(proof.sources)?[...proof.sources]:[];if(guide?.source_url&&!sources.some(s=>(s.url||s.source_url)===guide.source_url))sources.unshift({name:guide.source_name||"공식 관광 안내",url:guide.source_url,checked_at:guide.retrieved_at});const trustLinks=sources.map(s=>{const link=/^https?:\/\//i.test(s.url||s.source_url||"")?safeLink(s.url||s.source_url):"";return link?`<a href="${escapeHTML(link)}" target="_blank" rel="noopener noreferrer">${escapeHTML(s.label||s.name||s.source_name||"근거 원문")}</a>${s.checked_at?` (자료 기준·소개 확인 ${escapeHTML(s.checked_at)})`:""}`:"";}).filter(Boolean).join(" · ");
    return `<li><p class="time">${index+1}번째 · ${escapeHTML(clock(stop.arrival_minute))}–${escapeHTML(clock(stop.departure_minute))}</p><h2>${escapeHTML(stop.name)}</h2><p>체류 ${escapeHTML(stop.stay_minutes??"미확인")}분 · 앞 장소에서 이동 약 ${escapeHTML(stop.travel_minutes??"미확인")}분 추정${Number.isFinite(stop.travel_km)?` · ${stop.travel_km.toFixed(2)}km`:""}</p><p>${unknown?"입장료·식사비 등 방문 비용 미확인":`방문 비용 ${escapeHTML(won(stop.cost_krw))}`}</p>${(stop.address||item?.address)?`<p>주소 ${escapeHTML(stop.address||item.address)}</p>`:""}${trustLinks?`<p>관광 근거 ${trustLinks}</p><p>현재 영업·입구·요금은 방문 전 확인해야 합니다.</p>`:""}${(Array.isArray(proof.warnings)?proof.warnings:[]).filter(w=>typeof w==="string").slice(0,12).map(w=>`<p>장소 확인사항 ${escapeHTML(w)}</p>`).join("")}<p>출처 ${source?`<a href="${escapeHTML(source)}" target="_blank" rel="noopener noreferrer">${escapeHTML(stop.source_id||item?.source_name||"장소 자료 원문")}</a>`:escapeHTML(stop.source_id||"장소 출처 별도 확인")}</p></li>`;
  }).join("");
  const warnings=Array.isArray(result.warnings)?result.warnings:[];
  const osmCredit=(result.travel_estimate?.basis==="osm_road_distance"||result.stops.some(stop=>String(stop.poi_id||stop.id||" ").startsWith("osm_")))?`<p>지도 업소 자료 © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a> · <a href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noopener noreferrer">ODbL</a>. 공동 편집 지도이며 현재 영업·메뉴·입구는 미확인입니다.</p>`:"";
  const documentHTML=`<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>${escapeHTML(day)} 제주 여행 일정</title><style>body{max-width:800px;margin:40px auto;padding:0 24px;background:#fffdf7;color:#173f47;font:15px/1.8 'Malgun Gothic',sans-serif}h1{font-size:30px;line-height:1.4}h2{font-size:21px;margin:0}a{color:#185a69;overflow-wrap:anywhere}.mode{padding:14px 0;border-block:1px solid #ced9d5}ol{padding-left:24px}li{padding:20px 0;border-bottom:1px solid #dce1da}p{margin:6px 0}.time{font-weight:700;color:#286675}footer{margin-top:30px;font-size:13px}li::marker{font-weight:700}section{margin-top:26px}@media print{body{background:#fff;margin:0;max-width:none}li{break-inside:avoid}a{color:inherit}}</style></head><body><header><p>제주 길벗 · 저장한 일정</p><h1>${escapeHTML(day)} 나의 제주 여행</h1><p class="mode">${escapeHTML(mode)}</p></header><section>${journeyContext}<p>방문 ${result.stops.length}곳 · 복귀 ${escapeHTML(clock(totals.end_arrival_minute))}</p><p>추정 이동비 ${totals.travel_cost_krw==null?"미확인":escapeHTML(won(totals.travel_cost_krw))}</p><p>입장료·식사비·주차비·렌터카 비용을 확인하지 않았습니다. 전체 예산 충족을 보장하지 않습니다.</p></section><ol>${stopHTML}</ol><section><h2>출발 전에 확인하세요</h2><p>${distanceNote}</p><ul>${warnings.map(value=>`<li>${escapeHTML(value)}</li>`).join("")}</ul></section><footer>${osmCredit}이 파일에는 사진과 외부 실행 코드가 없습니다. 여행 순서는 시간·비용 조건을 검색한 초안이며 개별 장소의 인기 순위가 아닙니다.</footer></body></html>`;
  const url=URL.createObjectURL(new Blob([documentHTML],{type:"text/html;charset=utf-8"}));
  const anchor=document.createElement("a");anchor.href=url;anchor.download=`jeju-gilbeot-${day.replace(/[^0-9-]/g,"")||"itinerary"}${revised?"-remaining-"+String(req.start_minute):""}.html`;document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  notify("일정 파일을 저장했어요. 출처와 확인할 내용을 함께 담았습니다.");
}
function resetTrip() {
  ++restaurantRequest;++placesRequest;++parkingRequest;++mobilityRequest;++tripRequest;
  clearTimeout(restaurantTimer);clearTimeout(placesTimer);
  $$("dialog[open]").forEach(closeDialog);
  saved.clear();restoredExtras=[];destinations=destinations.filter(item=>item.featured!==false);placeResults=[];lastRoute=null;lastTripRequest=null;
  try{sessionStorage.removeItem(SESSION_KEY);}catch{/* No browser storage is required for an empty session. */}
  $("#hero-search").reset();$("#planner-form").reset();$("#place-search-form").reset();$("#mobility-form")?.reset();
  $("#hero-keyword").value="";$("#destination-search").value="";$("#restaurant-search").value="";$("#restaurant-region").value="all";
  searchText="";region="all";audience="tourist";
  $("#food-month").value=String(Number(todayKST().slice(5,7)));$("#travel-date").value=todayKST();if($("#mobility-date"))$("#mobility-date").value=todayKST();
  $("#trip-result").hidden=true;$("#trip-result").innerHTML="";$("#planner-error").hidden=true;$("#planner-error").textContent="";
  $("#destination-detail").innerHTML="";$("#place-result-count").textContent="";$("#parking-results").textContent="";$("#parking-details").open=false;$("#parking-details").hidden=false;
  if($("#mobility-result"))$("#mobility-result").innerHTML='<p class="insight-empty">날짜와 이동 시간대를 골라 비교해 보세요.</p>';
  if($("#mobility-submit"))$("#mobility-submit").disabled=false;$("#create-trip").disabled=false;$(".location-details").open=false;
  $(".main-nav").classList.remove("open");$("#mobile-menu").setAttribute("aria-expanded","false");$("#mobile-menu").setAttribute("aria-label","메뉴 열기");
  $$(".region-chip").forEach(chip=>{const active=chip.dataset.region==="all";chip.classList.toggle("active",active);chip.setAttribute("aria-pressed",String(active));});
  renderAudience();renderDestinations();renderSaved();renderPlaceResults();updatePlanningMode();loadRestaurants();
  window.dispatchEvent(new Event("jeju:reset"));window.scrollTo({top:0,behavior:"smooth"});notify("이전 목록과 입력을 지웠어요. 새로운 제주 여행을 시작하세요.");
}

$("#reset-trip").addEventListener("click", () => {
  const hasTrip = saved.size || lastRoute || $("#observed-csv-file")?.files?.length;
  if (hasTrip && !window.confirm("이 탭의 일정, 모아둔 장소와 선택 파일을 지우고 새 여행을 시작할까요?")) return;
  resetTrip();
});
$("#food-month").addEventListener("change",loadRestaurants);
$("#place-search-form").addEventListener("submit",event=>{event.preventDefault();loadPlaces();});
$("#place-query").addEventListener("input",()=>{clearTimeout(placesTimer);++placesRequest;if($("#place-query").value.trim().length<2){placeResults=[];renderPlaceResults();$("#place-result-count").textContent="";return;}placesTimer=setTimeout(loadPlaces,350);});
$("#place-region").addEventListener("change",()=>{if($("#place-query").value.trim().length>=2)loadPlaces();$("#parking-details").hidden=false;if($("#parking-details").open)loadParking();});
$("#parking-details").addEventListener("toggle",()=>{if($("#parking-details").open)loadParking();});
$("#mobility-form")?.addEventListener("submit",event=>{event.preventDefault();loadMobility();});
$("#travel-date").value=todayKST();if($("#mobility-date"))$("#mobility-date").value=todayKST();$("#food-month").value=String(Number(todayKST().slice(5,7)));
$("#center-check-button")?.addEventListener("click", async()=>{
  const button=$("#center-check-button"), output=$("#center-check-result");
  button.disabled=true; output.textContent="이 PC에서 응답을 확인하고 있어요.";
  try {
    const status = await getJSON("/api/operational-check");
    const report = [
      status.models_ready ? `운영 모델 ${status.model_count}종` : "모델 자료 확인 필요",
      `자동 코스 후보 ${status.automatic_places}곳`,
      `유효한 공식 소개 ${status.guides_current}곳`,
      status.road_file_present ? "로컬 도로 파일 있음" : "로컬 도로 파일 확인 필요",
    ];
    if (status.unavailable_models?.includes("1047")) report.push("1047 외식 모델 자료 확인 필요");
    if (status.guides_due_within_30_days) report.push(`30일 안에 재검토할 소개 ${status.guides_due_within_30_days}곳`);
    if (status.guides_overdue) report.push(`재검토 기한을 지난 소개 ${status.guides_overdue}곳`);
    output.textContent = report.join(" · ");
  } catch { output.textContent="로컬 서버에 연결하지 못했습니다. 실행 창을 확인한 뒤 다시 시도해 주세요."; }
  finally { button.disabled=false; }
});
initPlannerOrigin();renderSaved();renderAudience();updatePlanningMode();
Promise.allSettled([loadDestinations(),loadRestaurants(),loadDataStatus(),loadModelStatus()]);

// Shared travel actions; location state is held separately in tab memory.
window.JejuTripBridge={
  beginPlan: beginGuidedPlan,
  addPlace(raw) {
    const existing = destinations.find(item=>itemID(item)===String(raw.id));
    const point = existing || normalizeExtraPlace(raw);
    if (!point) {
      notify("이 장소는 일정에 연결할 좌표·원본 ID를 확인하지 못했어요.");
      return false;
    }
    if (!existing) destinations.push(point);
    if (saved.has(point.id)) {
      if (!existing) {
        restoredExtras = restoredExtras.filter(ref=>ref.id!==point.id);
        persist();
        renderSaved();
      }
      notify("이미 여행에 담아둔 장소예요.");
      return true;
    }
    toggleSaved(point.id);
    return saved.has(point.id);
  },
  getRoute(){return lastRoute;},
  getConfirmedOrigin(){return plannerOriginRequest();},
  getSaved(){return destinations.filter(p=>saved.has(itemID(p)));},
  openPlace(raw, options){return showRichDetail(raw, options);},
  async createMapRoute(){
    let req;
    try {
      req = {...formRequest(), max_stops:"all"};
      addSavedDestinations(req);
    } catch (error) {
      showPlannerInputs(error.message);
      throw error;
    }
    const ticket = ++tripRequest;
    lastTripRequest = req;
    const result = await getJSON("/api/plan-destinations", {
      method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(req)
    });
    if (ticket !== tripRequest) throw new Error("출발지나 조건이 바뀌어 이전 경로를 표시하지 않습니다.");
    renderRoute(result);
    if (result.status === "ok") {
      setTimeout(()=>{
        const map = $("#map-explorer");
        window.JejuPages?.reveal(map);
        map.scrollIntoView({behavior:"smooth"});
      },0);
    }
    return result;
  }
};
