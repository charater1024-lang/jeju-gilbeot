# E5 운영 모델 명세

이 문서는 탐라따라에 포함한 모델의 자체 명세입니다. Hugging Face 모델카드 전체나 상위 벤치마크 표를 복제하지 않았습니다.

- 모델ID: `intfloat/multilingual-e5-small`
- 고정revision: `614241f622f53c4eeff9890bdc4f31cfecc418b3`
- [제작자 모델카드](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3) · [고정revision README 원문](https://huggingface.co/intfloat/multilingual-e5-small/raw/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md)
- 원문 모델카드의 라이선스 선언: MIT. 카드가 연결한 [Microsoft unilm E5 프로젝트](https://github.com/microsoft/unilm/tree/master/e5)의 [MIT LICENSE](https://github.com/microsoft/unilm/blob/master/LICENSE) 원문을 `licenses/e5-upstream-LICENSE.txt`에 보관합니다. 그 원문에 있는 저작자 표기를 변경하거나 새 저작자를 만들지 않았습니다.

## 실제 사용

공식 관광 안내문과 질문을384차원 숫자로 바꾸어 의미가 비슷한 기존 안내를 검색합니다. 답변 문장을 생성하는 LLM이 아니며, 외부 추론API로 질문을 보내지 않습니다. `query: `와 `passage: ` 접두어, 점수 기준0.86을 적용합니다. 점수는 정확도 확률이 아닙니다.

운영 선택은 `small_pretrained`입니다. 공개 사전학습 모델을 ONNX로 변환했고 제주 질문·안내문으로 추가 학습한 가중치는 운영에 채택하지 않았습니다. 운영설정의 `training_source_pairs`는0입니다. 과거40개 이름-소개 쌍 적응 학습과base모델은 비교 실험의 후보이며 해당 거대 가중치를 제출물에 포함하지 않습니다.

CPU는INT8 모델, Windows 선택형DirectML GPU는FP32 모델을 사용합니다. GPU 입력길이64와 긴질문의CPU대체 등 세부조건은 실행코드·설정을 따릅니다. Ubuntu 동작은별도Linux CPU의존성을 사용하며Windows DML을Linux GPU라고표시하지않습니다.

## 동봉 파일 확인

|파일|바이트|SHA256|
|---|---:|---|
|`models_semantic/encoder.int8.onnx`|118269180|`87f3135651e3a93f9e50d3685776586b404e21f805e8060ef1510a4d0076eb69`|
|`models_semantic/encoder.fp32.onnx`|470223896|`cf3f713592d6a68b340057834342b44812495437749855e43c9af914e739fe54`|
|`models_semantic/tokenizer.json`|17082800|`cd98e5698b201ba914efb8c18b6709fa8735ab71dcad8d2b431e52e8bf68d932`|
|`models_semantic/corpus.json`|756720|`f599185c4d7d6f87b001ffac84060706d71bef41870b6265f692db6b1a5d6e32`|
|`models_semantic/config.json`|707|`59f700d2b4c00914d1afaa1cb406b2e1bc9bd53818aec1eccd68b51b176e46d1`|
|`models_semantic/gpu_config.json`|704|`4895292b7cdfb30e04bb3480e6e905670581cd40a2b8b4865dae8f430ce3e321`|

## 평가 범위

분리한 자체 시험 질문의 지원24개 중23개에서 목표 안내가 첫 결과와상위3개에 포함됐고, 미지원12개는 빈 결과를 점검했습니다. 12개 관광지에 대한 제한된 작성질문 시험이며 실제 이용자전체의 정확도나 센터 처리성능을 뜻하지 않습니다. 원문 E5의일반 벤치마크점수와구분합니다. 동결질문·선택·변환·평가 기록은 `REPRODUCTION/e5/`에있습니다.

기본 실행은 이미 동봉한 모델을 사용합니다. 모델을 다시 내려받거나 재학습할 필요는 없습니다.
