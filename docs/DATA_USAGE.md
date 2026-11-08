# 데이터 활용 및 외부 자산 명세

기준일2026-11-08. 탐라따라는 아래 공개 자료를 내려받아 로컬 CSV·JSON·SQLite·모델로 사용한다. 화면 조회마다 제주데이터허브에 접속하지 않는다. 출처 URL, 원본 해시와 기준 기간은 함께 보관한다.

## 제주데이터허브 활용11종

허브 상세 주소는 `https://www.jejudatahub.net/data/view/data/자료번호`, 교육부·KERIS 연결 카탈로그 주소는 `https://data.edmgr.kr/dataView.do?id=jejudatahub-net-자료번호`이다.

|자료번호와 이름|활용 항목과 처리|서비스 역할|
|---|---|---|
|1048 업종별 성별 카드 이용 정보|월·업종·집단·이용건수 → 음식8업종의 월별 비중 → 가중 계절Ridge|선택 월·집단의 음식 분야 이용 경향|
|1047 업종별 성별 외식업 이용 정보|월·업종·성별 이용건수 합산 → 실제69개월·94업종 비중 → 계절Ridge|세부 외식업종 탐색|
|1349 VISIT JEJU 여행장소|이름·주소·좌표·분류 → 지도와 정확한 이름 및250m 위치 교차확인|관광 후보68곳의 자격과 허브 표시 이름|
|780 음식점 통합 목록|인허가 이름·주소·상태 → 정리한20,954건과 검색DB|허브 음식점 원문 근거. 좌표는2건만 정확한 이름·전체 주소로 연결|
|189 내국인 관광지 입장객|명소·월·입장객 → 시계열 정리|6개명소의 과거 방문 흐름|
|190 외국인 관광지 입장객|명소·월·입장객 → 내국인 자료와 구분 집계|과거 월별 방문 참고. 현재 혼잡 예측 아님|
|877 2000~2021 제주 일간 기후|4지점·날짜·일평균기온31,900건 → 시간 분리·HGB/분위수 모델|과거 계절 기온과 변동 범위|
|761 VISIT JEJU 축제행사|공개 행사522건 → 꽃6종의 과거 일정28건 검토|선호 기온과 꽃 여행 시기 비교. 개화일 예측 아님|
|871 올레길 위치|공개 미리보기19코스의 거리·시간·위치|걷기 코스 참고|
|858 무장애 여행지 위치|위치120건 → 지역·항목 정리|과거 접근성 자료 참고|
|784 해수욕장 시설|연도별 시설88건 →2023년11해변 비교|해변 시설 비교|

1047·1048 제공처는 제주빅데이터센터, 유통처는 제주데이터허브다. 877은 기상청 생산 자료를 고성빈 게시자가 허브에 공개한 것으로, 센터가 직접 생산했다고 표시하지 않는다. 1349·761은VISIT JEJU, 780은LOCALDATA 계보를 따른다. 관측 기간과 현재 영업·혼잡·개방 여부를 구분한다.

공식 제출 답변: [공개 원본·전처리·DB 제출](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board&postId=b2f27892-3e7e-4df7-b055-d50d529f4741). 출처와 전처리·적재 방법을 함께 기록한다. [제공 데이터 목록 엑셀 및 그 로컬DB는 ZIP동봉 금지](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board&postId=685a3d1d-2d50-48f4-8114-f4aeae6a8075) 대상과 실제 분석한 공개 원본을 구분한다. 이 ZIP에 금지 목록 엑셀이나 전체 허브 데이터셋 카탈로그를 포함하지 않는다.

교육부·KERIS 연결 카탈로그는 위11종을cc-zero로 표시한다. 원허브의 별도 라이선스 필드나 개별 허가증을 확인했다고 주장하지 않으며, 카탈로그 표기와 대회 제출 답변의 범위를 기록한다. 제3자 권리를 센터가 새로 소유한다고 표시하지 않는다.

## 보완 자료와 모델 및 라이브러리

|자료·자산|이용 및 권리 고지|
|---|---|
|공공데이터포털 서귀포 숲길3082951·마을 편의시설15109369|각50건·2,450건을정리. 해당 공개 포털은 이용허락범위 제한 없음 표시|
|OpenStreetMap 장소·식당·도로|© OpenStreetMap contributors, ODbL-1.0. `data_raw/osm/LICENSE_NOTICE.txt`·`LICENSE_TOURISM_ROADS_v5.txt` 및 원본·가공 데이터의 출처와 동일조건 데이터베이스 배포 의무 유지|
|공식 관광 설명|비짓제주59건·한국관광공사3건의 사실을 짧게 재서술. 원문 링크·확인일·사실 영수증 보관. 제공기관 원문 전체나 현재 영업 보증이 아님|
|웹 사진|Wikimedia Commons 원본. 사진별 저작자·CC BY/CC BY-SA/CC0/퍼블릭도메인 조건은PHOTO_CREDITS와웹credits에기록. 사진의조건을프로그램전체라이선스로확대하지않음|
|Leaflet|BSD2-Clause, `ui/vendor/leaflet/LICENSE` 보존|
|multilingual-e5-small|제작자intfloat, MIT 모델카드·고정revision 보존. 제주 질문 추가 학습은 운영 미적용, 생성형 답변 모델 아님|
|Python|PSF 및 포함된 제3자 고지, `runtime/LICENSE.txt` 보존|
|NumPy·tokenizers·ONNX Runtime/DirectML 등|배포버전·의존성 파일 및vendor의dist-info licenses/NOTICE보존. Windows 바이너리를Ubuntu용으로표시하지않음|
|Open-Meteo|선택한공개장소의7일예보API. 비상업무료이용/출처표기조건·CC BY4.0데이터라이선스 준수. 인터넷이없으면예보만실패하고저장자료기능은계속이용|

관련 조건: [OSM 저작권](https://www.openstreetmap.org/copyright), [E5 제작자 모델카드](https://huggingface.co/intfloat/multilingual-e5-small), [Open-Meteo 이용약관](https://open-meteo.com/en/terms), [데이터 라이선스](https://open-meteo.com/en/licence), [상업 이용 안내](https://open-meteo.com/en/pricing).

## AI 활용 범위

런타임은Ridge·HGB·TF-IDF·사전학습E5와규칙기반조정기/준비답변을사용한다. 외부LLM추론API나런타임생성형LLM은사용하지않는다. 개발·코드작성·자료정리·문서편집에는AI개발도구를활용했다. 사용한개발도구명과실제확인가능한모델명은별도AI활용명세에기록하며확인하지못한내부모델명을만들어쓰지않는다.

키·개인인증정보·실제이용자GPS로그는제출하지않는다. 집계카드데이터는개인카드번호와구분하며, 공개음식점·관광지좌표는이용자의현재위치가아니다. 개인정보에접근하는기능은동의절차를거친다.
