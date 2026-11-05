# v4 지도·기기 위치·음식점 좌표의 출처와 운영 조건

확인일: 2026-10-28. 이번 구현은 센터 PC의 CPU 로컬 웹앱을 기준으로 한다. 지도 표시와 식당 검색에 필수 API 키는 없다. 원격 서비스를 무제한·무중단으로 사용할 수 있다는 의미는 아니다.

## 1. 채택한 구성

| 구성 | 실제 역할 | 외부 연결 | 권리·조건 |
|---|---|---|---|
| 로컬 SVG + Natural Earth 해안선 | 저장된 장소 좌표와 기기 위치의 참고도 | 없음 | Natural Earth public domain |
| 로컬 Leaflet 1.9.4 | 선택적 온라인 지도를 그리는 SDK | SDK 로딩은 로컬 | BSD-2-Clause, 원본 LICENSE 보존 |
| OpenStreetMap 표준 래스터 타일 | 사용자가 켠 온라인 배경지도 | 켠 뒤 열람 타일만 요청 | 타일 정책 준수, 지도 위 출처 표시, 제공 보장 없음 |
| 브라우저 Geolocation | 사용자 동의 후 기기 위치 추정 | 웹앱은 좌표를 외부 지도에 자동 전송하지 않음 | 브라우저·OS 위치 서비스의 동작과 정확도는 별개 |
| OSM 업소 좌표 스냅샷 | 이름이 있는 음식점·카페·패스트푸드의 별도 검색 자료 | 개발 중 고정 제주 영역을 1회 조회; 실행 중 API 호출 없음 | ODbL-1.0, 출처·라이선스·정규화 자료 보존 |

온라인 지도는 경로 탐색 엔진이 아니다. 장소 점과 배경지도를 표시하며 도로 길찾기, 실시간 교통, 영업 여부, 인기, 맛 평가를 계산하지 않는다.

## 2. 기본 오프라인 참고도

원본은 [Natural Earth 1:10m Land v5.1.1](https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-land/)이다. 공식 설명의 `10m`은 **축척 1:10,000,000**을 뜻하며 10미터 정밀도가 아니다. 원본 WGS84 육지 폴리곤에서 `[126.05, 33.0, 127.05, 33.65]` 안에 완전히 들어오는 링 2개만 추출했다. 본섬 61점과 우도 12점, 총 73개 좌표이며 소수 6자리로 반올림했다.

이 자료에는 가파도·마라도 등 작은 섬 일부가 축척상 없다. 별도 도로·읍면동 경계·고도·진입로를 만들어 넣지 않았다. 화면의 작은 섬 생략 안내와 “오프라인 위치 참고도” 표시를 유지한다. 좌표는 일정한 기준 위도 33.355°의 등거리 원통 투영으로 표시하며 축척 막대는 대략적 거리다. 행정 경계도나 정밀 측량·항해 지도로 사용하지 않는다.

[Natural Earth 이용 조건](https://www.naturalearthdata.com/about/terms-of-use/)은 배포 데이터가 public domain이며 수정·배포·상업 이용을 허용한다고 명시한다. 출처 표시는 자발적으로 유지했다. 제주도 공인 행정경계 자료로 표현하지 않는다.

| 보존 항목 | 값 |
|---|---|
| 원본 URL | `https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip` |
| 원본 크기 | 3,269,070 bytes |
| 원본 SHA-256 | `e547d749445eaa0964aba76738090ec88f5e63c4585122170f98c67a7ea922dc` |
| 파생 GeoJSON | `ui/vendor/leaflet/jeju-land.geojson` |
| 파생 SHA-256 | `fff9ddb37e0bacc003616f6f32555a296f7a69dee20be23cac76b5a665fba61f` |
| 추출·권리 기록 | `ui/vendor/leaflet/NATURAL_EARTH_SOURCE.json` |

GeoJSON 좌표는 `ui/jeju-map.js`에도 넣었다. 따라서 런타임에 GeoJSON 파일이나 지도 서버를 요청하지 않는다. 원본 ZIP은 개발용 `jeju_v4_work/map_research`에 보존하고 실행 프로젝트에는 필요한 파생 좌표와 출처만 포함했다.

## 3. Leaflet 로컬 공급망

[Leaflet 공식 다운로드 페이지](https://leafletjs.com/download.html)가 안내하는 안정 버전 1.9.4의 고정 CDN 경로에서 SDK를 내려받았다. 브라우저가 CDN을 직접 요청하는 구현이 아니다. 공식 페이지의 JS/CSS SRI 값과 내려받은 바이트의 SHA-256을 대조해 일치를 확인했다. [공식 v1.9.4 LICENSE](https://raw.githubusercontent.com/Leaflet/Leaflet/v1.9.4/LICENSE)는 BSD 2-Clause다.

| 로컬 파일 | bytes | SHA-256 |
|---|---:|---|
| `leaflet.js` | 147,552 | `db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a` |
| `leaflet.css` | 14,806 | `a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6` |
| `LICENSE` | 1,395 | `53e8dc25862014e4324741ca18fbe3611e11d42ef69f59f86ea8c5389647d4cb` |

경로는 모두 `ui/vendor/leaflet/` 아래다. CSS가 참조하는 공식 이미지 5개도 같은 버전의 `images/`에 보존했다. 개별 URL·크기·해시는 `VENDOR_MANIFEST.json`에 있다. JS/CSS 외부 CDN 태그와 외부 폰트는 이 모듈에 없다.

## 4. 온라인 타일 사용과 개인정보 경계

사용자는 먼저 IP와 열람 타일 범위가 OpenStreetMap에 전달된다는 안내를 본다. `온라인 지도 켜기` 버튼을 누른 경우에만 Leaflet 맵과 원격 타일 레이어를 만든다. 최초 뷰와 `제주 전체` 버튼은 항상 `[33.355, 126.565]`이며, 지도 폭 720px 미만에서는 zoom 9, 그 외에는 zoom 10이다. 사용자가 제주 주변을 직접 드래그하거나 zoom 8~18로 변경할 수 있다. 골목 단위 확대는 사용자가 직접 지도 컨트롤을 조작한 경우에만 발생하며, 검색 결과나 내 위치에 맞춘 `fitBounds`, `panTo`, 자동 확대는 하지 않는다. GPS 점과 정확도 원은 로컬 SVG에서만 그린다. 점이 겹치면 목록의 개별 `지도에서 보기` 또는 온라인 확대 기능을 이용하도록 안내한다.

공식 [OSM 타일 정책](https://operations.osmfoundation.org/policies/tiles/)에 따라 다음을 적용했다.

- URL은 `https://tile.openstreetmap.org/{z}/{x}/{y}.png`이며 키를 넣지 않는다.
- 지도 위 `© OpenStreetMap contributors`와 [저작권·라이선스 링크](https://www.openstreetmap.org/copyright)를 유지한다.
- 브라우저 기본 User-Agent와 HTTP 캐시를 사용한다. 타일에 `no-cache`를 추가하지 않는다. 타일 Referer 정책은 `strict-origin-when-cross-origin`으로 지정한다.
- 보이는 제주 주변 타일만 요청하고 `keepBuffer:0`, 비 Retina 모드로 동작한다. 대량 수집, 영역 내려받기, 서비스워커 캐시, 오프라인 타일 묶음, 미리 읽기를 구현하지 않았다.
- 첫 타일 오류 또는 초기 10초 동안 타일 로딩이 없으면 연결 오류 문구와 함께 로컬 참고도로 돌아간다. 끄기·새 사용자 초기화 시 `map.remove()`로 타일 레이어와 대기 중 이미지 요청을 정리한다.

OSM 타일 서버는 공용 자원이며 SLA·항상 제공되는 사용량·영구 무료 운영을 보장하지 않는다. 서비스 규모를 키우면 별도 제공자나 자체 호스팅 구성을 검토해야 한다. 현재 기본 오프라인 모드는 타일 서비스 상태와 독립적이다.

## 5. 기기 위치의 정확도와 권한

[W3C Geolocation 명세](https://www.w3.org/TR/geolocation/)는 GPS 외에도 Wi-Fi·IP 등 다양한 위치 추정원을 허용하고 실제 위치를 보장하지 않는다. `enableHighAccuracy:true`도 더 정확한 결과를 요청하는 힌트다. GPS 수신기가 없는 센터 PC에서 정밀 GPS가 된다고 표현하지 않는다. `accuracy`는 미터 단위 기기 정확도 추정값이며 화면에도 함께 보여 준다.

위치 API는 사용자 권한과 secure context를 요구한다. [W3C Secure Contexts](https://www.w3.org/TR/secure-contexts/)는 HTTPS와 loopback `127.0.0.1`, 조건을 충족하는 `localhost`를 신뢰 가능한 origin으로 취급한다. 일반 사설 IP의 HTTP 주소를 동일하게 보장하지 않는다. [MDN getCurrentPosition](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/getCurrentPosition)에서도 secure context·사용자 허용·타임아웃 조건을 확인했다.

지도 모듈은 직접 위치 권한을 요청하지 않는다. 앱이 허용받은 좌표를 `setLocation`/`setUserLocation`으로 넘기면 메모리와 SVG에만 표시하며 외부 타일 요청의 URL·중심·마커에 포함하지 않는다. 위치 끄기와 초기화는 앱 메모리 및 표시를 지우는 동작이다. 브라우저에 저장된 사이트 권한 자체를 철회하는 기능은 아니다. 브라우저·OS가 위치를 추정하는 과정의 외부 통신까지 이 앱이 차단하거나 완전 오프라인이라고 보장하지 않는다.

## 6. 새 OSM 음식점·카페 스냅샷

[Overpass 개발자 공식 매뉴얼의 공용 인스턴스 정책](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html)과 [OSM의 공식 API 안내](https://wiki.openstreetmap.org/wiki/Overpass_API)를 확인했다. 공용 Overpass를 매 사용자 요청의 상시 백엔드로 쓰지 않고, 공개 데이터 준비 단계에서 고정 제주 영역 1회만 내려받았다. 공유 서버 과부하·할당량·오류 가능성이 있으며 반복 재시도와 자동 새로고침은 넣지 않았다. 사용자 GPS·선호·이름은 조회에 사용하지 않았다.

```overpassql
[out:json][timeout:30][maxsize:33554432];
nwr["amenity"~"^(restaurant|cafe|fast_food)$"](32.9,126.0,33.7,127.0);
out center tags;
```

POST endpoint는 `https://overpass-api.de/api/interpreter`다. [태그·영역 조회 공식 설명](https://dev.overpass-api.de/overpass-doc/en/criteria/per_tag.html)에 맞춰 node/way/relation을 조회했다. 응답에 오류 `remark`가 없고 JSON `elements`가 유효함을 확인한 뒤 정규화했다.

| 관측한 항목 | 실제 값 |
|---|---:|
| 요청 횟수 | 1회 |
| HTTP | 200, application/json |
| 원본 bytes | 2,464,819 |
| 원본 요소 | 6,180 |
| 원본 node / way / relation | 5,808 / 369 / 3 |
| 원본 restaurant / cafe / fast_food | 5,508 / 586 / 86 |
| 이름·영역 내 유효 좌표가 있는 정규화 장소 | 6,102 |
| 이름 없음으로 제외 | 78 |
| cuisine 태그가 있는 정규화 장소 | 743 |
| 부분 주소 태그가 있는 정규화 장소 | 4,852 |
| OSM DB 기준 시각 | 2026-10-28T10:47:02Z |
| 다운로드 완료 UTC | 2026-10-28T10:49:02.720176+00:00 |

DB 기준 시각은 동기화 스냅샷 시각이며 6,102개 업소 모두가 그날 갱신됐거나 현재 운영한다는 뜻이 아니다. 좌표가 있어도 업체 신원·입구·영업·가격·맛을 확인한 기록은 아니다. way/relation의 `center`는 요소 경계상자의 중심이므로 입구 또는 폴리곤 내부를 보장하지 않는다. cuisine은 커뮤니티 태그이며 743곳 이외에는 결측을 임의의 음식 종류로 바꾸지 않는다.

원본은 `data_raw/osm/jeju_food_overpass.json`, 조회문·메타데이터·권리 고지는 같은 폴더에 있다. 원본 SHA-256은 `554c1eed694692681781877f0caa919bca5e3183df213cc104c4a2e48adf859d`다. 정규화 `data_reference/osm_food_places.json`은 4,623,615 bytes이며 SHA-256은 `b6f43b9afda08485039f8fdc58c34037e433e776495170e94d7be7bab1156415`다. OSM 정체성은 `osm_node_<id>`처럼 원천 유형과 ID를 보존한다. 인허가 780의 좌표라고 대체하거나 동일 업체로 강제 연결하지 않았다.

[OSM 저작권 안내](https://www.openstreetmap.org/copyright), [OSMF 출처 표시 가이드](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines), [ODbL 1.0 원문](https://opendatacommons.org/licenses/odbl/1-0/)에 따라 OSM 원본·파생 DB에는 ODbL 고지와 출처를 유지한다. 정규화 기계 판독 파일도 함께 제공한다. 화면 및 일정 HTML에서 OSM 업소를 사용하면 `© OpenStreetMap contributors`와 copyright 링크를 표시한다. 지도 모듈은 OSM 장소가 들어오면 오프라인 모드에도 업소 자료 출처 줄을 표시한다. 제주 허브·센터의 독립된 자료는 해당 원천의 출처·조건을 별도로 유지한다.

## 7. 프런트엔드 모듈 계약과 검증

```javascript
const map = window.JejuMap.mount(document.querySelector('#jeju-map'), {
  onPlaceSelect: place => openPlaceDetail(place) // onSelect 별칭도 지원
});
map.setPlaces(points); // id/name/latitude/longitude; source_name/data_license 등 선택 필드
map.setSelectedIds(savedIds);
map.setLocation({latitude, longitude, accuracy});
// setUserLocation({latitude, longitude, accuracy_m}) 별칭 지원
map.clearLocation(); // clearUserLocation 별칭
map.fit();          // GPS와 무관한 제주 전체
map.disableOnline();
map.destroy();
```

출력은 최대 50개다. 중복 ID, 잘못된 좌표, 제주 참고도 범위 밖 좌표를 처리하고 생략 안내를 표시한다. 마커와 선택 정보는 사용자 문자열을 HTML로 해석하지 않고 DOM `textContent`로 만든다. 온라인 마커의 아이콘 HTML에는 직접 생성한 숫자만 들어간다.

SDK 문법 검사와 독립 Node DOM/Leaflet mock 회귀 검증을 통과했다. 검증 항목은 기본 타일 레이어 생성 0회, GPS 설정만으로 원격 지도 생성 없음, 좌표 한도·검증, HTML 문자열 처리, GPS가 Leaflet 마커에 없는 점, 고정 제주 초기 뷰, 명시적 끄기·정리, 타일 오류와 SDK 부재의 오프라인 복귀다. mock은 실제 OSM 타일 전송의 성공이나 브라우저 위치 정확도를 보장하는 테스트가 아니다. 통합 브라우저 화면·권한·기본 네트워크 점검은 앱 전체 검증에서 별도로 확인한다.

## 8. 위치·초기화 독립 코드 검토

`ui/discovery.js`, `ui/app.js`의 저장 항목 정규화, `jeju_agent/discovery.py` 응답과 `server.py` 로그 처리를 읽기 전용으로 추가 확인했다. 이 검토에서 새 차단 문제는 찾지 못했다.

- `getCurrentPosition`은 `내 위치 사용` 클릭 처리에서만 호출한다. 초기 로딩·지도 표시·page 이벤트가 위치 권한을 자동 요청하지 않는다. 지도 모듈 자체에는 Geolocation 호출이 없다.
- 정밀 좌표는 상대 경로 `/api/discover`의 POST 본문으로 로컬 서버에만 전달된다. 외부 지도 주소 검색은 업소의 공개 주소를 사용한다. GPS가 외부 링크·타일 URL·공개 장소 마커에 들어가지 않는다.
- `geoGeneration`은 위치 삭제, 수동 기준 변경, 초기화, pagehide 이후의 늦은 기기 위치 콜백을 무효화한다. `requestId`는 위치 삭제와 초기화 이후 도착한 검색 응답의 재표시를 막는다.
- 위치 정보는 브라우저 저장소에 쓰지 않는다. 저장 장소의 `normalizeExtraPlace`는 공개 장소 좌표 등 제한된 필드만 남기며 기기 원점·기기 정확도·원점과의 거리를 저장하지 않는다.
- API 응답은 요청의 정밀 좌표를 되돌려 주지 않는다. 서버의 기본 로그는 요청 경로·상태를 기록하고 JSON 요청 본문을 기록하지 않는다.
- pagehide에서 기기 위치와 지도 기기 위치 마커를 지우며, BFCache 복귀의 persisted pageshow에서 새 사용자 초기화를 수행한다. 초기화는 온라인 타일 연결도 정리한다.

통합 작업의 `examples/location_ui_v4.json`에는 자동 권한 요청 없음, 거부·시간 초과·비보안 context의 대체 동작, 초기화 후 지연 콜백 무시, 로컬 POST 전용, 저장소 미사용 등 9개 검사 통과 기록이 있다. 이 조사·검토 과정에서는 실제 기기 위치의 권한 버튼을 누르거나 허용하지 않았다.
