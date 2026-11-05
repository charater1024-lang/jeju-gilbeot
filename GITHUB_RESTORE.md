# GitHub 작업본과 로컬 실행 자료

이 저장소에는 제주 길벗의 서비스·학습 코드, 테스트, 설정, Markdown 문서와 v20 집계 평가를 보관합니다. 지도 라이브러리에는 동봉된 라이선스와 출처 고지를 적용합니다.

원자료, 데이터베이스, 학습 산출물, 사진, 휴대용 Python, 예제 내보내기와 이전 ZIP은 로컬 작업본에서 관리합니다. 제주데이터허브 자료는 원본과 가공물의 반출 범위를 확인한 뒤 사용합니다. 사진의 개별 출처는 `docs/PHOTO_CREDITS.md`와 `ui/credits.html`에 있습니다.

## 다른 PC에서 실행

1. 저장소를 클론한 뒤 같은 v20 로컬 이전본에서 `data_reference/`, `models*/`, `ui/assets/`, `runtime/`을 상대 경로 그대로 복원합니다. 코드와 Git 관리 파일은 클론의 버전을 사용합니다.
2. 전체 검사나 재학습이 필요하면 로컬 이전본의 `data_raw/`, `examples/`, `development_support/` 및 그 밖의 이전 자료도 각 경로에 복원합니다. 파일 단위의 범위와 해시는 `SERVICE_MANIFEST_v20.json`에서 확인할 수 있습니다. 원본 입수 경로는 `config/download_manifest.json`과 `docs/데이터다운로드보고.md`에 있습니다.
3. 복원 후 `runtime\python.exe dev.py check`로 전체 서비스 파일을 검사하고 `run_center.cmd`를 실행합니다. 새로 받은 파일만으로 전체 실행을 하려면 해당 데이터의 확인 및 모델·색인 생성이 선행되어야 합니다.

현재 실험 결과는 [v20 모델 조합 비교](docs/모델다양화_v20/전체실험_결과보고.md)에 있습니다. 학습 재현에 필요한 라이브러리 버전은 `development_support/change_v20/training_requirements.txt`를 참조합니다.
