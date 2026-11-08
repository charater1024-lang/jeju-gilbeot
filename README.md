# 탐라따라

**제주 공공데이터 기반 맞춤 여행 코스 추천 AI Agent**

제주 관광지의 공식 설명과 위치를 살펴보고, 출발지·시간·지역·관심 조건에 맞춰 하루 여행 코스를 만드는 로컬 웹 서비스입니다. 제주데이터허브 공개 자료를 중심으로 음식 이용 경향, 과거 기온과 꽃 여행 시기도 함께 안내합니다. 센터 PC에서 서버를 실행하고 같은 PC의 브라우저로 이용합니다.

서비스명은 **탐라따라(TAMRA TTARA)**입니다. 이전 브랜드의 GitHub 주소는 기존 링크 호환을 위해 유지합니다.

## 최종 제출본 받기

**실행하려면 [최종 Release](https://github.com/charater1024-lang/jeju-gilbeot/releases/tag/v2026.11.09-tamra-ttara)의 완성본 ZIP을 받으세요.** 모델·데이터·Windows Python 런타임·Ubuntu 오프라인 설치 패키지가 모두 들어 있습니다. GitHub의 초록색 **Code → Download ZIP**은 검토용 소스 묶음으로, 실행 자산 전체를 담은 Release ZIP과 다릅니다.

|파일|내용|
|---|---|
|[실행용 전체 ZIP](https://github.com/charater1024-lang/jeju-gilbeot/releases/download/v2026.11.09-tamra-ttara/tamra_ttara_final_20261109.zip)|525.34MiB · 소스, 데이터, 학습된 모델, Windows 런타임, Ubuntu 설치 패키지, 문서|
|[기획서 PDF](https://github.com/charater1024-lang/jeju-gilbeot/releases/download/v2026.11.09-tamra-ttara/tamra_ttara_proposal_20261109.pdf)|15쪽 최종 기획서 · [저장소에서 보기](docs/탐라따라_최종기획서.pdf)|
|[상세 실행 안내](README_실행안내.md)|OS별 설치·실행·정상 상태·검사·문제 해결|
|[SHA256SUMS.txt](https://github.com/charater1024-lang/jeju-gilbeot/releases/download/v2026.11.09-tamra-ttara/SHA256SUMS.txt)|다운로드한 배포 파일 검증|

전체 ZIP SHA256: `e7bb7d73e5a9fba29bb6b9aa7bae9fb366309e90ea1cad8469a3deab119105db`

## 빠른 실행

전체 ZIP을 **새 폴더에 완전히 압축 해제**한 뒤, 그 안의 `tamra_ttara` 폴더에서 실행합니다. Git 체크아웃 폴더에 덮어쓰지 않습니다. 운영 실행에 데이터 재다운로드·재학습·API 인증키·Conda가 필요하지 않습니다.

Windows11 x64는 동봉 Python3.13과 라이브러리를 사용합니다.

```powershell
.\run_center.cmd
```

선택 GPU 실행은 `run_center_gpu.cmd`입니다. 기본 CPU로도 핵심 기능과 E5 의미 검색을 사용할 수 있습니다. DirectML GPU 준비 여부는 `/api/compute-status`에서 확인합니다.

Ubuntu24.04 LTS x86_64는 Python3.12를 먼저 준비한 뒤 실행합니다.

```bash
bash setup_ubuntu.sh && bash run_center.sh
```

프로젝트 전용 `.venv-linux`를 만들고 동봉 Linux wheel로 설치합니다. `requirements/linux-cpu.lock.txt`에 버전·해시를 고정했습니다. Conda용 `environment.yml`은 제공하지 않습니다. 사전 준비·DLL 오류·글꼴·포트 변경과 설치 검증은 [실행 안내](README_실행안내.md)를 따릅니다.

브라우저 접속은 **http://127.0.0.1:8765/**, 종료는 실행창에서 **Ctrl+C**입니다. 같은 PC에서 실행하는 구성이며 공개 데모 서버 주소는 아닙니다.

## 서비스와 AI

|기능|사용 방식|
|---|---|
|공식 관광지 검색|명부·지도 교차확인, 공식 소개, TF-IDF 및 선택형 multilingual-e5-small 의미 검색|
|맞춤 하루 코스|확인한 출발지 → 후보 검증 → 도로 거리·가정 속도 → 시간·복귀 조건 탐색 → 일정 재검사|
|먹거리 안내|허브1048·1047의 월별 업종 이용 비중을 가중 계절 Ridge 계열로 안내|
|기온·꽃 시기|허브877 기반 HGB·분위수 기온 회귀와 과거 꽃 일정 비교, 선택형 Open-Meteo 7일 예보|
|탐라따라 상담|준비한 답변·규칙·공식 자료 검색. 런타임 LLM과 유료 LLM API 사용 없음|
|위치·지도|사용자가 동의한 위치 또는 직접 고른 공개 출발지, 동봉 OSM 도로의 오프라인 경로|

관광 후보68곳, 공식 소개62건, 자동 코스 대상40곳은 서로 다른 범위입니다. 음식점 명부는 별도이며 좌표가 확인되지 않은 식당에 임의 좌표를 붙이지 않습니다. 이동 시간은 거리·가정 속도에 따른 추정이며 실시간 교통·현재 영업 상태·실제 인기 방문 순서의 학습값이 아닙니다. E5는 공개 사전학습 모델을 채택했고 제주 질문 추가 학습 가중치는 운영에 사용하지 않습니다.

## 문서와 재현

- [15쪽 기획서](docs/탐라따라_최종기획서.pdf), [편집용 Word](docs/탐라따라_최종기획서.docx)
- [데이터 출처·원본·가공·활용](docs/DATA_USAGE.md), [구현·외부 연결·설치 요구사항](docs/IMPLEMENTATION.md)
- [기능 검증과 평가 해석](docs/VALIDATION.md), [학습·변환·평가 연구 재현](docs/REPRODUCTION.md)
- [모델 설명](docs/E5_MODEL_CARD.md), [자산별 라이선스](docs/THIRD_PARTY_NOTICES.md), [사진 출처](docs/PHOTO_CREDITS.md)

`jeju_agent/`, `ui/`, `config/`, `scripts/`, `tests/`는 최종 제출 ZIP과 동일한 현재 소스입니다. Git에는 검토할 소스·문서와 일부 공개 참고 자료를 두고, 대용량 모델·DB·실행 라이브러리는 Release에 제공합니다. 실행·동작 검사는 완성본 ZIP을 새 폴더에 푼 곳에서 진행합니다. `SUBMISSION_MANIFEST.json`도 그 완성본의 명세이며, 자산이 빠진 Git 체크아웃의 완전성 검사에는 사용하지 않습니다. 과거 `SERVICE_MANIFEST_v*`와 연구 문서는 이력으로 보존했습니다. 최신 기준은 이 README·최종 기획서·최종 Release입니다.

최종 기능 확인은 Python 현재 범위426개(과거 실험22개 명시적 미실행), UI 동작29개·JavaScript 문법18개, Windows HTTP49개, 완성 ZIP 재압축 해제 후 HTTP24개·정적 파일2,993개 해시 검사입니다. Ubuntu24.04/Python3.12의 기존 실제 VM26개 기능 결과와 동일 코드·모델을 유지했습니다. 기능 검사 수를 추천 정확도나 센터 처리량으로 해석하지 않습니다. 과거 TF-IDF22질의 원본 미보관과 HGB의 단순 기준 대비 오차 한계는 검증 문서에 공개했습니다.

## 출처와 AI 개발 도구

제주데이터허브11종·원본CSV14개와 보완 공개 자료를 사용했습니다. 데이터·사진·OSM·모델·라이브러리는 각 출처와 이용 조건을 따르며 저장소 전체에 새 단일 라이선스를 덧씌우지 않습니다. 원자료와 변환 과정은 `docs/DATA_USAGE.md`에서 추적할 수 있습니다.

개발 과정에서 OpenAI Codex 등 생성형 AI 개발 도구를 코드·문서 작성·검토에 활용했습니다. 서비스 이용자의 질문을 외부 LLM으로 보내는 기능과는 구분합니다.
