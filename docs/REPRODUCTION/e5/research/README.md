# 검색 실험 재현 구조

운영 서버 폴더 밖에 새 작업 폴더를 만든다. 이 폴더에 동봉 세 Python 스크립트를 복사하고, `평가/`의 동결 자료를 `evaluation/`으로 복사한다. 현재 서비스의 코드·운영 자료·동봉 Python·CPU vendor를 `site/`라는 독립 복제본으로 준비한다. `site/models_semantic/`은 아직 없는 새 실험 출력 상태여야 한다. 라이브 프로젝트 자체를 이 출력 위치로 사용하지 않는다.

```text
새_작업폴더/
  fetch_encoders.py
  semantic_gpu_trial.py
  semantic_cpu_check.py
  evaluation/        ← 동봉 평가 파일
  site/              ← 서비스의 독립 복제본, vendor/semantic 포함
  .venv/             ← GPU 학습 패키지
```

Python3.12의 별도 venv에서 공식 CUDA PyTorch와 잠금 버전의 학습 패키지를 설치한다. 원래 설치 버전은 `requirements-training.txt`에 있다. Torch는 공식 `https://download.pytorch.org/whl/cu128`에서 2.11.0+cu128을, 나머지는 공식 PyPI에서 준비했다. 원 실험은 Python3.12.10, CUDA12.8, RTX4090Laptop을 사용했다. 다른 GPU·드라이버·패키지에서는 학습 시간과 가중치의 바이트 단위 동일성을 보장하지 않는다.

새 작업 폴더에서 순서대로 실행한다. GPU 단계의 네 후보와 임계값은 `freeze`에서 먼저 고정한다. 보관 질문은 CPU 설정이 고정된 뒤 마지막 명령에서만 읽는다.

```powershell
.\.venv\Scripts\python.exe -B semantic_gpu_trial.py freeze
.\.venv\Scripts\python.exe -B fetch_encoders.py
.\.venv\Scripts\python.exe -B semantic_gpu_trial.py dev
.\.venv\Scripts\python.exe -B semantic_gpu_trial.py export
.\site\runtime\python.exe -B semantic_cpu_check.py dev
.\site\runtime\python.exe -B semantic_cpu_check.py holdout
```

`semantic/`에 GPU 결과·선정·CPU 변환·개발 평가·최종 동결과 보관 결과가 생성된다. 이미 평가한 폴더의 결과를 지우고 같은 독립 시험처럼 반복하지 않는다. 데이터·정책·검토일·기본 알고리즘이 달라지면 새 실험으로 표시해야 한다. 원래 기계의 절대경로는 저장된 실험 영수증에만 남아 있으며 새 실행에서는 새 폴더 경로를 기록한다.

현재 서비스의 기본 핵심 모델3종은 그대로이며, 이 검색 도구는 개인화·인기경로 학습기가 아니다. `source40`은 실제 이름–소개 쌍만 사용하고 작성 평가 질문은 학습하지 않는다. 40쌍 적응 학습은 원 실험에서 채택하지 않았다.
