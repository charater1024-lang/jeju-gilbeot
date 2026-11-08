# 최신 실행·개발 안내

최신 제출본은 [GitHub Release](https://github.com/charater1024-lang/jeju-gilbeot/releases/tag/v2026.11.08-submission)의 전체 ZIP입니다. ZIP을 새 폴더에 풀어 루트 README를 따르세요. Windows는 `run_center.cmd`, Ubuntu24.04/Python3.12는 `bash setup_ubuntu.sh && bash run_center.sh`입니다. 모델·DB·런타임을 동봉했으므로 과거 Git 복구/restore를 실행하지 않습니다. 이 Git 저장소는 검토·개발용 소스이며, 최신 기획서는 `docs/제주길벗_최종기획서.pdf`입니다.

## 이전 작성 시점의 이력

# GitHub에서 제주 길벗 복원하기

저장소에 접근할 수 있는 Windows PC에서 Git과 Python 3.10 이상을 준비합니다. Python 3.13에서 아래 절차를 검증했습니다.

```powershell
git clone https://github.com/charater1024-lang/jeju-gilbeot.git
Set-Location .\jeju-gilbeot
python -B dev.py restore
python -B dev.py check --service
.\run_center.cmd
```

`restore`는 처음 실행할 때 인터넷에 연결해 제주데이터허브와 공공데이터포털의 공개 첨부 9개를 받습니다. 파일의 크기와 SHA-256을 확인한 뒤 소비 모델, 장소·음식점·상담 색인, 도로 그래프와 여행 참고 자료를 PC에서 생성합니다. 다시 실행하면 검증을 통과한 파일을 재사용합니다. Python 패키지와 API 키 없이 실행할 수 있습니다.

저장소에는 OpenStreetMap 스냅샷과 ODbL 출처 고지, 이용조건을 표시한 사진, 프로젝트가 작성한 관광 소개와 원문 검증 메타데이터가 들어 있습니다. 내려받은 원자료와 생성한 DB·모델은 실행한 PC에 저장됩니다. 기본 서버 주소는 `http://127.0.0.1:8765/`입니다. [공개 원본 명세](config/restore_sources.json) · [OpenStreetMap 이용조건](data_raw/osm/LICENSE_TOURISM_ROADS_v5.txt) · [사진 출처](docs/PHOTO_CREDITS.md)

`check --service`는 현재 서비스 실행에 필요한 자료를 확인합니다. `dev.py check`는 동봉 Python과 과거 평가 파일까지 포함한 전체 이전본의 바이트 단위 검사용입니다. 별도 연구·평가에 사용한 자료와 이전 보고서를 보존해야 할 때는 [v27 전체 파일 명세](SERVICE_MANIFEST_v27.json)와 승인된 로컬 이전본을 사용합니다.

공식 다운로드 주소가 응답하지 않거나 첨부가 바뀌면 복원이 중단됩니다. 오류에 나온 파일과 출처를 확인한 뒤 `restore`를 다시 실행하세요. 같은 위치에 해시가 다른 파일이 있다면 해당 파일을 다른 곳에 보관한 뒤 다시 실행하세요.

Codex에서 `jeju-gilbeot` 폴더를 프로젝트로 엽니다. 다른 PC에서 반영한 커밋을 가져오려면 작업 트리가 깨끗할 때 `git pull --ff-only`를 실행합니다. [서비스 사용 방법](README.md#빠른-실행)
