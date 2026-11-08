# 제주 길벗 구현 구조와 센터 설치 명세

## 목적과 참여 역할

개인 개발 프로젝트로 공개 자료 수집·전처리, 모델 비교·학습, 화면·서버 구현, 검증과 문서 작성을 수행했다. 도민과 관광객이 장소의 근거·위치를 확인하고 음식 분야와 여행 시기를 살펴본 뒤 출발·복귀 조건에 맞는 하루 코스를 고르는 것이 목표다. 기관 협약·실제 센터 시험·현장 만족도 조사 실적을 주장하지 않는다.

## 실행 구조와 Agent 판단 범위

```text
브라우저 화면 ui/
  → 같은 PC의127.0.0.1 Python서버 center_app.py / jeju_agent/server.py
    → 조건·출발 확인 planning_input.py
    → 공개 관광 후보·공식 소개 검색 tourism_access.py / assistant_search.py
    → 장소 자격·자료 해시 검사 place_trust.py
    → 일정·복귀 조건 계산 orchestrator.py
    → 저장 도로의 거리·경로 roads.py
  ← 일정·지도·설명·출처·제약을 JSON으로 반환
```

통합 Agent는 정해진 도구를 순서대로 조정한다. 후보 선택·제한 탐색·조건 검사를 수행하지만 LLM이 임의로 도구를 고르거나 새 웹 사실을 만들어내지 않는다. 불명확한 출발과 미확인 장소는 확인 요청·제외 사유로 안내한다. 일정 조건을 조용히 완화하지 않는다. 예약·결제·메시지 발송·실시간 교통·센터 DB 직접 접속은 포함하지 않는다.

일반 상담은 `jeju_agent/chatbot.py`의 규칙·후속 질문과 `config/chatbot_faq.json`, `data_reference/chatbot.sqlite`의 준비 설명을 쓴다. 독립적인 수만 개 수작업 FAQ나 자유 생성형 챗봇이라고 설명하지 않는다. LLM프롬프트는 해당 없으며 `prompts/RUNTIME_RULES.md`는 코드의 처리 규칙을 설명한 문서다.

## 모델과 데이터의 연결

|기능|사용 자료와 변환|모델·도구|화면에서의 의미|
|---|---|---|---|
|음식 분야 비중|허브1048의월·집단·업종·이용건수→비중표|가중 pooled seasonal trend Ridge, `models_candidates_v23/audience`|선택 월·집단의8업종 경향|
|세부 외식 비중|허브1047의성별합산→69개월94업종 비중|가중 계절 Ridge, `models_dining`|업종 탐색 참고값|
|과거 계절 기온|허브877의4지점·날짜→10개입력과일평균기온|HGB·분위수회귀, `models_climate`|과거 대표 기온과 변동 범위|
|공식 관광 소개|확인한62개 소개→단어/문장표현|기본TF-IDF와선택형multilingual-e5-small|기존 설명·출처 검색|
|꽃 여행 시기|허브761의꽃6종28일정+기온모델|선호기온비교규칙|과거일정이있던월최대3개비교|
|자동 코스|자격확인40관광지·출발/복귀조건·도로|제한탐색·조건재검사·A*도로탐색|이동거리·시간추정과지도경로|
|방문 흐름|허브189·190의6명소관측|저장 집계 조회|과거월별방문참고|

학습·추론·관측 집계·규칙을 구분한다. 식당 맛·현재 인기도·현재 혼잡·실제 인기 이동 순서 학습은 아니다. 허브 이름을 지도 이름보다 우선하며 원래 근거는 보존한다. 데이터 전처리·출처·기간·이용조건은 [DATA_USAGE.md](DATA_USAGE.md), 모델 선택·평가와 원본 흐름은 기획서와 [REPRODUCTION.md](REPRODUCTION.md)를 따른다.

## 센터 설치 담당자에게 알릴 항목

공식 게시판의 센터 기준은 Windows11·i7-8700·GTX1060 VRAM3GB·RAM32GB, Chrome/Edge, FHD다. 로컬 서버 실행과 추가 패키지 설치가 허용되지만 설치 항목을 미리 명시해야 한다. 다음 항목을 설치·실행 명세로 제공한다.

|환경|필요 항목|준비 방식|
|---|---|---|
|Windows11x64|Python3.13|공식 Windows내장배포를 `runtime`에 동봉, 시스템Python변경없음|
|Windows E5 CPU|NumPy2.3.5·tokenizers0.22.2·ONNX Runtime1.31.1 및 해당 의존성|`vendor/semantic`의CP313Windows배포본 동봉|
|Windows GPU 선택|동봉 ONNX Runtime DirectML배포본·WindowsDirectX12 호환 GPU드라이버|`vendor/semantic_gpu`, `run_center_gpu.cmd`. CUDA/PyTorch설치불필요|
|Windows DLL준비|Microsoft Visual C++ v14 x64 런타임|이미있으면재설치불필요. 없는PC는담당자가Microsoft공식배포에따라설치|
|Ubuntu추가지원|Ubuntu24.04LTSx86_64·Python3.12|운영체제Python사용,프로젝트내venv 생성|
|Ubuntu E5 CPU|NumPy2.3.5·tokenizers0.22.2·ONNX Runtime1.31.1 등21wheel+pip|동봉해시고정오프라인설치. WindowsDLL사용안함|
|브라우저|Chrome/Edge, Ubuntu의호환브라우저|주소는같은PC의 `http://127.0.0.1:8765/`|

전체 라이브러리 버전·라이선스와 동봉 고지는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), Linux 설치 고정값은 `requirements/linux-cpu.lock.txt`와 wheel/bootstrap manifest다. Windows ONNX의 VisualC++ 요구는 [ONNX Runtime 공식설치문서](https://onnxruntime.ai/docs/install/), 다운로드는 [Microsoft 공식재배포안내](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/)에서 확인한다. 이 제출 작업이 담당자 대신 런타임·GPU드라이버를 시스템에 설치하거나 약관을 승인하지 않았다.

Ubuntu는 같은 E5의INT8CPU를 사용한다. GPU기본여부·레이어·메모리예산을 이용해 모델 정답률이 높아졌다고 주장하지 않는다. 기본WindowsCPU와선택GPU는유지했고, LinuxCPU import경로·프로세스RSS진단만추가했다. 설치와실행명령은루트README를따른다.

## 외부 주소와 의존성

|주소|언제 사용|전송 내용·대체|
|---|---|---|
|`https://api.open-meteo.com/v1/forecast`|이용자가7일예보버튼선택|미리확인한공개장소좌표. 사용자GPS·파일을보내지않음. 실패시과거자료유지|
|`https://tile.openstreetmap.org/{z}/{x}/{y}.png`|온라인지도전환|지도타일좌표. 실패시오프라인도로·위치참고도|
|`https://pypi.org/simple`, `https://files.pythonhosted.org/`|Linux3.11/3.13온라인설치를명시선택|패키지요청. CP312동봉오프라인설치로대체가능|
|`https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/`, `https://aka.ms/vc14/vc_redist.x64.exe`|Windows VC런타임이없는경우담당자수동준비|Microsoft공식안내/설치파일. 앱이자동설치하지않음|
|`https://www.jejudatahub.net/`, `https://www.data.go.kr/`|원문버튼또는선택자료의개발수집재현|출처확인·공개자료. 일반로컬검색마다요청하지않음|
|`https://www.visitjeju.net/kr/`, `https://korean.visitkorea.or.kr/`|공식설명원문링크|이용자의브라우저선택. 확보시점의로컬소개유지|
|`https://www.openstreetmap.org/`, `https://opendatacommons.org/`|지도원문·주소검색·라이선스링크|선택적외부브라우저접속|
|`https://huggingface.co/intfloat/multilingual-e5-small`|개발재현·모델출처확인|학습자료/모델정체성확인. 일반실행중다운로드없음|

선택된장소의공식홈페이지버튼은각자료에기록된주소로이동할수있다. 설치자료외추가외부주소도데이터원문에명시한다. 센터의DLP·리다이렉트·주소차단정책은별도로적용되며접속을보장하지않는다. 프로그램은외부API를못받은경우새사실을대신생성하지않는다.

## 데이터 보안과 센터 이용

기본 탑재 자료는 공개 허브 원본·파생자료다. 대회 제공 전체 데이터 목록 엑셀이나 그 내용을 복제한DB는 포함하지 않았다. `catalog.sqlite`는 실제관광장소·음식점명부DB다. 센터 전용 자료를Agent가직접API/DB로가져오는기능은없다.

1048 CSV 체험은 브라우저 탭 안에서만 처리하며 서버전송·재학습에쓰지않는다. 이용자자료의영구보존·외부전송·반출을자동으로승인하지않는다. 센터의이용·삭제·반출절차를따른다. GPS는명시적동의·권한후사용하고직접출발지선택도제공한다. 실제사용자의GPS권한은자동시험하지않았다.

## 개발 AI 도구와 범위

코드·문서작성과검토에OpenAI Codex 등생성형AI개발도구를사용했다. 런타임에는로컬회귀·검색·규칙·도구조정을사용하며유료LLM호출·외부추론·실시간재학습은없다. 외부코드/데이터/사진/모델의명세와라이선스를같이제공한다. 비LLM Agent에대한운영진의개별승인을받았다고표현하지않는다.
