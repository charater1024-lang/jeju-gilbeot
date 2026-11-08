# 모델과 데이터 처리의 재현 자료

운영 실행에는 재학습이 필요하지 않습니다. 동봉한 CSV·SQLite·JSON·ONNX 모델을 사용하면 됩니다. 설치와 실행은 루트README를 따릅니다. 이 문서는 사용 모델의 수집·가공·학습·변환·평가 근거를 확인하려는 검토자와 개발자를 위한 별도 안내입니다.

`REPRODUCTION/`에는 현재 채택한Ridge·HGB·E5와 관련된 원래 연구 코드 및 고정 결과를 선별했습니다. 미채택 거대 모델 가중치, 웹페이지 전체 복제, 대회 제공 데이터 목록, 개화 예측용 인증키 수집 코드는 넣지 않았습니다. `REPRODUCTION/MANIFEST.json`에 원래 프로젝트 상대경로·동봉경로·크기·SHA256을 기록했습니다. 이 제출 준비 과정에서 재학습하거나 평가 질문을 새로 만들지 않았습니다.

## 실행 프로그램과 연구 코드의 구분

- `jeju_agent/`와루트실행도구는제출서비스의실행코드입니다.
- `docs/REPRODUCTION/`은연구원본·프로토콜·평가를보관한자료입니다. 파일을서버에서자동호출하지않습니다.
- 연구를실행하려면패키지밖에새작업폴더와서비스복사본을만듭니다. 원본ZIP해제폴더·현재운영폴더를학습출력위치로사용하지않습니다. 모델교체도자동으로하지않습니다.
- 저장된평가에는작성시점의PC경로·시각이남아있을수있습니다. 이는역사영수증이며현재실행경로가아닙니다. 특히`e5/evaluation/freeze_catalog.py`의`ROOT`는원래Windows기기의절대경로입니다. 원본을보존한상태로사본에서새연구서비스경로를지정해야합니다.
- 이연구코드전체가Ubuntu또는센터GPU에서추가설정없이학습된다는뜻은아닙니다. 센터운영지원과별도학습환경재현을구분합니다. 다른라이브러리·GPU·드라이버에서는처리시간이나새가중치의바이트동일성을보장하지않습니다.

## 음식 이용 비중 Ridge

|자료|코드와 고정 결과|입력과 출력|
|---|---|---|
|1048 집단별 음식 비중|`ridge/experiment_audience_v23.py`, `ridge/frozen_audience/`의protocol·selection·result·serving_profile|`data_raw/hub/hub_1048_5832.csv` → 실제 월별 비중 → 검증으로 선택한 가중 계절Ridge → 월별 운영표|
|1047 세부 외식업종 비중|`ridge/train_dining.py`, `ridge/frozen_dining_metrics.json`|`data_raw/hub/hub_1047_5831.csv` → 성별 이용건수 합산 → 94업종 월별 비중 → 계절Ridge|

계산 구현은 실제 서비스의 `jeju_agent/audience_model.py`, `audience_v23.py`, `dining_model.py`에 있습니다. `models_candidates_v23/audience/`는이름에candidate가있지만현재1048운영표와고정근거를로드하는필수폴더입니다.

1048 실험의 진입점은 `--root`, `--output`, `--stage validation|test`입니다. 새연구폴더에서복사한서비스의경로를`--root`, 별도빈출력폴더를`--output`으로지정합니다. 검증후고정된선택을사용해시험합니다. 이미열어본2024.01~2025.06기간을다시계산해도새독립미래평가가되지않습니다.

1047 원래스크립트는자신의상위프로젝트경로를사용하고`models_dining/`에출력합니다. 실행할경우서비스복사본의`scripts/train_dining.py`로실행해야하며보관용`docs/REPRODUCTION/ridge/`경로에서바로실행하지않습니다. 이자료의평균오차0.328%p·0.097%p는저장된과거평가범위의값입니다.

## 계절 기온 HGB

`climate_model/`의5개원본코드는다음역할을갖습니다.

|파일|역할|
|---|---|
|`prepare_climate.py`|허브877의4지점CSV검사, 실제 일평균기온 정리, 시간순분할|
|`freeze_climate_protocol.py`|특징·후보·선택규칙·학습/검증/시험분할을먼저고정|
|`train_climate.py`|대표기온HGB와분위수모델적합, 검증후선택, JSON변환과고정시험|
|`climate_runtime.py`|학습때와같은특징변환 및 표준라이브러리 추론|
|`verify_climate.py`|원본·분할·결과SHA와JSON추론의범위를검사|

`trial_01/`에는실제선택한프로토콜·분할·선택·평가·최종모델JSON을보관했습니다. 현재선택모델의작은JSON근거이며거대한실패후보가중치가아닙니다. 원본은패키지의`data_raw/hub_climate/`이고현재실행모델은`models_climate/`입니다.

원래연구코드는`climate_model/`과그옆의`weather_research/`배치를전제로합니다. 검토용새작업폴더에`climate_model/`을복사하고, 그옆`weather_research/`에동봉한`data_raw/hub_climate/`파일을복사해야합니다. `prepare_climate.py`의`SOURCE`가이상대배치를읽습니다. `train_climate.py`의과거`training_libs`검색경로는별도연구환경의라이브러리경로이며, 필요한NumPy·SciPy·scikit-learn을독립환경에설치한뒤경로를검토해야합니다. 당시버전은`climate_model/requirements-training.txt`와선택기록에남겼습니다. 이파일은운영설치의존성목록이아닙니다.

고정자료를검증할때에는그연구복사본에서`verify_climate.py`를실행합니다. 결과는복사본의`verification.json`에기록됩니다. 새학습을재현할때에는기존`trial_01`을덮어쓰지않는새폴더에서준비·분할고정·학습순으로실행합니다. 원래코드는이미고정된프로토콜덮어쓰기를거절합니다. 검증/시험기간을섞거나시험결과를보고조건을바꾸지않습니다.

학습은2000~2016, 검증은2017~2018, 시험은2019~2021.10입니다. 평균오차1.920°C는단순기준1.903°C보다개선된결과가아닙니다. 기온범위포함76.57%와2021년68.75%의범위를그대로읽으며현재날씨예보나꽃개화일예측으로바꾸지않습니다.

과거부가수집스크립트가전체허브목록파일을참조한경로는이폴더에서제외했습니다. 실제선택한CSV는위고정원본과출처URL·SHA로추적할수있습니다. 전체허브데이터목록이나대회제공목록을수집·동봉하는방식을재현절차로안내하지않습니다.

제출용 보조 도구 `REPRODUCTION/collect_climate_selected.py`는 현재 출처 명세의877 CSV4개만 취급합니다. `--root 패키지경로 --verify-only`는 동봉원본SHA만 검사하고 네트워크를 사용하지 않습니다. 고급 연구자가 원본 재취득을 원하는 경우에만 `--root 패키지경로 --download --output 프로젝트밖의빈폴더`를 지정합니다. 고정공개URL·파일크기·SHA가 달라지면 중단하며 원래운영자료나모델을 덮어쓰지 않습니다. 이 보조 도구는 이번 제출을 위해 작성했으며 원래 학습 스크립트나 과거 평가를 새로 작성한 것은 아닙니다.

## E5 선택과 ONNX 변환

`e5/research/`에는 `fetch_encoders.py`, `semantic_gpu_trial.py`, `semantic_cpu_check.py`, 당시학습의존성목록과원래연구배치README를보관했습니다. 역할은 고정공개모델수집, 사전학습/적응후보비교, FP32 ONNX내보내기, INT8변환, CPU검증입니다.

- `e5/evaluation/`: 출처분할, 개발질문, 보관시험질문, 동결영수증, 프로토콜과검사코드.
- `freeze_catalog.py`의catalog는확인한공식관광소개62건의분할을뜻합니다. 전체제주데이터허브데이터셋목록을수집하는도구가아닙니다. 이파일의과거`ROOT`경로는별도연구복사본에맞춰검토해야합니다.
- `e5/selection/`: 실제small사전학습선택·개발평가·CPU설정고정·변환영수증·최종보관질문평가. 고정질문·정답을새로작성하지않았습니다.
- 실제운영선택은`small_pretrained`이며제주질문추가학습가중치는미채택입니다. 원래연구에있던40쌍적응학습과base모델의거대가중치는동봉하지않았습니다.
- 원래실험은별도Python3.12·CUDA12.8·PyTorch환경과RTX4090Laptop에서진행한연구입니다. 센터GTX1060에이학습환경을설치하는것을기본실행절차로요구하지않습니다.

새연구실행시에는`e5/research/README.md`의별도작업폴더구조를따라`evaluation/`, 서비스복사본`site/`, 결과폴더`semantic/`을분리합니다. 현재보관경로`e5/research/`를그대로실험루트라고가정하지않습니다. 다운로드할공개모델의revision은동봉된선택기록으로고정해야하며최신모델로바꿔받은결과를원래선택의동일재현이라고표시하지않습니다. 원래수집스크립트는small과base를함께받는비교연구도구이므로추가다운로드가발생할수있습니다.

`base_download.json`과`base_asset_hashes.json`은당시비교후보의고정revision·해시영수증만남긴것이며base가중치는동봉하지않았습니다. 원래비교연구를재실행하는경우에만해당영수증을확인합니다.

모델동결→개발후보선택→FP32/INT8변환→CPU개발확인→CPU설정고정→마지막보관시험의순서를지킵니다. 이미평가한질문을반복해서열어도새독립평가가아닙니다. CPU/GPU가중치와토크나이저의현재SHA는[E5 모델명세](E5_MODEL_CARD.md)에있습니다.

## TF-IDF 22질의 기록의 한계

`historical_tfidf/`는기존22/22집계와당시운영API자료입니다. `development_support/retrieval_v20/benchmark.json`과`benchmark_freeze.json`의원래22개고정질의·정답파일은현재복구하지못했습니다. 따라서그특정22질의를새환경에서그대로재현했다고주장하지않습니다.

`e5/evaluation/legacy_guide_cases.json`은별도로작성했던25개기능회귀사례입니다. 이를22개정답세트로바꾸지않습니다. E5의지원24개/목표안내23개평가, 현재실행스모크, 기능회귀, 과거TF-IDF집계를각각구분합니다. 상세현재실행검증은제출검증보고서를따릅니다.
