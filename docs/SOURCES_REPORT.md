# 제주 관광지 사실정보와 실사진 취득 보고

취득일 2026년 10월 26일. 실제 자료를 다운로드하여 저장했다. 현재 작업 범위는 공식 관광지 참조정보와 실사진이며 방문량·식당 이용량·실시간 혼잡도는 포함하지 않는다.

## 취득 결과

| 파일 | 내용 | 건수 |
| --- | --- | --- |
| attractions_official.json 및 csv | 제주관광공사 비짓제주 공식페이지에서 추출한 참조자료 | 관광지 10곳 |
| destinations.json | 웹 UI 계약에 맞춘 관광지 데이터 | 관광지 10곳 |
| raw_official | 취득 증빙용 공식 페이지 HTML과 data key 원문 필드 JSON | 페이지 10개 및 원문 필드 10개 |
| images | 실제 명소 JPEG 사진 10장 및 성산 히어로 복사본 | 사진 10장 및 별칭 1개 |
| image_manifest.json | 사진별 저작자·출처·라이선스·이용조건 링크·원본/취득 URL·SHA256 | 사진 10장 및 히어로 정보 |
| PHOTO_CREDITS.md | 웹에서 연결하거나 함께 배포할 저작자 표시 문서 | 1개 |

공식페이지 참조자료는 공공데이터포털의 별도 배포 CSV를 받았다고 표시하면 안 된다. 다운로드한 공식 HTML에 서버 렌더링된 `data-key`의 사실정보를 정규화한 것이다. 원문 서술형 본문과 비짓제주 공식 사진은 서비스 자산으로 재사용하지 않았다. 웹 UI의 소개는 짧게 새로 작성했고 사진은 아래 개별 공개 라이선스 자료를 사용했다.

## 공식 관광지 출처

| ID | 관광지 | 공식 출처 |
| --- | --- | --- |
| seongsan | 성산일출봉 | [비짓제주 500349](https://www.visitjeju.net/kr/detail/view?contentsid=CONT_000000000500349) |
| hyeopjae | 협재해수욕장 | [비짓제주 500697](https://www.visitjeju.net/kr/detail/view?contentsid=CONT_000000000500697) |
| hamdeok | 함덕해수욕장 | [비짓제주 500693](https://www.visitjeju.net/kr/detail/view?contentsid=CONT_000000000500693) |
| hallasan | 한라산국립공원 | [비짓제주 500685](https://www.visitjeju.net/kr/detail/view?contentsid=CONT_000000000500685) |
| saryeoni | 사려니숲길 | [비짓제주 500281](https://www.visitjeju.net/kr/detail/view?contentsid=CONT_000000000500281) |
| cheonjiyeon | 천지연폭포 | [비짓제주 500618](https://www.visitjeju.net/kr/detail/view?contentsid=CONT_000000000500618) |
| jeongbang | 정방폭포 | [비짓제주 500531](https://www.visitjeju.net/kr/detail/view?contentsid=CONT_000000000500531) |
| seopjikoji | 섭지코지 | [비짓제주 500343](https://www.visitjeju.net/kr/detail/view?contentsid=CONT_000000000500343) |
| udo | 우도 해양도립공원 | [비짓제주 500477](https://www.visitjeju.net/kr/detail/view?contentsid=CONT_000000000500477) |
| osulloc | 오설록 티 뮤지엄 | [비짓제주 500457](https://www.visitjeju.net/kr/detail/view?contentsid=CONT_000000000500457) |

원문에서 확인한 키는 `contentsid`, `title`, `contentscd.label`, `region1cd.label`, `region2cd.label`, `roadaddress`, `address`, `latitude`, `longitude`, `phoneno`, `tag`, `introduction`, `usedescinfo`다. 원문 좌표를 그대로 유지했다. 각 HTML의 SHA256을 정규화 자료에 기록했다. 영업시간은 텍스트 참조정보이며 현재 날씨·혼잡도·리뷰 수치와 같은 동적 요소는 추천 지표로 추출하지 않았다.

## UI 데이터 계약

`destinations.json`은 JSON 배열이다. 기본 키는 `id`, `name`, `region`, `region_label`, `category`, `tags`, `description`, `address`, `latitude`, `longitude`, `image`, `source_url`, `source_name`, `image_credit`, `metadata_verified`다. 사진 경로는 `/assets/<id>.jpg`이고 히어로는 `/assets/hero-jeju.jpg`다.

추가 키 `image_source_url`, `image_license_url`, `metadata_source_id`, `metadata_status`, `verified_on`, `requires_ferry`, `requires_access_point`, `route_note`, `popularity`, `classification_note`를 제공한다. `region`은 east west south north 중 하나인 화면 탐색 분류이며 공식 행정구역을 대체하지 않는다. `metadata_verified=true`는 공식 관광지 페이지에서 이름·주소·좌표를 확인했다는 뜻이다. 인기·모델·영업상태를 검증했다는 뜻이 아니다.

한라산은 `requires_access_point=true`다. 공식 대표 좌표를 차량 목적지로 바로 연결하지 않는다. 실제 탐방로 입구를 별도로 확보한 뒤 예약과 통제·입산시간을 검증해야 한다. 우도는 `requires_ferry=true`이며 배편과 운항 조건을 별도 데이터로 확보하기 전 육로 일정에 연결하지 않는다. 다른 지점도 대표 좌표이므로 실제 주차장이나 입구를 보장하지 않는다.

`popularity`는 모든 장소에서 null이다. 사진·공식 등재·웹 소개를 방문량 증거로 사용하지 않는다. 지도와 추천 일정의 교통시간은 별도로 검증한 데이터 또는 추정치 표시가 필요하다.

## 사진과 검증

Wikimedia Commons의 공개 API `imageinfo`로 사진명과 저작자·라이선스를 확인한 뒤 공개 이미지 URL에서 실제 바이트를 다운로드했다. 함덕은 CC0, 우도는 저작자의 공공영역 기증, 천지연과 정방은 CC BY 2.0, 나머지는 CC BY-SA 조건이다. 상세 버전과 원문은 `image_manifest.json` 및 `PHOTO_CREDITS.md`에 개별 기록했다. 사진의 동일조건변경허락은 각 사진 자산에 유지한다.

API에서 너비 1600픽셀 썸네일을 요청했으나 CDN이 실제로 반환한 파일 너비는 1920픽셀이었다. 실제 파일 크기는 Pillow로 확인하여 manifest의 `downloaded_width`, `downloaded_height`에 기록했다. 생성형 편집을 수행하지 않았다. 히어로는 성산 항공 사진의 바이트가 동일한 복사본이다.

사진 10장의 연락시트 `qa_contact_sheet.jpg`를 직접 열어 성산 분화구·협재와 비양도·함덕 해변·한라산 탐방로·천지연·정방·섭지코지 해안·우도·사려니숲 외경·오설록 전경을 확인했다. 연락시트는 내부 검증용이며 서비스 자산으로 필요하지 않다.

재취득은 `download_tourism_assets.py`를 실행하고 웹 UI 정규화와 저작자 문서는 `prepare_ui_assets.py`로 갱신한다. 네트워크 권한이 필요하다. 표준 라이브러리를 사용해 다운로드하며 정규화 과정의 이미지 크기 검증에는 Pillow가 필요하다.
