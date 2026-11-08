# 런타임 규칙과 준비 답변 위치

운영 서비스에는 LLM 호출이나 LLM 프롬프트가 없습니다. 이 문서는 실제 코드의 처리 흐름을 설명하며 모델에 전달하는 system prompt가 아닙니다.

- `jeju_agent/orchestrator.py`: 확인된 출발 조건 → 장소 검색·자격 확인 → 일정 계산 → 복귀 조건 검사 → 설명·경로 결과.
- `jeju_agent/place_trust.py`, `config/place_trust_policy_v15.json`: 관광 자격·출처·확인일·설명 영수증 검사.
- `jeju_agent/chatbot.py`, `config/chatbot_faq.json`: 질문 규칙·후속 선택·준비 FAQ.
- `data_reference/chatbot.sqlite`: 실제 장소 필드로 미리 정리한 안내문. 독립적인 수만 개 사람이 쓴 FAQ나 자유 생성 답변이 아닙니다.
- `jeju_agent/assistant_search.py`: 공식 설명의 TF-IDF 검색.
- `jeju_agent/semantic_search.py`: 동일한 공식 설명에 대한 E5 의미 검색.

출처에서 확인한 내용과 모델 계산·가정값을 구분합니다. 근거 없는 평점·현재 영업·메뉴·입구·실시간 교통·실제 인기 동선을 생성하지 않습니다. 자료가 없거나 조건을 만족하지 못하면 그 이유를 안내합니다. 실제 권한 동의 없이 GPS를 사용하지 않으며 인증키나 원시 위치를 설명문에 넣지 않습니다.
