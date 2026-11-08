# 제3자 자료와 오픈소스 고지

각 자산의 이용조건을 따로 유지합니다. 이 문서는 모든 코드·데이터·사진·모델에 하나의 새로운 라이선스를 부여하지 않습니다. 대회 결과물 소속 조항도 원 저작자·오픈소스의 권리를 새로 이전하는 조항으로 해석하지 않습니다.

## 데이터와 사진 및 지도

- 허브11종과 보완 공공자료: [DATA_USAGE.md](DATA_USAGE.md)의 자료번호·제공기관·기간·가공·근거URL 참조. 교육부·KERIS 연결 카탈로그의cc-zero 표기와 원허브 별도조건 확인 수준을 구분합니다.
- OpenStreetMap 장소·음식점·도로 및 파생데이터베이스: © OpenStreetMap contributors, ODbL-1.0. [저작권 안내](https://www.openstreetmap.org/copyright), [라이선스 전문](https://opendatacommons.org/licenses/odbl/1-0/). 원본스냅샷·질의·가공DB와 `data_raw/osm/LICENSE_NOTICE.txt`, `LICENSE_TOURISM_ROADS_v5.txt`를 보존합니다. 데이터베이스 재배포 시 출처와 해당 동일조건 의무를 유지합니다.
- 비짓제주·대한민국 구석구석: 공식사실의 짧은 재서술 소개62건이며 원문 링크·확인일·사실 영수증을 기록했습니다. 원문 전체와 사진을 자유라이선스로 재허가하지 않습니다.
- 사진10개: [PHOTO_CREDITS.md](PHOTO_CREDITS.md)에 저작자·원본링크·사진별CC BY2.0/CC BY-SA2.0·3.0·4.0/CC0/퍼블릭도메인 조건·해시를 그대로 제공합니다. 사진별변경·재배포조건을 유지하며 이를웹코드전체조건으로확대하지않습니다. 웹의credits에서도 표기합니다.
- Leaflet: BSD2-Clause, 저작자Volodymyr Agafonkin/CloudMade 고지와 `ui/vendor/leaflet/LICENSE`를 보존합니다.
- Open-Meteo: 선택형외부7일예보. [API조건](https://open-meteo.com/en/terms)과 [CC BY4.0데이터조건](https://open-meteo.com/en/licence), 예보제공기관 출처를 표시합니다. API접속조건과 받아온데이터라이선스는 구분합니다.

## 모델과 런타임

- multilingual-e5-small: intfloat의공개사전학습모델, MIT. [모델카드](https://huggingface.co/intfloat/multilingual-e5-small) 및 동봉 [자체 운영 명세](E5_MODEL_CARD.md), 고정revision·모델/토크나이저SHA를 보존합니다. 원문 카드의 MIT 선언과 연결 프로젝트의 LICENSE 전문은 licenses/e5-upstream-LICENSE.txt에 기록했습니다. 추가제주질의학습은운영미적용입니다.
- Python3.13Windows내장배포: PSF및포함제3자고지, `runtime/LICENSE.txt`를보존합니다. Ubuntu의시스템Python은설치된배포판의고지를따릅니다.
- ONNX Runtime및DirectML: 아래배포본의MIT고지와포함제3자NOTICE를유지합니다. WindowsDirectML바이너리를Linux용CUDA런타임이라고표시하지않습니다.
- NumPy등네이티브배포는주라이선스외BLAS·컴파일러런타임등동봉고지도포함할수있으므로LICENSE/NOTICE전체를유지합니다. 아래표는배포METADATA의선언을읽은목록이며전이구성요소에대한별도법률인증이아닙니다.

## 배포 라이브러리 목록

Windows는vendor의실제dist-info, Linux는동봉wheel의실제METADATA에서읽었습니다. 설치시그wheel안의라이선스파일도유지됩니다. Linux다른Python버전으로별도설치하면해당고정의존성에대응하는공식wheel의고지도따릅니다.

|배포 환경|라이브러리와 버전|METADATA 라이선스 선언|고지 위치|
|---|---|---|---|
|Windows CP313 amd64|anyio 4.16.0|MIT|`vendor/semantic/anyio-4.16.0.dist-info/licenses/LICENSE`|
|Windows CP313 amd64|certifi 2026.10.23|MPL-2.0|`vendor/semantic/certifi-2026.10.23.dist-info/licenses/LICENSE`|
|Windows CP313 amd64|click 8.5.1|BSD-3-Clause|`vendor/semantic/click-8.5.1.dist-info/licenses/LICENSE.txt`|
|Windows CP313 amd64|colorama 0.4.6|OSI Approved :: BSD License|`vendor/semantic/colorama-0.4.6.dist-info/licenses/LICENSE.txt`|
|Windows CP313 amd64|filelock 4.2.9|MIT|`vendor/semantic/filelock-4.2.9.dist-info/licenses/LICENSE`|
|Windows CP313 amd64|flatbuffers 25.12.19|Apache 2.0|`docs/licenses/flatbuffers-25.12.19-LICENSE.txt`|
|Windows CP313 amd64|fsspec 2026.9.0|BSD-3-Clause|`vendor/semantic/fsspec-2026.9.0.dist-info/licenses/LICENSE`|
|Windows CP313 amd64|h11 0.16.0|MIT|`vendor/semantic/h11-0.16.0.dist-info/licenses/LICENSE.txt`|
|Windows CP313 amd64|hf-xet 1.8.0|Apache-2.0|`vendor/semantic/hf_xet-1.8.0.dist-info/licenses/LICENSE`|
|Windows CP313 amd64|httpcore 1.0.9|BSD-3-Clause|`vendor/semantic/httpcore-1.0.9.dist-info/licenses/LICENSE.md`|
|Windows CP313 amd64|httpx 0.28.1|BSD-3-Clause|`vendor/semantic/httpx-0.28.1.dist-info/licenses/LICENSE.md`|
|Windows CP313 amd64|huggingface_hub 1.33.0|Apache-2.0|`vendor/semantic/huggingface_hub-1.33.0.dist-info/licenses/LICENSE`|
|Windows CP313 amd64|idna 3.20|BSD-3-Clause|`vendor/semantic/idna-3.20.dist-info/licenses/LICENSE.md`|
|Windows CP313 amd64|numpy 2.3.5|BSD-3-Clause 및 동봉 제3자 고지|`vendor/semantic/numpy-2.3.5.dist-info/LICENSE.txt`|
|Windows CP313 amd64|onnxruntime 1.31.1|MIT License|`vendor/semantic/onnxruntime/LICENSE`|
|Windows CP313 amd64|packaging 26.3|Apache-2.0 OR BSD-2-Clause|`vendor/semantic/packaging-26.3.dist-info/licenses/LICENSE`|
|Windows CP313 amd64|protobuf 7.36.2|3-Clause BSD License|`vendor/semantic/protobuf-7.36.2.dist-info/LICENSE`|
|Windows CP313 amd64|PyYAML 6.0.3|MIT|`vendor/semantic/pyyaml-6.0.3.dist-info/licenses/LICENSE`|
|Windows CP313 amd64|tokenizers 0.22.2|OSI Approved :: Apache Software License|`docs/licenses/tokenizers-0.22.2-LICENSE.txt`|
|Windows CP313 amd64|tqdm 4.70.1|MPL-2.0 AND MIT|`vendor/semantic/tqdm-4.70.1.dist-info/licenses/LICENCE`|
|Windows CP313 amd64|typing_extensions 4.16.0|PSF-2.0|`vendor/semantic/typing_extensions-4.16.0.dist-info/licenses/LICENSE`|
|Windows CP313 amd64|onnxruntime-directml 1.24.4|MIT License|`vendor/semantic_gpu/onnxruntime/LICENSE`|
|Linux wheel / Python3.12 or universal|anyio 4.16.0|MIT|`wheelhouse/linux-cp312/anyio-4.16.0-py3-none-any.whl!/anyio-4.16.0.dist-info/licenses/LICENSE`|
|Linux wheel / Python3.12 or universal|certifi 2026.10.23|MPL-2.0|`wheelhouse/linux-cp312/certifi-2026.10.23-py3-none-any.whl!/certifi-2026.10.23.dist-info/licenses/LICENSE`|
|Linux wheel / Python3.12 or universal|click 8.5.1|BSD-3-Clause|`wheelhouse/linux-cp312/click-8.5.1-py3-none-any.whl!/click-8.5.1.dist-info/licenses/LICENSE.txt`|
|Linux wheel / Python3.12 or universal|colorama 0.4.6|OSI Approved :: BSD License|`wheelhouse/linux-cp312/colorama-0.4.6-py2.py3-none-any.whl!/colorama-0.4.6.dist-info/licenses/LICENSE.txt`|
|Linux wheel / Python3.12 or universal|filelock 4.2.9|MIT|`wheelhouse/linux-cp312/filelock-4.2.9-py3-none-any.whl!/filelock-4.2.9.dist-info/licenses/LICENSE`|
|Linux wheel / Python3.12 or universal|flatbuffers 25.12.19|Apache 2.0|`docs/licenses/flatbuffers-25.12.19-LICENSE.txt`|
|Linux wheel / Python3.12 or universal|fsspec 2026.9.0|BSD-3-Clause|`wheelhouse/linux-cp312/fsspec-2026.9.0-py3-none-any.whl!/fsspec-2026.9.0.dist-info/licenses/LICENSE`|
|Linux wheel / Python3.12 or universal|h11 0.16.0|MIT|`wheelhouse/linux-cp312/h11-0.16.0-py3-none-any.whl!/h11-0.16.0.dist-info/licenses/LICENSE.txt`|
|Linux wheel / Python3.12 or universal|hf-xet 1.8.0|Apache-2.0|`wheelhouse/linux-cp312/hf_xet-1.8.0-cp38-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl!/hf_xet-1.8.0.dist-info/licenses/LICENSE`|
|Linux wheel / Python3.12 or universal|httpcore 1.0.9|BSD-3-Clause|`wheelhouse/linux-cp312/httpcore-1.0.9-py3-none-any.whl!/httpcore-1.0.9.dist-info/licenses/LICENSE.md`|
|Linux wheel / Python3.12 or universal|httpx 0.28.1|BSD-3-Clause|`wheelhouse/linux-cp312/httpx-0.28.1-py3-none-any.whl!/httpx-0.28.1.dist-info/licenses/LICENSE.md`|
|Linux wheel / Python3.12 or universal|huggingface_hub 1.33.0|Apache-2.0|`wheelhouse/linux-cp312/huggingface_hub-1.33.0-py3-none-any.whl!/huggingface_hub-1.33.0.dist-info/licenses/LICENSE`|
|Linux wheel / Python3.12 or universal|idna 3.20|BSD-3-Clause|`wheelhouse/linux-cp312/idna-3.20-py3-none-any.whl!/idna-3.20.dist-info/licenses/LICENSE.md`|
|Linux wheel / Python3.12 or universal|numpy 2.3.5|BSD-3-Clause 및 동봉 제3자 고지|`wheelhouse/linux-cp312/numpy-2.3.5-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl!/numpy-2.3.5.dist-info/LICENSE.txt`|
|Linux wheel / Python3.12 or universal|onnxruntime 1.31.1|MIT License|`wheelhouse/linux-cp312/onnxruntime-1.31.1-cp312-cp312-manylinux_2_28_x86_64.whl!/onnxruntime/LICENSE`|
|Linux wheel / Python3.12 or universal|packaging 26.3|Apache-2.0 OR BSD-2-Clause|`wheelhouse/linux-cp312/packaging-26.3-py3-none-any.whl!/packaging-26.3.dist-info/licenses/LICENSE`|
|Linux wheel / Python3.12 or universal|protobuf 7.36.2|3-Clause BSD License|`wheelhouse/linux-cp312/protobuf-7.36.2-py3-none-any.whl!/protobuf-7.36.2.dist-info/LICENSE`|
|Linux wheel / Python3.12 or universal|PyYAML 6.0.3|MIT|`wheelhouse/linux-cp312/pyyaml-6.0.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl!/pyyaml-6.0.3.dist-info/licenses/LICENSE`|
|Linux wheel / Python3.12 or universal|tokenizers 0.22.2|OSI Approved :: Apache Software License|`docs/licenses/tokenizers-0.22.2-LICENSE.txt`|
|Linux wheel / Python3.12 or universal|tqdm 4.70.1|MPL-2.0 AND MIT|`wheelhouse/linux-cp312/tqdm-4.70.1-py3-none-any.whl!/tqdm-4.70.1.dist-info/licenses/LICENCE`|
|Linux wheel / Python3.12 or universal|typing_extensions 4.16.0|PSF-2.0|`wheelhouse/linux-cp312/typing_extensions-4.16.0-py3-none-any.whl!/typing_extensions-4.16.0.dist-info/licenses/LICENSE`|
|설치도구 공통|pip 26.3|MIT|`tools/pip-26.3-py3-none-any.whl!/pip-26.3.dist-info/licenses/LICENSE.txt`|

## 개발과 학습 도구

서비스코드는표준라이브러리와위선택형검색런타임으로실행합니다. 과거학습·비교에사용한scikit-learn(BSD3-Clause), CatBoost(Apache2.0), LightGBM(MIT), PyTorch(BSD계열) 등은운영추론에필수라고표시하지않습니다. 해당학습을다시실행하는경우별도재현코드·의존성·원저작자조건을따릅니다. 이패키지가그도구의모든학습환경바이너리를포함한다는뜻이아닙니다.

개발과문서편집에AI개발도구를활용했으나서비스요청을외부LLM에전송하지않습니다. 개발도구의실제확인가능한이름·활용범위와런타임모델목록은README와AI활용명세를따릅니다. 확인하지않은개발도구내부모델명을추측하지않습니다.
