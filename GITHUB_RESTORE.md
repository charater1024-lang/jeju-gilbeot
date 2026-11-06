# 다른 Windows PC에서 제주 길벗 이어서 개발하기

GitHub 작업본에는 서비스 코드, 테스트, 설정, 모델 검증 문서, v27 기획서와 화면 캡처가 있습니다. 로컬 실행 자료 ZIP에는 v27 파일 명세에 필요한 데이터, 모델, Windows x64 Python 런타임, 사진과 이전 검증 자료가 들어 있습니다.

1. 새 PC에 Git을 설치하고 저장소에 접근 권한이 있는 GitHub 계정으로 인증합니다.
2. PC 간 직접 복사 등 자료 반출이 허용된 경로로 로컬 실행 자료 ZIP을 가져옵니다. 작업할 상위 폴더에 ZIP을 놓고 PowerShell에서 아래 명령을 실행합니다.
3. 파일 검증을 통과하면 서버를 시작합니다. 기본 접속 주소는 http://127.0.0.1:8765/ 입니다.

```powershell
git clone https://github.com/charater1024-lang/jeju-gilbeot.git
Set-Location .\jeju-gilbeot
tar.exe -xf '..\JejuGilbeot_v27_로컬실행자료.zip' -C .
.\runtime\python.exe -B dev.py check
.\run_center.cmd
```

같은 v27 전체 작업 폴더를 이미 가지고 있다면 [v27 파일 명세](SERVICE_MANIFEST_v27.json)에 따라 로컬 자료를 원래 상대 경로에 복사할 수 있습니다. 공개 1047·1048 원본과 관광 출처 검증 자료는 실제 실행에서도 사용합니다. 이용조건과 반출 범위를 확인한 자료만 이동하고, ZIP은 권한이 있는 PC에서 보관합니다. 자료 출처는 [다운로드 명세](config/download_manifest.json), [데이터 다운로드 보고](docs/데이터다운로드보고.md), [사진 출처](docs/PHOTO_CREDITS.md)에 정리되어 있습니다.

Codex에서 새 PC의 jeju-gilbeot 폴더를 프로젝트로 열면 됩니다. 다른 PC에서 GitHub에 반영한 변경을 가져오려면 작업 트리가 깨끗할 때 git pull --ff-only를 실행합니다. 서버 실행과 테스트 방법은 [README](README.md#처음-실행하기)를 참조하세요.
