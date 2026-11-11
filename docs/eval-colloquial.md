# 구어체 평가 세트 작성·검수 지침

대상 파일: `tests/fixtures/faq_eval_colloquial.jsonl` · 도구: `scripts/make_blind_brief.py`, `scripts/eval_colloquial.py`

## 1. 출처 공개

- 이 세트의 질문은 사람이 쓴 것이 아니다. 작성자는 AI 보조(LLM 에이전트)다.
- 검수도 사람이 아니라 작성 에이전트와 분리된 별도 LLM 리뷰어 에이전트가 한다.
- 따라서 이 세트는 "실제 시민 발화"가 아니라 "실제 발화에 가깝게 쓰도록 통제한 합성 질문"이다. 수치를 인용할 때 이 점을 함께 적는다.

## 2. 작성 지침

- 말투: 민원 키오스크 앞에 선 일반 시민. 짧은 한 문장. 존댓말·반말 섞여도 된다.
- 방법: blind brief의 답변 발췌를 읽고 "이 답을 듣고 싶은 사람이 처음 꺼낼 말"을 쓴다.
- 답변에 나오는 제도·서류 이름을 그대로 옮기지 않는다. 가능하면 상황으로 돌려 말한다.
  - 예: "출생신고 기한" 대신 "애기 낳았는데 언제까지 신고해야 돼요"
- 길이: 4~80자, 한 문장.
- trait (행마다 1개 이상, 전체 최소 개수):

  | trait | 뜻 | 최소 |
  |-------|----|------|
  | `typo` | 받아쓰기·자판 오타 | 5 |
  | `ellipsis` | 조사·목적어 생략, 말 줄임 | 8 |
  | `indirect` | 제도명 없이 상황으로 돌려 말함 | 10 |
  | `spoken` | 구어 어미·군말 ("그거", "있잖아요") | 제한 없음 |

- 구성: 답 있는 행 38건(`kind: "colloquial"`, brief의 `target_id`를 `expected_id`로) + 답 없는 행 8건(`kind: "none"`, `expected_id: null`).
- none 8건: 키오스크에서 물을 법하지만 시 FAQ 범위 밖인 질문. 예: 다른 지역 행정, 실시간 날씨·교통, 개인 사건 상담.
- 금지: 개인정보, 실명, 전화번호, 주소, IP 주소.

## 3. 누출 줄이기 절차

1. `scripts/make_blind_brief.py`로 blind brief(인텐트명 없이 `target_id`·분류·답변 발췌만)를 만든다.
2. 작성자는 brief만 보고 쓴다. 다음은 열람 금지: `data/faq/faq.jsonl`, `tests/fixtures/faq_eval.jsonl`, `scripts/eval*`, `tests/**`.
3. 작성자는 검색을 실행하지 않는다. 쓸 수 있는 명령은 `scripts/eval_colloquial.py --validate` 하나뿐이다.
4. 순서는 고정: 작성 → 감사(리뷰어) → 1회 수정 → 커밋으로 동결 → 측정.
5. 측정 후에는 질문을 고치지 않는다. 결과가 나빠도 그대로 보고한다.

## 4. 누출 지표

정의 (`scripts/eval_colloquial.py`):

- `bigrams(s)`: `s`를 NFC 정규화·소문자화한 뒤 글자·숫자가 아닌 문자(공백·문장부호)를 모두 지우고, 이어진 두 글자 묶음의 집합을 만든다.
- `leak(query, intent) = |B(intent) ∩ B(query)| / |B(intent)|`, `B(intent)`가 비면 0. 여기서 intent는 정답 FAQ의 질문(인텐트명)이다.
- 구간: `leak < 0.34`는 low-leak, `leak ≥ 0.34`는 high-leak (`LOW_LEAK = 0.34`).

해석:

- 1.0이면 인텐트명 글자가 질문에 모두 들어 있다(띄어쓰기만 바꾼 복사 포함). 0이면 두 글자 묶음이 하나도 겹치지 않는다.
- BM25는 글자 bigram을 쓰므로 leak가 높으면 맞히기 쉽다. `top1_low_leak`가 "인텐트명을 모르는 사용자"에 가까운 정확도다.
- `leak_mean`이 낮을수록 세트가 검색기에 유리한 단서를 덜 준다. 기존 규칙 기반 세트(`faq_eval.jsonl`)와 같은 명령으로 비교한다.
- none 행은 leak를 계산하지 않는다(`na`).

## 5. 검수 기준 (리뷰어용 체크리스트)

리뷰어도 검색 측정은 실행하지 않는다. `--validate`와 `grep`만 쓴다.

- [ ] 정답 FAQ의 답변이 질문에 실제로 답이 되는가.
- [ ] 더 맞는 다른 FAQ가 있으면 그 id로 정정을 제안한다.
- [ ] none 행: 핵심어 2개 이상으로 `grep` 해서 답이 되는 FAQ가 없음을 확인한다.
- [ ] 한 문장, 4~80자.
- [ ] 개인정보·실명·전화번호·주소·IP 없음.
- [ ] trait 표기가 실제 질문과 맞고, §2 최소 개수를 채운다.

## 6. 라이선스

질문 텍스트(`tests/fixtures/faq_eval_colloquial.jsonl`의 `query`)는 CC0으로 공개한다. 정답 id가 가리키는 FAQ 본문의 출처·라이선스는 `data/README.md`를 따른다.
