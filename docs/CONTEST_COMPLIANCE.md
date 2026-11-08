# 공식 안내와 제출 파일의 대응

2026-11-08 한국시간에 [대회 안내](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge)와 [게시판](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board)의공개27글·댓글20개·답글1개,관련공지첨부를읽고제출물을준비했다. 다른참가자의질문·미답변내용을운영진확정조건으로사용하지않았다. 다른사람의원시게시글·프로필·공지PDF전체는ZIP에복제하지않았다.

|공식요구|제출위치|
|---|---|
|15쪽이내기획서PDF|`docs/제주길벗_최종기획서.pdf`, 별도제출PDF도제공|
|실행소스·모델·도구/API·데이터처리|`center_app.py`, `jeju_agent/`, `scripts/`, `models*`, `docs/IMPLEMENTATION.md`|
|프롬프트/판단·자율범위|런타임LLM프롬프트해당없음. 규칙·준비답변·도구조정코드와 `prompts/RUNTIME_RULES.md` 공개|
|실행환경·설치·매뉴얼·환경변수|루트README, `.env.example`, `requirements/`, Windows런타임, Ubuntu오프라인wheel|
|데이터·출처·이용조건·전처리·외부자료|`docs/DATA_USAGE.md`, `docs/THIRD_PARTY_NOTICES.md`, `config`의실제활용11종,선별공개원본|
|문제·구조·기능·결과·검증·센터활용|기획서, `docs/IMPLEMENTATION.md`, `docs/VALIDATION.md`, `docs/validation/`, `docs/REPRODUCTION/`|

## 공식 답변에 따라 반영한 사항

- [센터OS·추가설치](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board&postId=3d8a1ba3-d0d8-4667-9e0e-b6d5d671e6d5): Windows11을센터기준으로기재하고설치항목을명시했다. Ubuntu24.04는추가지원이다.
- [VRAM·CSV](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board&postId=bf483331-0a71-4f92-b061-570b12b31fa8): GTX1060의VRAM3072MB를반영했다.
- [로컬서버·브라우저·외부주소](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board&postId=368e6265-4d28-4d8c-9c73-1fb28c131fc9): localhost실행,Chrome/Edge기준,외부주소·용도·연결실패대체를설계서에명시했다.
- [공개전처리·DB동봉](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board&postId=b2f27892-3e7e-4df7-b055-d50d529f4741): 실제사용공개원본·적재DB와가공명세를동봉했다.
- [데이터목록파일제외](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board&postId=685a3d1d-2d50-48f4-8114-f4aeae6a8075): 대회제공전체데이터목록엑셀과그목록DB를동봉하지않았다. 실제관광/음식점DB와구분했다.
- [선택링크·마감](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge?section=board&postId=cc8f28e5-6253-446b-a664-ff9ac7ffbb82): 데모·GitHub·영상은필수가아니므로별도배포·업로드를수행하지않았다.

최종제출은기획서PDF와ZIP을갤러리에서사용자가업로드한다. 확인한공개프런트엔드의기본상한은PDF20MiB·ZIP5GiB이며실제서버업로드승인을시험한것은아니다. 센터분석자료반출첨부의3GB와혼동하지않는다. 제출마감은2026-11-20 10:00KST이다. 제출시화면의최신조건을따른다.

규정에서LLM필수조건을찾지못했으나이비LLM구조가운영진의개별승인을받았다고쓰지않는다. 실제학습모델·구현흐름·개발AI사용·외부의존성을명시했다. 민감한인증정보를포함하지않고센터이용자자료를자동반출하는기능을제공하지않는다.
