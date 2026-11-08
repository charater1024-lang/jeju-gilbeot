# 탐라따라 최종 제출 패키지

제주 공개 데이터로 장소·먹거리·여행 시기를 살펴보고, 출발지와 복귀 시간에 맞춰 하루 코스를 만드는 로컬 웹 서비스입니다. 센터 PC에서 서버를 실행하고 같은 PC의 브라우저로 사용합니다. 런타임 LLM·유료 AI 계정·API 인증키가 필요하지 않습니다.

기획서는 `docs/탐라따라_최종기획서.pdf`, 데이터별 출처·전처리·조건은 `docs/DATA_USAGE.md`, 구조·설치 요구사항·외부 주소는 `docs/IMPLEMENTATION.md`, 검증 범위는 `docs/VALIDATION.md`, 학습·변환·평가 원본과 연구 재현은 [REPRODUCTION.md](docs/REPRODUCTION.md)에 있습니다.

## 빠른 시작

ZIP 전체를 새 폴더에 풀고, 그 안의 `tamra_ttara` 폴더를 기준으로 실행합니다. 표의 명령은 해당 폴더에서 실행하세요. 동봉 데이터와 학습·변환된 모델을 바로 사용하므로 **서비스 실행을 위한 재다운로드·재학습은 필요하지 않습니다.**

|운영체제|처음 한 번|다음 실행|접속·종료|
|---|---|---|---|
|Windows11 x64|전체 압축 해제 후 `run_center.cmd` 두 번 클릭|`run_center.cmd` 두 번 클릭|`http://127.0.0.1:8765/` · 실행창에서 `Ctrl+C`|
|Ubuntu24.04 LTS x86_64 / Python3.12|`bash setup_ubuntu.sh` 후 `bash run_center.sh`|`bash run_center.sh`|같은 주소 · 실행 터미널에서 `Ctrl+C`|

Ubuntu 최초 설치와 실행을 한 번에 하려면 `bash setup_ubuntu.sh && bash run_center.sh`를 사용합니다. 설치가 성공해야 서버가 시작됩니다. Windows 기본 실행에는 별도 Python·Node·CUDA 설치가 필요하지 않으며, Ubuntu 사전 준비와 선택 GPU 실행은 아래 운영체제별 안내를 따릅니다. 해시 검사와 재현 확인 명령은 **6 진단과 문제 해결**에 있습니다.

## 1 설치 환경

게시판 공식 답변의 센터 환경은 **Windows11 / i7-8700 / GTX1060 VRAM3072MB / RAM32GB / Chrome·Edge /1920×1080**입니다. Ubuntu는 **24.04 LTS x86_64 / Python3.12**를 추가 지원합니다. 현재 개발 PC의 시험 결과를 센터 실측으로 대신하지 않습니다.

- [OS·설치에 관한 공식 답변](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board&postId=3d8a1ba3-d0d8-4667-9e0e-b6d5d671e6d5)
- [VRAM·CSV에 관한 공식 답변](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board&postId=bf483331-0a71-4f92-b061-570b12b31fa8)

ZIP 전체를 먼저 압축 해제한 뒤 `tamra_ttara` 폴더를 사용하세요. ZIP 안에서 실행하거나 실행 파일만 옮기면 자료를 찾지 못합니다. `config`, `data*`, `models*`, `ui`, `vendor`의 상대 위치를 유지합니다. 설치·압축 해제용 디스크 공간을 여유 있게 확보하고 실제 파일 크기는 `SUBMISSION_MANIFEST.json`을 확인하세요. Ubuntu는 사용할 위치에 압축을 푼 뒤 가상환경을 만듭니다.

압축 해제된 배포 파일은 약 **1.04GiB**입니다. ZIP 원본을 보관할 공간과 압축 해제 작업 공간이 따로 필요하며, Ubuntu는 `.venv-linux`와 Linux 추론 패키지 설치 공간도 추가로 필요합니다. 공간이 부족한 저장소에서는 설치하지 말고, 압축 해제·설치가 끝날 때까지 여유 공간을 확보하세요.

## 2 Windows 실행

1. `run_center.cmd`를 두 번 클릭합니다. 또는 프로젝트 폴더의 PowerShell에서 아래 명령을 실행합니다.
2. 브라우저가 열리지 않으면 `http://127.0.0.1:8765/`에 접속합니다.
3. 실행창을 열어 둔 상태로 사용합니다. 종료는 그 창에서 `Ctrl+C`입니다.

```powershell
.\run_center.cmd
```

기본은 CPU입니다. 공식 Python3.13 Windows x64 런타임과 해당 버전 추론 패키지를 동봉했으므로 별도 Python·pip 설치, 로그인, 재학습 없이 실행합니다. 시스템 Python은 변경하지 않습니다. ONNX Runtime에 필요한 Microsoft Visual C++ 런타임이 없는 PC에서 `DLL load failed`·`MSVCP140` 오류가 나면 담당자가 [Microsoft 공식 x64 재배포 패키지](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/)를 설치한 뒤 재실행합니다. 관련 설치 항목을 `docs/IMPLEMENTATION.md`에 명시했습니다.

### 선택형 GPU와 포트 변경

```powershell
# Windows DirectML GPU를 선택적으로 사용
.\run_center_gpu.cmd

# 브라우저 자동 열기 생략 또는 다른 포트 사용
.\run_center.cmd --no-browser --port 8790
```

GPU 모드는 E5 검색 모델1개를 상주시킵니다. 작은 회귀·기온·규칙 계산과 일정 탐색은 CPU이며, 도로 최근접 노드만 선택적으로 가속합니다. CUDA·PyTorch 설치는 요구하지 않습니다. GPU 준비에 실패하면 CPU로 대체할 수 있으므로 실제 `gpu_ready`, `gpu_resident`, provider를 확인합니다. 포트를8790으로 바꾸면 `http://127.0.0.1:8790/`에 접속합니다.

이 서버는 같은 PC의 `127.0.0.1`에서만 접속을 받습니다. 다른 PC에 공개하는 웹 호스팅 구성은 포함하지 않습니다.

## 3 Ubuntu 설치와 실행

Ubuntu24.04 x86_64의 Python3.12를 기준으로 합니다. Windows의 `runtime/python.exe`와 `vendor/semantic` DLL을 Linux에서 사용하지 않습니다. Ubuntu는 **동일 E5 INT8 CPU·도로CPU**로 실행합니다.

프로젝트 폴더에서 터미널을 열어 실행합니다.

```bash
python3 --version
bash setup_ubuntu.sh
bash run_center.sh
```

브라우저에서 `http://127.0.0.1:8765/`를 엽니다. 종료는 실행 터미널의 `Ctrl+C`입니다. ZIP의 실행 권한이 보존되지 않아도 `bash`로 실행할 수 있습니다. Python이 없는 PC는 담당자가 Ubuntu 저장소의 `python3`, 필요시 `python3-venv`를 먼저 설치합니다. 이 사전 준비에만 저장소 연결·관리 권한이 필요할 수 있습니다.

```bash
# Python이 없거나 venv 모듈이 준비되지 않은 Ubuntu에서만 담당자가 실행
sudo apt update
sudo apt install python3 python3-venv
```

Ubuntu에서 브라우저는 열리지만 한글이 네모로 보이면 담당자가 `fonts-noto-cjk` 같은 한글 폰트를 준비합니다. 이 패키지는 브라우저·시스템 글꼴을 설치하거나 변경하지 않습니다.

설치기는 프로젝트의 `.venv-linux`를 만들고 동봉 pip와 **SHA256 고정 Linux wheel21개**로 `vendor/semantic_linux/cp312`에 설치합니다. pip까지22개 파일의 해시를 검사하며 전역 pip·시스템 패키지를 덮어쓰지 않습니다. Python3.12 오프라인 경로는 PyPI·허브·Hugging Face에 접속하지 않고, 실행 때 모델을 다시 내려받지 않습니다.

```bash
# 설치된 버전과 import 경로 확인
bash setup_ubuntu.sh --verify-only

# 포트 변경 또는 브라우저 자동 열기 생략
bash run_center.sh --no-browser --port 8790
```

Ubuntu22.04의 기본 Python3.10은 E5 전체 설치 대상이 아닙니다. 전체 기능의 기본 지원 조합은 Ubuntu24.04/Python3.12입니다. Python3.11 또는3.13이 별도로 준비된 Linux x86_64는 같은 버전 고정 파일로 온라인 설치를 선택할 수 있습니다.

```bash
JEJU_PYTHON=python3.11 bash setup_ubuntu.sh --online
JEJU_PYTHON=python3.11 bash run_center.sh
```

온라인 설치에는 PyPI 연결이 필요합니다. 다른 아키텍처 전체에 대한 지원을 뜻하지 않습니다. Python 버전이 다른 `.venv-linux`가 있거나 설치 폴더를 옮겨 문제가 생기면 새 위치에 ZIP을 다시 풀어 설치합니다. Ubuntu에서 GPU 옵션을 요청해도 Windows DirectML DLL을 가져오지 않고 CPU를 사용합니다.

## 4 사용자 매뉴얼

### 관광지 찾기와 장소 설명

첫 화면에서 **제주 둘러보기**(`/explore`)를 열고 북부·동부·서부·남부, 검색어·테마를 고릅니다. 지도 표시나 목록을 선택하면 이름·위치·공식 설명·출처를 봅니다. 묶인 표시에는 여러 장소 목록이 나타나며 각각 선택할 수 있습니다. **장소 자세히**에서 설명을 읽고 **내 여행에 담기**를 누릅니다.

관광 후보는 허브 명부와 지도의 이름·좌표·분류를 교차 확인한68곳이며 공식 소개62건, 자동 코스 대상40곳은 서로 다른 범위입니다. 음식점은 별도 인허가 명부입니다. 좌표를 확인한2건 외에는 임의 위치를 붙이지 않으므로 이름·주소 검색 결과가 모두 거리 지도에 표시되지는 않습니다.

### 위치 동의 또는 직접 출발지 선택

**내 위치 사용**을 누르면 서비스 동의 후 브라우저 위치 권한을 요청합니다. OS·브라우저가 위치를 제공해야 합니다. 권한을 자동 허용하거나 사용자 GPS를 자동 시험하지 않습니다. 권한 거절·위치 오류·센터 PC의 위치 미제공 시 지역이나 제주공항 같은 공개 장소를 직접 고릅니다. 출발 기준을 **선택하고 확인**한 뒤 코스를 만드세요. 출발 조건이 달라지면 다시 확인합니다.

### 하루 자동 코스와 지도 경로

1. **내 여행**(`/planner`)에서 자동 코스 만들기를 선택합니다.
2. 출발·복귀 지점을 확인합니다.
3. 날짜, 출발·복귀 시간, 이동 수단, 예산, 방문 수, 지역·테마를 입력합니다.
4. 계산 버튼을 눌러 방문 순서·체류·이동 추정·복귀 시간을 봅니다.
5. 지도 경로와 장소별 근거를 읽고 조건 변경 시 다시 계산합니다.

예시: 제주공항을 공개 출발지로 고르고 북부·자동차·09:00~18:00·3곳을 요청합니다. 실제 결과는 자료와 자격 조건에 따라 달라집니다. 사용자가 고른 조건을 조용히 버리거나 확인하지 못한 장소를 대신 확정하지 않습니다.

경로는 저장 도로 거리와 가정 속도에 따른 추정입니다. 실시간 교통, 현재 영업·입구·요금, 실제 인기 이동 순서 학습은 포함하지 않습니다. 음식점도 관광 자동 코스에 임의 편입하지 않고 별도 검색·수동 참고 범위를 따릅니다.

**오프라인 위치 참고도**는 저장된 제주 위치·도로를 사용합니다. 일정을 만들면 경로 선과 장소 순서를 확인할 수 있습니다. 온라인 지도 전환은 OpenStreetMap 타일을 가져오고 연결 실패 시 오프라인 지도로 돌아옵니다. 실시간 내비게이션은 아닙니다.

### 음식 경향과 식당 탐색

음식·데이터 안내에서 월·집단 또는 세부 외식업종을 선택합니다. 허브1048·1047을 학습한 Ridge가 업종별 이용 비중을 보여주며 관심 업종에서 식당 검색으로 이어집니다. 이 값은 개별 식당의 맛·평점·현재 인기도나 개인 만족도 예측이 아닙니다.

### 공식 소개 검색과 탐라따라 상담

공식 소개는 기본 TF-IDF 단어 검색으로 찾습니다. 의미 검색을 선택하면 공개 사전학습 E5로 같은 설명을 찾습니다. 예: **아이와 바다를 산책하고 싶어요**. 관련도·범위가 맞지 않으면 빈 결과가 나올 수 있으므로 장소명·지역·다른 표현으로 다시 찾습니다.

**탐라따라 상담**은 규칙·준비 답변을 사용합니다. 버튼을 다시 누르거나 닫기 버튼을 누르면 닫힙니다. “내 주변 관광지”처럼 위치가 필요한 요청만 동의를 받고, 지역·장소명 검색은 위치 없이 이용할 수 있습니다. 모든 자유 문장을 이해하는 LLM 챗봇은 아닙니다.

### 기온과 꽃 여행 시기

**계절 기온**(`/climate`)에서 지역·월·일을 고르면 허브877의 HGB·분위수 모델로 과거 계절 기온과 범위를 봅니다. **꽃과 계절**(`/flowers`)은 꽃·지역·선호 기온에 맞춰 과거 꽃 행사 일정이 있던 월을 비교합니다.

**7일 예보 조회**를 누르면 공개 기준 장소의 Open-Meteo 예보를 가져옵니다. 개인 GPS는 보내지 않습니다. 과거 기온·꽃 일정과 최신 예보를 구분하며 꽃 개화일·만발일 예측은 포함하지 않습니다.

### 방문 흐름과 CSV 체험

`/insights`는6개 명소의 과거 월별 입장객을 보여줍니다. 현재 혼잡 예측은 아닙니다. 지역 소비패턴 비교와 승차 예측은 운영에서 제외했습니다.

1048 CSV 체험은 `base_year_month,biz_nm,user_type,sex,use_count` 열을 가진8MiB 이하 UTF-8 또는 한글 CSV를 탭 안에서 집계합니다. 파일을 서버로 올리거나 재학습에 쓰지 않습니다. 센터 전용CSV 모든 형식의 범용 업로드 기능은 아닙니다. 이용자 자료·결과 보존과 반출은 센터 승인 절차를 따릅니다.

## 5 인터넷과 환경변수

핵심 검색·회귀·기온·꽃 비교·규칙상담·자동 일정·오프라인 지도는 동봉 자료와 모델로 실행합니다. 외부 연결은 다음과 같습니다.

|상황|외부 주소|연결 실패 시|
|---|---|---|
|온라인 지도 전환|`https://tile.openstreetmap.org/{z}/{x}/{y}.png`|오프라인 지도|
|7일 예보 버튼|`https://api.open-meteo.com/v1/forecast`|저장 기온·꽃 비교|
|Linux3.11/3.13 온라인 설치|`pypi.org`, `files.pythonhosted.org`|Python3.12 동봉 오프라인 설치|
|원문 링크 선택|허브·비짓제주·한국관광공사·공공데이터포털 등|확보 시점의 로컬 설명|

센터DLP·외부 주소 정책이 적용될 수 있어 `docs/IMPLEMENTATION.md`에 주소·용도를 명시했습니다. 핵심 동작에서 외부 LLM 추론·이용자 파일 외부 전송·센터 DB 직접 접속을 하지 않습니다.

`.env.example`은 안내 예시이며 자동으로 읽지 않습니다. 예보 기능을 끄려면 실행 전 환경변수를 설정합니다.

```powershell
$env:JEJU_FLOWER_WEATHER_API='0'
.\run_center.cmd
```

```bash
JEJU_FLOWER_WEATHER_API=0 bash run_center.sh
```

## 6 진단과 문제 해결

`http://127.0.0.1:8765/api/status`, `/api/operational-check`, `/api/compute-status`에서 준비 상태를 봅니다. 정상 CPU 모드도 올바른 실행입니다. E5 전체 기능 확인은 `preload.status=ready`, CPU/DML provider와 실제 의미 검색을 함께 확인합니다. `gpu_ready:false`만으로 전체 실패를 뜻하지 않습니다.

### 배포 파일과 Python 회귀 검사

압축 해제 후 서버를 실행하기 전에 파일 해시를 확인합니다. 서버가 이미 실행 중이면 해당 실행창에서 `Ctrl+C`로 종료한 뒤 검사하세요. 모든 명령의 작업 위치는 `tamra_ttara` 폴더입니다. 검사는 제출 파일을 재학습하거나 복구 다운로드로 덮어쓰지 않습니다.

Windows PowerShell:

```powershell
# 동봉 파일 크기·SHA256 확인
.\runtime\python.exe .\scripts\verify_submission.py

# Python 기능 회귀 검사
.\runtime\python.exe .\dev.py test --python-only
```

Ubuntu 설치 후 터미널:

```bash
# 최초 설치 후 런타임 import 확인
bash setup_ubuntu.sh --verify-only

# 동봉 파일 크기·SHA256 확인
.venv-linux/bin/python scripts/verify_submission.py

# Python 기능 회귀 검사
.venv-linux/bin/python dev.py test --python-only
```

해시 검사 결과의 `"pass": true`, `"failures": []`를 확인합니다. `checked_files`는 현재 `SUBMISSION_MANIFEST.json`에 기록된 배포 파일 수입니다. 설치 과정에서 생긴 Linux 가상환경·추가 설치 파일과 브라우저 자료는 이 정적 명세의 검사 대상이 아닙니다. 실패 목록이 있으면 해당 파일을 임의로 고치지 말고 원래 제출 ZIP을 새 폴더에 다시 풉니다.

Python 회귀 결과는 **448개 수집 중 현재 범위 426개 실행, 과거 실험 22개 명시적 건너뜀(skip)**으로 구분합니다. 마지막 JSON의 `python.pass=true`, `tests=448`, `executed=426`, `skipped_historical=22`를 확인합니다. 제외 사유는 `tests/release_scope.json`에 있습니다. `--python-only`의 `ui.status=not_run`은 UI 검사를 요청하지 않았다는 뜻이며 Python 검사 실패가 아닙니다. 이 회귀 검사는 추천 정확도나 센터 기기의 처리 성능을 다시 측정하는 검사가 아닙니다.

Node는 **개발자용 UI 검사에만 필요한 선택 의존성**이며, 서비스 실행이나 위 Python 회귀 검사에는 필요하지 않습니다. Node를 별도로 준비한 경우에만 다음 명령으로 Python 검사와 Node 기반 UI 검사를 함께 실행합니다. Windows 경로는 실제 설치 위치로 바꿉니다.

```powershell
.\runtime\python.exe .\dev.py test --node "C:\실제Node경로\node.exe"
```

```bash
.venv-linux/bin/python dev.py test --node "$(command -v node)"
```

UI 검사는 DOM 모의 동작과 JavaScript 문법 검사입니다. 브라우저 위치 권한 팝업·실제 GPS 수신을 자동으로 시험하거나 허용하지 않습니다. 세부 검증 범위와 고정된 과거 모델 평가 결과는 [VALIDATION.md](docs/VALIDATION.md)를 참고하세요.

### 공개 출발지로 확인하는 약 5분 시나리오

1. 운영체제별 실행 도구로 서버를 시작하고 `http://127.0.0.1:8765/`를 엽니다. 포트를 바꿨다면 주소도 같은 포트로 바꿉니다.
2. **제주 둘러보기**(`/explore`)에서 북부를 선택하고 지도 또는 목록의 장소를 엽니다. 이름·설명·출처와 **장소 자세히**가 표시되는지 확인합니다.
3. **내 여행**(`/planner`)의 **직접 조건 입력 · 담은 장소로 일정 만들기**를 펼치고, **일정 만드는 방법 → 조건에 맞는 코스 추천**을 선택합니다. **제주공항 출발로 확인**을 누른 뒤 북부·차로 여유롭게·09:00~18:00·3곳과 여행 날짜를 입력해 코스를 요청합니다. GPS 권한은 필요하지 않습니다. 장소 순서·이동 추정·복귀 시간과 오프라인 지도 경로가 표시되는지 봅니다. 결과가 없으면 표시된 이유를 읽고 지역·방문 수·복귀 조건을 조정합니다.
4. 공식 소개의 **의미 검색**에서 `오랜 나무 그늘과 화산송이 길을 따라 걷는 숲`을 검색하고 결과의 설명·출처를 확인합니다. `/api/compute-status`의 `preload.status=ready`와 실제 CPU 또는 DML provider도 확인합니다. GPU가 없는 CPU 모드에서도 의미 검색은 사용할 수 있습니다.
5. **탐라따라 상담**에서 `성산일출봉`처럼 위치가 필요 없는 장소 안내를 요청합니다. 상담 버튼을 다시 눌러 닫히는지 확인하고, 실행창에서 `Ctrl+C`로 서버를 종료합니다.

이 시나리오는 개인 위치 권한 없이 핵심 동작을 확인하는 방법입니다. 실제 GPS 사용은 이용자가 **내 위치 사용**을 선택하고 서비스 동의와 OS·브라우저 권한을 허용했을 때만 별도로 확인합니다. 7일 예보와 온라인 지도는 외부 연결이 필요한 선택 기능입니다.

|증상|조치|
|---|---|
|브라우저가 안 열림|실행창의 `Local UI` 주소를 직접 엽니다.|
|포트 사용 중|기존 실행창에서Ctrl+C 후 재실행하거나 `--port 8790`으로 변경합니다.|
|자료·모델 없음|ZIP 전체를 새 폴더에 풀고 `config/data*/models*/ui/vendor` 상대 위치를 확인합니다.|
|Windows DLL 오류|동봉runtime·vendor를 유지하고 Microsoft x64 Visual C++ 런타임을 담당자가 준비합니다.|
|Ubuntu 의미 검색 준비 안 됨|Python3.12 확인 후 `bash setup_ubuntu.sh`, `--verify-only`를 실행합니다.|
|wheel 해시 오류|누락·손상된 ZIP일 수 있으므로 새 폴더에 다시 압축 해제합니다.|
|위치 팝업이 안 뜸|localhost 사이트 권한·OS 위치 기능을 확인하고, 제공이 안 되면 공개 출발지를 직접 선택합니다.|
|지도·날씨 연결 실패|인터넷·센터 주소 정책을 확인하고 오프라인 지도·저장 자료를 사용합니다.|
|검색·코스 결과 없음|지역·필터·방문 수·체류·복귀 조건을 조정하고 출발지를 다시 확인합니다.|

무결성 검사·회귀 시험 명령과 실제 결과는 `docs/VALIDATION.md`를 따릅니다. 현재 기능 검사와 자료가 남아 있지 않은 옛 실험 재현 검사를 구분합니다. 처리 성공·형식 검사는 추천 정답률100%나 센터 실측을 뜻하지 않습니다.

### 종료·이동·다시 설치

브라우저 탭만 닫으면 서버는 계속 실행됩니다. 실행한 콘솔 또는 터미널에서 `Ctrl+C`로 종료하고 다음 실행 때 같은 런처를 사용합니다. 포트 충돌 시 기존 실행창을 먼저 확인하며, 다른 프로그램을 임의 종료하는 대신 `--port 8790`으로 실행할 수도 있습니다.

다른 PC나 폴더로 옮길 때에는 서버를 종료하고 **원래 제출 ZIP 전체를 새 위치에 압축 해제**합니다. Windows는 `run_center.cmd`로 실행합니다. Ubuntu의 `.venv-linux`는 경로에 의존하므로 설치된 폴더를 그대로 재사용하지 말고 새 위치에서 `bash setup_ubuntu.sh`를 다시 실행합니다. 데이터·모델만 따로 옮기거나 기존 가상환경에 덮어쓰지 않습니다.

최종 제출본에서는 `dev.py restore`나 과거 Git 복구 도구를 실행하지 않습니다. 모든 운영 자료·모델을 동봉했으며, 복구는 원래 ZIP 재압축 해제로 진행합니다. 학습·변환 과정을 검토하거나 다시 연구하려면 서비스 실행과 구분하여 [REPRODUCTION.md](docs/REPRODUCTION.md)의 **별도 연구 복사본** 절차를 따릅니다.

## 7 구성과 AI 사용 공개

`jeju_agent/`는 서비스·통합 도구 조정, `ui/`는 화면, `config/`는 출처·검증 정책, `data*`는 공개 원본·가공 자료, `models*`는 모델·학습 계보, `scripts/tests`는 처리·학습·검증, `runtime/vendor/requirements/tools/wheelhouse`는 실행 의존성입니다. `SUBMISSION_MANIFEST.json`에 배포 파일의 크기·SHA256을 기록합니다.

음식 모델은 가중 계절 Ridge 계열, 기온은 HGB·분위수 회귀, 검색은 TF-IDF·multilingual-e5-small입니다. 운영 E5는 공개 사전학습 모델로 제주 질문을 추가 학습하지 않았습니다. 통합 Agent는 출발 확인·장소 검증·일정 계산·검사를 순서대로 연결합니다. 자율 도구 선택이나 런타임 LLM은 없습니다. 준비 답변과 규칙·템플릿 위치를 `docs/IMPLEMENTATION.md`에 명시했고 LLM 프롬프트는 해당 없음입니다.

개발 과정에서는 OpenAI Codex 등 생성형 AI 개발 도구를 코드·문서 작성·검토에 사용했습니다. 이용자의 질문·파일을 외부 LLM으로 전송하는 기능과 구분합니다. 데이터·사진·모델·라이브러리별 조건과 출처는 `docs/THIRD_PARTY_NOTICES.md`, `docs/PHOTO_CREDITS.md`, `docs/DATA_USAGE.md`를 따릅니다.

대회 제공 데이터 목록 엑셀·그 전체 목록을 옮긴DB, 개인 키·Git정보·로그·옛 ZIP은 포함하지 않았습니다. `data_reference/catalog.sqlite`는 실제 관광지·음식점DB이며 대회 전체 데이터 목록DB가 아닙니다.

## 8 제출 안내

대회 **갤러리 → 기획서 및 최종 결과물 제출**에서 PDF와 ZIP을 선택합니다. 마감은 공식 안내 기준 **2026년11월20일10:00 한국시간**입니다. 이 파일 생성 작업은 사이트 업로드·최종 제출을 수행하지 않았으며, 제출 시 최신 화면 안내를 따릅니다. 원본 개발 폴더는 제출 패키지와 별도로 보존했습니다.
