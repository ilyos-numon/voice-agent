# Data: voice-agent

This project uses public or synthetic data only. Raw downloads go to data/raw/ (ignored by git). Processed files go to data/processed/.

## Sources

| Dataset | Source URL | License | Version or date | Subset used |
|---|---|---|---|---|
| 합성 FAQ 샘플 | 이 저장소 | CC0 | 2026-10-22 | 5건 |
| 경기도 시흥시_챗봇 FAQ 시나리오 (공공데이터포털 15148282) | https://www.data.go.kr/data/15148282/fileData.do | 이용허락범위 제한 없음 (공공데이터포털 표기) | 2025-09-01 (다운로드 2026-10-22) | 인텐트명·답변·대분류 열, 전처리 후 570건 → `data/faq/faq.jsonl` |
| tests/fixtures/faq_eval.jsonl | 이 저장소 (faq.jsonl에서 규칙으로 생성) | CC0 | 2026-10-22 | 질의 42건 (변형 40 + 센티널 2) |
| tests/fixtures/ask_faq001_ko.wav | 이 저장소 (Supertonic 3로 합성, 가중치 OpenRAIL-M) | CC0 | 2026-10-22 | 질문 1문장, 사람 목소리 아님, 재생성 scripts/make_fixture_audio.py |

## Download

```sh
uv sync --extra dev          # openpyxl (XLSX 읽기)
./scripts/prepare_data.sh    # 다운로드 → 정규화 → 평가 세트 생성 → 평가
```

- 원본: `data/raw/siheung_chatbot_faq_20250901.xlsx` (295,757 B, 12시트, git 제외). 로그인·인증키 없이 받는다. 이미 있으면 `./scripts/prepare_data.sh --skip-download`.
- 다운로드 절차 (`scripts/prepare_faq.py`): (1) 포털 파일 URL을 `GET`해 ZIP 시그니처·100 KB 이상이면 성공, (2) 아니면 포털의 다운로드 해결 요청(`selectFileDataDownload.do`)으로 파일 id를 다시 받아 1회 재시도, (3) 그래도 실패면 종료 3. 포털은 과다 다운로드에 캡차를 띄우므로 한 번 실행에 1회만 받는다.
- 산출물: `data/faq/faq.jsonl` (575행, 476,391 B, 커밋됨), `tests/fixtures/faq_eval.jsonl` (42행, 커밋됨). 같은 입력이면 같은 바이트가 나온다.

## Preprocessing

원본 구조: "챗봇 FAQ 시나리오 전체" 시트 714행 + 분야별 11시트 714행(전체 시트의 부분집합) = raw_rows 1428. 고유 행은 714건, 인텐트명 기준 704개다. 원본에 질문 문장 열이 없어 **질문 필드 = `인텐트명`**(2어절 안팎의 주제명, 예: "어린이 예방접종"), 답변 = `답변`, 분류 = `대분류`를 쓴다. `검토부서`·`담당 팀`·`연락처`·`링크`·`관련 인텐트`·`비 고` 열은 출력하지 않는다.

- 본문 정리 (`clean_text`): HTML 태그·엔티티, 이메일, URL, 전화번호(공공기관 번호 포함)를 제거하고 공백 정리·NFC 정규화.
- 행 규칙 (순서대로): 빈 행 → 짧은 행(질문 < 2자, 답변 < 5자) → 챗봇 시나리오 표기 답변(`scenario`: 영숫자·밑줄 + `|`로 시작하거나 `|` 포함) → IPv4 형태 포함 행 → 질문 정확 중복 → 질문 bigram Jaccard ≥ 0.6 근사 중복 → `data/faq/exclude_keys.txt`에 적힌 key.
- 이번 실행 통계 (`./scripts/prepare_data.sh` stdout): 탈락 short 2 · scenario 14 · pattern 0 · exact_dup 590 · near_dup 252 · excluded 0 (scenario·exact_dup·near_dup에는 분야별 시트 중복 재집계가 포함된다). 정리 phones 304 · urls 106 · emails 4. 결과 final 575 = 합성 5 + 공개 570, 답변 길이 p50 227 · p95 571 · max 1150자.
- `key` = 원문 질문 기준 sha1 앞 12자리. 익명화 검사(`sanitize-check.sh`)에 걸린 행은 `exclude_keys.txt`에 key를 적어 빼고 다시 실행한다 (금지 단어를 저장소에 쓰지 않고 재현). 현재 제외 0건.
- 행 형식: `{"id", "question", "answer", "source", "category", "key"}`. 서버는 메모리에서 BM25 인덱스를 만든다(인덱스 파일 없음).

## Synthetic data

`data/faq/sample_faq.json` 5건(faq-001~005)은 손으로 작성, 실제 기관 안내 아님. 생성 스크립트·시드는 없다. 수수료·운영 시간 등 문장 속 수치도 예시일 뿐이다. 각 항목은 `id`, `question`, `answer`, `source` 필드를 가진다. `faq.jsonl`에서도 이 5건이 faq-001~005로 맨 앞에 그대로 들어가고(`category` = "합성"), 공개 행은 faq-006부터다. 기존 테스트·음성 픽스처가 faq-001을 기준으로 하기 때문이다.

평가 세트 `tests/fixtures/faq_eval.jsonl`은 `scripts/make_faq_eval.py`(시드 20261022)가 공개 행 중 다른 항목과 겹치지 않는 인텐트명 40개를 골라 규칙 4종으로 변형한다: 각 어절 끝 글자 제거 + "알려주세요", 첫 두 어절 교체 + "어떻게 해요?", 가장 긴 어절 2개 + "궁금해요", 공백 전부 제거 + "?". 여기에 합성 센티널 2건("떼려면/때려면")을 더한다. 사람이 쓴 질문이 아니므로 실제 사용자 발화 정확도를 대표하지 않는다.
