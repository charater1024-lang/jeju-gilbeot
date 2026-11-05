# 제주 길벗 다른 노트북에서 시작하기

이 폴더에는 2026년 10월 31일 기준 앱 v13, 원본 데이터, 학습 모델, 검증 자료, 최신 15페이지 기획서와 Codex 인계 문서가 있다. 기존 실행 ZIP과 달리 재학습 원본 CSV도 포함한 개인 개발 이전용 전체 패키지다.

## Windows에서 시작

1. ZIP 전체를 로컬 폴더에 압축 해제한다. ZIP 내부에서 직접 실행하지 않는다.
2. Codex에서 `AGENTS.md`가 있는 이 폴더를 프로젝트로 연다.
3. `check_transfer.cmd`로 파일 무결성을 확인한다.
4. `run_center.cmd`를 실행한다. 브라우저 주소는 http://127.0.0.1:8765/ 이다.
5. `CODEX_START_PROMPT.md`의 시작 문구를 새 Codex에 전달한다.

Windows x64 Python 3.13.17과 표준 라이브러리가 포함돼 있어 앱 실행에 Python/pip/API 키를 별도 설치할 필요가 없다. 처음 Windows가 실행 확인을 요구하면 파일 출처와 검증 결과를 직접 확인한다. 8765 포트를 다른 프로그램이 쓰면 다음처럼 별도 포트를 지정한다.

```powershell
.\runtime\python.exe .\center_app.py --port 8780
```

실행 중 종료는 서버 터미널에서 Ctrl+C로 한다. 설치된 다른 프로그램이나 기존 서버를 일괄 종료하지 않는다.

## 개발용 검증

```powershell
.\runtime\python.exe .\dev.py check
.\runtime\python.exe .\dev.py test
```

`test`는 Python 전체 테스트와 `tests/ui_*.cjs`를 실행한다. Node는 PATH 또는 새 노트북의 Codex 런타임에서 찾는다. Node를 찾지 못하면 종료코드 2와 함께 UI 테스트 미실행을 안내한다. 새 Codex에서 workspace dependency 경로를 확인한 뒤 지정할 수 있다.

```powershell
.\runtime\python.exe .\dev.py test --node "새 노트북의 node.exe 절대경로"
.\runtime\python.exe .\dev.py test --python-only
```

`--python-only`는 의도적으로 Python 검사만 실행하는 옵션이다. 문서 제작 도구의 `python-docx`와 Word는 앱 실행 필수가 아니다. 기획서 재편집 시 새 Codex의 문서 스킬과 workspace dependencies를 사용한다.

## Mac 또는 Linux

동봉된 실행 런타임은 Windows x64용이다. 다른 운영체제에서는 Python 3.10 이상과 필요 시 Node를 별도 준비한 뒤 다음 명령을 사용한다. 앱 핵심은 표준 라이브러리만 사용한다.

```bash
python3 dev.py check
python3 dev.py test
python3 dev.py run --port 8765
```

## 포함된 자료

- `jeju_agent`, `ui`, `scripts`, `tests`, `config`: 현재 코드와 검증 코드
- `data_raw`, `data_reference`, `models*`, `data`: 원본 CSV·지도 자료·색인·모델·명시된 합성 체험 데이터
- `runtime`: Windows 내장 Python 전체. `python313.zip`도 반드시 함께 유지
- `docs`: 기존 검증·출처·화면 자료와 최신 기획서 Word·PDF·Markdown
- `development_support/proposal_20261031`: 기획서 콘텐츠·작성 도구·자료 조사·문서 QA 기록
- `CODEX_HANDOFF.md`, `AGENTS.md`, `CODEX_START_PROMPT.md`: 다음 Codex를 위한 작업 맥락
- `TRANSFER_MANIFEST.json`: 이번 인계 ZIP의 파일별 SHA256 기준

이전 버전 실행 ZIP, 백업 중복본, 실행 로그, 임시 캐시는 크기와 세션 흔적을 줄이기 위해 포함하지 않았다. 기존 `FILE_MANIFEST.json`은 v13 배포 기록이고, 이번 전체 이전 파일은 `TRANSFER_MANIFEST.json`으로 검증한다. 데이터 원본의 이용조건과 재배포 확인 상태는 기존 명세를 그대로 보존했다. 이 이전본을 공개 배포하거나 대회에 제출할 때는 해당 범위를 별도로 확인한다.

## 위치와 인터넷

내 위치는 브라우저와 OS가 좌표를 제공하는 환경에서만 수신한다. 위치를 받지 못해도 수동 기준 장소로 탐색할 수 있다. 센터 PC의 GPS는 이용자의 여행 출발지와 같지 않을 수 있다. 현재 GPS 주변 탐색은 구현돼 있으나 일정 출발점 자동 연결은 아직 개발 대상이다.

기본 지도와 검색·상담은 오프라인 자료를 쓴다. 공식 원문과 온라인 지도는 인터넷이 필요하며 실시간 교통 API는 아직 연결하지 않았다.
