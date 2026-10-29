# 상담원 빌더 API

프론트엔드를 만드는 사람이 이 문서만 보고 화면을 붙일 수 있게 쓴 계약서다.
예시 JSON은 실제 서버(`TestClient`, 음성 합성은 무음 스텁)에서 받은 응답을 그대로 옮겼다. `audio_wav_b64` 같은 긴 값만 `...`로 줄였다.
제품 화면에는 엔진 용어를 쓰지 않는다. 엔진 이야기는 맨 끝 "부록: 내부 구현"에만 있다.

## 1. 개요

- 계정이 없다. 상담원(agent)을 만들면 `agent_id`가 나오고, 그 id를 아는 사람은 누구나 같은 상담원과 대화한다.
- 대화는 세션(session) 단위다. 세션마다 질문 수 상한이 있다.
- 답변은 SSE 스트림으로 문장 단위로 온다. 문장마다 음성(WAV, base64)과 근거가 붙는다.
- 성적표는 비동기 작업이다. 제출하면 `job_id`를 받고 폴링한다.
- 프리셋 상담원 4개는 서버가 켜질 때 만들어지고, 읽기 전용이며 지워지지 않는다.

### 기본 URL

```
http://localhost:8765
```

모든 경로는 이 URL 아래에 붙는다. 서버 실행: `uv run uvicorn app.main:app --host localhost --port 8765`.
기계가 읽는 스키마는 `GET /openapi.json`, 사람이 보는 화면은 `/docs`(FastAPI 기본)에 있다. 다만 SSE 이벤트 모양은 OpenAPI에 없으니 이 문서 5절을 본다.

### 공통 규칙

- 요청·응답 본문은 JSON(UTF-8). 예외: 음성 업로드는 원시 바이트, 턴 응답은 `text/event-stream`.
- 시각은 ISO-8601 UTC 문자열, 초 단위: `"2026-10-23T03:02:01Z"`.
- 시간 길이(`*_ms`)는 밀리초, 소수 1자리로 반올림된 `float`.
- 검색 후보 점수(`score`)는 소수 2자리. 근거 겹침(`overlap`)은 0~1.
- id 형식: 상담원 `ag_` + 12자 16진수(프리셋은 `preset-<preset_id>`), 세션 `s_…`, 턴 `t_…`, 성적표 작업 `sc_…`. 지식 조각 id는 텍스트 입력이면 `c-001`, CSV 입력이면 `q-001`부터.
- 데모 모드(`DEMO_MODE=1`, 공개 데모 서버)에서 비용이 드는 엔드포인트 5개(`POST /api/agents`, `…/turns/stream`, `…/turns/audio-stream`, `…/compare`, `…/scorecards`)는 `X-Demo-Token` 헤더가 필요하다. 값은 `GET /api/demo`(5.14)의 `token`이다. 403 `demo_token_required`가 오면 토큰을 새로 받아 **1회만** 다시 보낸다. 데모 모드가 아니면 `token`이 `null`이고 헤더를 붙이지 않는다.

## 2. 오류 형식

### 2.1 앱 오류 (400·403·404·409·413·415·429·503)

```json
{"detail": {"code": "agent_not_found", "message": "상담원을 찾을 수 없습니다."}}
```

- `code`는 기계용(분기에 쓴다), `message`는 사용자에게 그대로 보여 줘도 되는 한국어 문장.
- `409 scorecard_running`만 `job_id`가 하나 더 붙는다. 이미 돌고 있는 작업의 id다.
- 데모 모드의 `demo_quota_exceeded`·`demo_daily_cap`에는 `kind`·`reset_at`, `temporarily_blocked`에는 `retry_after`가 더 붙는다(2.3).

```json
{"detail": {"code": "scorecard_running", "message": "이 상담원의 성적표를 이미 만들고 있습니다.", "job_id": "sc_e073c84b0a00"}}
```

### 2.2 요청 검증 실패 (422) — 형식이 다르다

필드 타입·길이·허용값이 틀리면 FastAPI 기본 422가 온다. 이때 `detail`은 객체가 아니라 **배열**이다. 화면에서는 `Array.isArray(body.detail)`로 구분한다.

```json
{"detail": [{"type": "literal_error", "loc": ["body", "settings", "tone"], "msg": "Input should be 'friendly' or 'concise'", "input": "angry", "ctx": {"expected": "'friendly' or 'concise'"}}]}
```

`msg`는 영어이거나 서버 내부 문장이라 사용자에게 그대로 보이지 않는 것이 좋다. `loc` 마지막 값(필드 이름)으로 어느 칸이 틀렸는지 표시한다. 422가 나는 대표 경우:

- 설정 값이 허용값 밖(`tone`, `voice`, `answer_length`, `when_unknown`)이거나 글자 수 상한 초과(4절 상한 표)
- `PATCH …/settings`·`compare`의 `a`/`b`에 모르는 필드가 있음 (`extra_forbidden`)
- 질문 `text`·`question`이 비었거나 공백뿐이거나 500자 초과
- `knowledge.kind`가 `text`/`faq_csv`가 아님, `name`이 비었거나 30자 초과
- `GET …/chunks`의 `limit`이 1..200 밖, `offset` < 0
- `POST …/scorecards`의 `n`이 10..30 밖
- `POST …/turns/audio-stream`에 `session_id` 쿼리가 없음

### 2.3 오류 code 전체 (22개)

| HTTP | code | 언제 | 화면 처리 예 |
|---|---|---|---|
| 400 | `knowledge_empty` | 붙여 넣은 텍스트·CSV에 쓸 내용이 없음 | 입력 칸 아래 `message` |
| 400 | `knowledge_bad_csv` | CSV를 읽을 수 없음 | 입력 칸 아래 `message` |
| 413 | `knowledge_too_large` | 텍스트 글자 수, CSV 글자 수 또는 행 수 상한 초과 | 상한을 `GET /api/options`의 `limits`로 미리 안내 |
| 503 | `capacity_full` | 서버에 상담원이 가득 참 | 잠시 뒤 다시 |
| 404 | `agent_not_found` | 상담원 id가 없거나 만료(24시간)됨 | "링크가 만료됐습니다" + 새로 만들기 |
| 403 | `preset_read_only` | 프리셋 상담원을 고치거나 지우려 함 | 프리셋에선 설정 버튼을 숨긴다 |
| 404 | `session_not_found` | 세션 id가 없거나 만료됨, 또는 다른 상담원의 세션 | 새 세션을 열고 다시 묻는다 |
| 429 | `question_limit` | 세션 질문 수를 다 씀 | 남은 질문 0 표시, 새 세션 안내 |
| 503 | `busy` | 동시에 묻는 사람이 너무 많음(대기열 가득) / A·B 비교가 60초 넘게 기다림 / 성적표 대기열 가득 | "잠시 뒤 다시". 질문 수는 차감되지 않는다 |
| 400 | `empty_audio` | 업로드한 녹음이 0바이트 | 다시 녹음 |
| 413 | `audio_too_large` | 녹음이 10 MiB(10,485,760바이트) 초과. 데모 모드에서는 녹음 길이가 `DEMO_MAX_AUDIO_SECONDS_PER_TURN`(20초) 초과도 | 더 짧게 |
| 415 | `unsupported_audio` | WAV·WebM·Ogg·MP4가 아님 | 브라우저 녹음 형식 확인 |
| 409 | `scorecard_running` | 같은 상담원의 성적표가 이미 대기·진행 중 | 응답의 `job_id`로 그 작업을 폴링 |
| 404 | `job_not_found` | 성적표 작업 id가 없거나 만료됨 | 다시 제출 |
| 429 | `demo_quota_exceeded` | (데모 모드) 이 방문자의 오늘 한도를 다 씀. `kind`(`turns`·`audio_seconds`·`agents`·`scorecards`)와 `reset_at`(다음 날 00:00 UTC)이 더 붙는다 | `message` + `reset_at` 안내 |
| 503 | `demo_daily_cap` | (데모 모드) 서버 전체의 오늘 사용량이 소진됨. `kind`·`reset_at`이 더 붙는다 | 내일 다시 |
| 429 | `rate_limited` | (데모 모드) 1분 동안 요청이 너무 많음 | 잠시 뒤 다시 |
| 413 | `payload_too_large` | (데모 모드) 요청 본문이 상한 초과(JSON 512 KiB, 녹음 2 MiB) | 내용을 줄인다 |
| 403 | `demo_token_required` | (데모 모드) `X-Demo-Token`이 없거나 만료·불일치 | `GET /api/demo`로 토큰을 새로 받아 1회 재시도 |
| 403 | `automated_client` | (데모 모드) 스크립트 도구(curl 등)로 보인 비용 요청 | 브라우저에서 이용 |
| 403 | `crawler_blocked` | (데모 모드) 검색·AI 크롤러 `User-Agent`(bot·crawl·spider·GPTBot·ClaudeBot 등). `/health`·`/robots.txt` 외 모든 경로. 위반 횟수에 넣지 않는다 | 브라우저에서 이용 |
| 429 | `temporarily_blocked` | (데모 모드) 비정상 요청이 반복돼 잠시 차단됨. 헤더 `Retry-After`와 `retry_after`(초)가 붙는다 | 나중에 다시 |

스트림 안에서 나는 오류(`no_speech`, `audio_decode_failed`, `internal`)는 HTTP 오류가 아니라 SSE `error` 이벤트로 온다(5절).

## 3. 개인정보

- **음성은 서버 밖으로 나가지 않는다.** 음성 인식과 음성 합성은 이 서버 프로세스 안에서 돈다.
- 설정에서 **요약(`summary`)을 켤 때만** 질문 문장과 그 질문에 맞는 근거 조각 몇 개가 외부 LLM API로 간다. 음성 파일은 가지 않는다. 기본은 꺼짐이다. 서버에 LLM이 설정돼 있지 않으면(`summary_available: false`) 켜도 아무것도 나가지 않는다.
- 올린 문서(텍스트·CSV)는 그 상담원에만 쓰이고 **메모리에만** 있다. 디스크·DB에 저장하지 않는다.
- 상담원과 세션은 만든 뒤 기본 **24시간**(`AGENT_TTL_HOURS`)이 지나면 지워진다. 성적표 결과는 24시간 또는 상담원이 지워질 때까지 남는다.
- **서버를 재시작하면 프리셋을 뺀 모든 상담원·세션·성적표가 사라진다.** 공유 링크도 그때 끊긴다(`agent_not_found`).
- 계정·쿠키·로그인이 없다. 서버는 질문 기록을 따로 쌓지 않는다.

## 4. 상한 (서버 환경변수와 기본값)

| 환경변수 | 기본값 | 뜻 | 화면에서 아는 법 |
|---|---|---|---|
| `AGENT_TTL_HOURS` | 24.0 | 상담원·세션 보존 시간 | `limits.agent_ttl_hours`, `expires_at` |
| `MAX_AGENTS` | 200 | 서버 전체 사용자 상담원 수 (넘으면 `capacity_full`) | - |
| `MAX_TEXT_CHARS` | 20000 | 텍스트 지식 글자 수 | `limits.max_text_chars` |
| `MAX_CSV_ROWS` | 300 | CSV 유효 행 수 (머리행 제외) | `limits.max_csv_rows` |
| `MAX_CSV_CHARS` | 100000 | CSV 전체 글자 수 | `limits.max_csv_chars` |
| `SESSION_MAX_QUESTIONS` | 30 | 세션당 질문 수 (대화 턴·A/B 비교 1회 = 1개) | `limits.max_questions_per_session`, `questions_left` |
| `TURN_CONCURRENCY` | 2 | 동시에 답을 만드는 턴 수 | - |
| `TURN_QUEUE_MAX` | 8 | 답을 기다리는 대기열 길이 (넘으면 `busy`) | SSE `queue` 이벤트 |
| `SCORECARD_QUEUE_MAX` | 4 | 실행 중 1개 외에 기다릴 수 있는 성적표 수 (넘으면 `busy`) | `position` |
| `PRESETS_DIR` | `data/presets` | 프리셋 데이터 폴더 | - |

코드에 고정된 상한 (환경변수 없음, `GET /api/options`의 `limits`에 같은 값이 온다):

| 항목 | 값 | `limits` 키 |
|---|---|---|
| 질문 글자 수 | 500 | `max_question_chars` |
| 상담원 이름 | 30자 (기본 `"내 상담원"`) | - |
| 상담원 호칭(`persona_name`) | 20자 | `max_persona_name_chars` |
| 담당자 안내 문구(`handoff_message`) | 100자 | `max_handoff_message_chars` |
| 피할 주제(`avoid_topics`) | 10개, 각 20자 | `max_avoid_topics`, `max_avoid_topic_chars` |
| 녹음 크기 | 10 MiB | - |
| 성적표 질문 수 `n` | 10..30 (기본 30) | - |

요약 기본값:

| 환경변수 | 기본값 | 뜻 | 화면에서 아는 법 |
|---|---|---|---|
| `AGENT_SUMMARY_DEFAULT` | false | 새 상담원과 프리셋의 `summary` 기본값. 요청·프리셋에 `summary`가 명시되면 그 값이 이긴다 | `defaults.summary`, 프리셋 상담원 `settings.summary` |

### 데모 모드 상한

공개 데모 서버(`DEMO_MODE=1`)에서만 쓰인다. 꺼져 있으면(기본) 이 표의 값은 아무 영향이 없고 응답도 같다.
방문자 한도는 IP로 만든 익명 버킷(원 IP는 저장하지 않음) 기준이고 매일 00:00 UTC에 비워진다. 잔량은 `GET /api/demo`(5.14)의 `remaining`.

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `DEMO_MODE` | false | 데모 모드 켜기 |
| `DEMO_CONTACT` | `""` | 배너에 보일 연락처. 평문으로 내보내지 않고 `GET /api/demo`의 `contact_enc`(난독화)로만 준다 |
| `DEMO_DAILY_TURNS` | 10 | 방문자당 하루 질문 수 (글자·음성 턴 1, A/B 비교 1회 = 2) |
| `DEMO_DAILY_AUDIO_SECONDS` | 200 | 방문자당 하루 녹음 초 |
| `DEMO_DAILY_AGENTS` | 2 | 방문자당 하루 상담원 만들기 수 |
| `DEMO_DAILY_SCORECARDS` | 2 | 방문자당 하루 성적표 수 |
| `DEMO_GLOBAL_DAILY_TURNS` | 500 | 서버 전체 하루 질문 수 (넘으면 `demo_daily_cap`) |
| `DEMO_GLOBAL_DAILY_AUDIO_SECONDS` | 2000 | 서버 전체 하루 녹음 초 |
| `DEMO_GLOBAL_DAILY_AGENTS` | 100 | 서버 전체 하루 상담원 만들기 수 |
| `DEMO_GLOBAL_DAILY_SCORECARDS` | 30 | 서버 전체 하루 성적표 수 |
| `DEMO_RATE_PER_MINUTE` | 30 | 방문자당 1분 `/api/` 요청 수 (넘으면 `rate_limited`) |
| `DEMO_MAX_JSON_BYTES` | 524288 | JSON 본문 상한 512 KiB (넘으면 `payload_too_large`) |
| `DEMO_MAX_AUDIO_BYTES` | 2097152 | 녹음 본문 상한 2 MiB |
| `DEMO_MAX_AUDIO_SECONDS_PER_TURN` | 20 | 녹음 1회 길이 상한 초 (넘으면 413 `audio_too_large`, 차감 없음) |
| `DEMO_TRUSTED_PROXY_HOPS` | 0 | 앞단 프록시 수. 0이면 접속 주소, N이면 `X-Forwarded-For` 오른쪽에서 N번째 |
| `DEMO_FRAME_ANCESTORS` | `'self'` | 이 화면을 iframe으로 넣을 수 있는 출처 (CSP `frame-ancestors`) |
| `DEMO_BOT_GUARD` | true | 봇 대응(아래 3종) 켜기 |
| `DEMO_TOKEN_SECRET` | `""` | 요청 토큰 서명 키. 비면 서버가 켜질 때마다 새로 만든다 |
| `DEMO_TOKEN_TTL_S` | 1800 | 요청 토큰 유효 초 (`token_expires_in`) |
| `DEMO_ABUSE_THRESHOLD` | 10 | 이 횟수만큼 위반(403·413·429)하면 차단 |
| `DEMO_ABUSE_WINDOW_S` | 300 | 위반을 세는 창 초 |
| `DEMO_BLOCK_STEPS` | `600,3600,86400` | 차단할 때마다 늘어나는 차단 초 |
| `DEMO_LLM_DAILY_CALLS` | 500 | 서버 전체 하루 외부 LLM 호출 수. 넘으면 요약 대신 규칙 문장으로 답한다 |

기존 상한과의 관계: 데모 한도를 **먼저** 검사해 차감하고, 그 뒤 기존 상한(`session_not_found`·`question_limit`·`busy`·`capacity_full`·지식 오류 등)에 걸려 거절되면 차감한 만큼 되돌린다. 녹음 초는 녹음 형식 검사(400/413/415)를 통과한 뒤 계산한다. 차감 단위:

| 엔드포인트 | 차감 | 되돌리는 경우 |
|---|---|---|
| `POST /api/agents` | `agents` 1 | 지식 오류(400/413)·`capacity_full`·그 밖의 실패 |
| `…/turns/stream` | `turns` 1 | `session_not_found`·`question_limit`·`busy` |
| `…/turns/audio-stream` | `audio_seconds` 녹음 초(올림) + `turns` 1 | 위와 같음. 길이 초과 413이면 차감하지 않음 |
| `…/compare` | `turns` 2 | `session_not_found`·`question_limit`·`busy` |
| `…/scorecards` | `scorecards` 1 | `agent_not_found`·`scorecard_running`·`busy` |

봇 대응 3종 (`DEMO_BOT_GUARD=true`일 때, `/api/` 요청만):

1. 요청 토큰: 비용 엔드포인트 5개는 `X-Demo-Token`(`GET /api/demo`의 `token`)이 맞아야 한다. 아니면 403 `demo_token_required`.
2. 스크립트 차단: 비용 요청의 `User-Agent`가 비었거나 curl·wget·python-requests 같은 도구면 403 `automated_client`.
3. 반복 위반 차단: 위반이 `DEMO_ABUSE_WINDOW_S` 안에 `DEMO_ABUSE_THRESHOLD`번 쌓이면 `DEMO_BLOCK_STEPS` 순서로 차단하고 429 `temporarily_blocked`(`Retry-After`)를 돌려준다.

크롤러 대응 (데모 모드면 `DEMO_BOT_GUARD`와 관계없이 켜짐):

- `GET /robots.txt`는 두 모드 모두 `text/plain` 본문 `User-agent: *` / `Disallow: /` 를 준다(OpenAPI 스키마에는 없음).
- 모든 응답에 `X-Robots-Tag: noindex, nofollow, noarchive, nosnippet, noimageindex`가 붙는다(데모 모드만).
- 크롤러·AI 에이전트 `User-Agent`는 `/health`·`/robots.txt` 외 모든 경로에서 403 `crawler_blocked`. curl 은 크롤러로 보지 않는다(비용 요청만 `automated_client`).

## 5. 엔드포인트

전체 목록:

| 메서드 경로 | 하는 일 |
|---|---|
| `GET /api/options` | 설정 화면 선택지·기본값·상한 |
| `GET /api/presets` | 프리셋 카드 4장 |
| `POST /api/agents` | 상담원 만들기 |
| `GET /api/agents/{agent_id}` | 상담원 정보 (공유 링크로 열 때) |
| `PATCH /api/agents/{agent_id}/settings` | 설정 바꾸기 |
| `DELETE /api/agents/{agent_id}` | 상담원 지우기 |
| `GET /api/agents/{agent_id}/chunks` | 상담원이 아는 지식 조각 목록 |
| `POST /api/agents/{agent_id}/sessions` | 대화 세션 열기 |
| `POST /api/agents/{agent_id}/turns/stream` | 글자로 묻기 (SSE) |
| `POST /api/agents/{agent_id}/turns/audio-stream` | 말로 묻기 (SSE) |
| `POST /api/agents/{agent_id}/compare` | 같은 질문을 두 설정으로 비교 |
| `POST /api/agents/{agent_id}/scorecards` | 성적표 만들기 시작 |
| `GET /api/scorecards/{job_id}` | 성적표 진행·결과 |
| `GET /api/demo` | 데모 안내·오늘 남은 한도·요청 토큰 |

### 5.0 공통 객체

**Settings** (응답에선 모든 필드가 온다. 요청에선 모두 선택이고, 빠진 필드는 기본값 또는 기존 값 유지)

```json
{"persona_name": "상담원", "tone": "friendly", "voice": "calm_female", "answer_length": "short",
 "when_unknown": "say_unknown", "handoff_message": "담당자에게 문의해 주세요.", "avoid_topics": [], "summary": false}
```

| 필드 | 타입 | 허용값 / 상한 | 화면 문구 |
|---|---|---|---|
| `persona_name` | string | 1..20자 | 이름 |
| `tone` | string | `friendly` \| `concise` | 친절하게 / 간결하게 |
| `voice` | string | `calm_female` \| `bright_female` \| `calm_male` \| `deep_male` | 차분한 여성 / 밝은 여성 / 차분한 남성 / 낮은 남성 |
| `answer_length` | string | `one_sentence`(1문장) \| `short`(최대 2문장) \| `detailed`(최대 4문장) | 한 문장 / 짧게 / 자세히 |
| `when_unknown` | string | `say_unknown` \| `handoff` | 모른다고 말하기 / 담당자 안내 문구 |
| `handoff_message` | string | 1..100자. `when_unknown=handoff`일 때 모르는 질문의 답 | 담당자 안내 문구 |
| `avoid_topics` | string[] | 최대 10개, 각 1..20자. 질문에 들어 있으면 답하지 않는다 | 피할 주제 |
| `summary` | bool | 켜면 근거 조각을 요약해 답한다 (3절 개인정보) | 요약해서 답하기 |

라벨 문구는 하드코딩하지 말고 `GET /api/options`에서 받는다.

**CandidateOut** — 검색 후보. `{"rank": 1, "chunk_id": "q-001", "title": "주차는 어디에 하나요?", "score": 0.74}`

**EvidenceOut** — 문장 근거. `{"chunk_id": "q-001", "title": "주차는 어디에 하나요?", "quote": "지하 1층 주차장을 이용하세요.", "overlap": 1.0}`
`quote`는 근거 조각에서 그 문장과 맞는 부분, `overlap`은 겹치는 정도(1.0 = 그대로 옮김).

**answer_kind** — 답의 종류.

| 값 | 뜻 | 문장 | `candidates` |
|---|---|---|---|
| `grounded` | 지식에서 근거를 찾아 답함 | 근거 조각 문장 (`supported`는 문장마다) | 1~3개 |
| `unknown` | 맞는 근거가 없어 지어내지 않음 | 1문장: `when_unknown`에 따라 `"제가 가진 자료에는 그 내용이 없어 답하기 어렵습니다."` 또는 `handoff_message` | 0~3개 (참고용 검색 결과) |
| `avoided` | 피할 주제에 걸림 | 1문장: `"그 주제는 안내해 드리지 않습니다."` | 항상 `[]` |

`unknown`·`avoided`의 문장은 `supported: false`, `evidence: []`다. 이것은 "근거 없음 경고"가 아니라 의도된 안내이므로 화면에서 `answer_kind`로 구분해 경고 표시를 하지 않는다. 경고는 `answer_kind == "grounded"`인데 `supported == false`인 문장에만 붙인다.

### 5.1 `GET /api/options`

설정 화면을 그릴 때 한 번 부른다. 요청 본문 없음. 오류 없음.

응답 200:

```json
{"answer_length": [{"value": "one_sentence", "label": "한 문장"}, {"value": "short", "label": "짧게"}, {"value": "detailed", "label": "자세히"}],
 "tone": [{"value": "friendly", "label": "친절하게"}, {"value": "concise", "label": "간결하게"}],
 "when_unknown": [{"value": "say_unknown", "label": "모른다고 말하기"}, {"value": "handoff", "label": "담당자 안내 문구"}],
 "voices": [{"value": "calm_female", "label": "차분한 여성", "available": true}, {"value": "bright_female", "label": "밝은 여성", "available": true},
            {"value": "calm_male", "label": "차분한 남성", "available": true}, {"value": "deep_male", "label": "낮은 남성", "available": true}],
 "defaults": {"persona_name": "상담원", "tone": "friendly", "voice": "calm_female", "answer_length": "short", "when_unknown": "say_unknown", "handoff_message": "담당자에게 문의해 주세요.", "avoid_topics": [], "summary": false},
 "limits": {"max_text_chars": 20000, "max_csv_rows": 300, "max_csv_chars": 100000, "max_questions_per_session": 30, "agent_ttl_hours": 24.0,
            "max_avoid_topics": 10, "max_avoid_topic_chars": 20, "max_persona_name_chars": 20, "max_handoff_message_chars": 100, "max_question_chars": 500},
 "summary_available": false, "voice_input_available": false}
```

| 필드 | 뜻 |
|---|---|
| `answer_length`·`tone`·`when_unknown` | 선택지 `{value, label}`. `value`를 보내고 `label`을 보여 준다 |
| `voices[].available` | `false`면 그 목소리를 고를 수 없게 비활성화 |
| `defaults` | 새로 만들기 화면의 초기값 |
| `limits` | 4절 상한. 입력 칸 글자 수 표시·사전 검사에 쓴다 |
| `summary_available` | `false`면 "요약" 스위치를 숨기거나 비활성화 (켜도 `summary_used`가 항상 `false`) |
| `voice_input_available` | `false`면 서버에 음성 인식이 없다. 마이크 버튼을 숨기고 글자 입력만 둔다 |

### 5.2 `GET /api/presets`

첫 화면 카드 4장. 요청 본문 없음. 오류 없음. 각 카드의 `agent_id`로 바로 세션을 열면 된다.

응답 200 (설명 일부 생략 없이 실제 값):

```json
{"items": [
  {"preset_id": "civil-kiosk", "title": "민원 키오스크", "description": "무인 민원 발급기 앞에서 증명서 발급, 전입신고, 여권 같은 민원 절차를 안내합니다. 공개 지자체 챗봇 FAQ 570건과 합성 5건으로 답합니다.",
   "sample_questions": ["주민등록등본 발급에 필요한 게 뭐예요?", "여권 발급 절차를 알려주세요", "인감증명서 대리 발급이 되나요?"], "agent_id": "preset-civil-kiosk", "chunk_count": 575},
  {"preset_id": "restaurant", "title": "식당 주문 안내", "description": "…", "sample_questions": ["영업시간이 어떻게 돼요?", "포장 주문도 되나요?", "키오스크로 주문하는 방법 알려주세요"], "agent_id": "preset-restaurant", "chunk_count": 24},
  {"preset_id": "hospital", "title": "병원 접수 안내", "description": "…", "sample_questions": ["외래 접수 시간이 언제예요?", "진단서는 어디서 발급받나요?", "주차 요금이 얼마예요?"], "agent_id": "preset-hospital", "chunk_count": 24},
  {"preset_id": "office-policy", "title": "사내 규정 Q&A", "description": "…", "sample_questions": ["연차는 며칠 받을 수 있어요?", "재택근무 가능한가요?", "출장비 정산은 어떻게 해요?"], "agent_id": "preset-office-policy", "chunk_count": 24}
]}
```

| 필드 | 뜻 |
|---|---|
| `preset_id` | 카드 식별자 |
| `title`·`description` | 카드 제목·설명 |
| `sample_questions` | 예시 질문 3개 (누르면 바로 묻는 버튼으로 쓰기 좋다) |
| `agent_id` | 이 프리셋 상담원의 id. 다른 엔드포인트에 그대로 쓴다 |
| `chunk_count` | 아는 지식 조각 수 |

### 5.3 `POST /api/agents`

상담원을 만든다. `knowledge.kind`로 입력 종류를 고른다.

요청 (CSV):

```json
{"name": "우리 가게 상담원",
 "knowledge": {"kind": "faq_csv", "csv": "질문,답변\n주차는 어디에 하나요?,지하 1층 주차장을 이용하세요. 두 시간 무료입니다.\n영업시간이 어떻게 되나요?,매일 오전 10시부터 오후 9시까지 영업합니다.\n,빈칸\n"},
 "settings": {"answer_length": "short"}}
```

요청 (텍스트, 이름·설정 생략):

```json
{"knowledge": {"kind": "text", "text": "매장은 매일 10시에 엽니다. 주차는 지하 1층입니다."}}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `name` | string | 아니오 | 1..30자, 기본 `"내 상담원"` |
| `knowledge.kind` | `"text"` \| `"faq_csv"` | 예 | |
| `knowledge.text` | string | kind=text | 붙여 넣은 글. 문단·문장 단위로 조각낸다 |
| `knowledge.csv` | string | kind=faq_csv | CSV 파일 내용 문자열. 앞 두 열이 질문·답변. 첫 행이 `질문,답변` 또는 `question,answer`면 머리행으로 건너뛴다 |
| `settings` | Settings 일부 | 아니오 | 빠진 필드는 기본값 |

CSV 파일 업로드 UI는 브라우저에서 `await file.text()`로 읽어 `csv` 문자열로 보낸다(멀티파트 아님).

응답 201 (`AgentOut`):

```json
{"agent_id": "ag_26e38f11fec9", "name": "우리 가게 상담원", "preset_id": null,
 "settings": {"persona_name": "상담원", "tone": "friendly", "voice": "calm_female", "answer_length": "short", "when_unknown": "say_unknown", "handoff_message": "담당자에게 문의해 주세요.", "avoid_topics": [], "summary": false},
 "chunk_count": 2, "created_at": "2026-10-23T03:02:01Z", "expires_at": "2026-10-24T03:02:01Z",
 "share_path": "/talk?agent=ag_26e38f11fec9",
 "warnings": [{"code": "empty_row", "message": "4행: 질문 또는 답변이 비어 있어 건너뜁니다"}]}
```

| 필드 | 뜻 |
|---|---|
| `agent_id` | 이후 모든 호출에 쓴다 |
| `preset_id` | 사용자 상담원은 `null`, 프리셋이면 프리셋 id |
| `chunk_count` | 만들어진 지식 조각 수 |
| `expires_at` | 지워지는 시각. 프리셋은 `null` |
| `share_path` | 공유 링크 경로(대화 화면 `/talk?agent=<id>`). 기본 URL 뒤에 붙인다. 실제 프론트엔드를 다른 주소에 두면 `agent_id`만 쓰고 링크는 직접 만든다 |
| `warnings` | 만들기는 됐지만 알려 줄 것. 만들 때 응답에만 있고 `GET`에선 항상 `[]` |

`warnings[].code`: `empty_row`(빈 행 건너뜀), `extra_columns`(셋째 열부터 무시), `duplicate_question`(같은 질문은 첫 행만). `message`에 행 번호가 들어 있다.

오류: 400 `knowledge_empty`·`knowledge_bad_csv`, 413 `knowledge_too_large`, 503 `capacity_full`, 422(2.2절).

```json
{"detail": {"code": "knowledge_empty", "message": "지식으로 쓸 내용이 없습니다"}}
{"detail": {"code": "knowledge_too_large", "message": "텍스트는 20000자까지 넣을 수 있습니다"}}
```

### 5.4 `GET /api/agents/{agent_id}`

공유 링크(`?agent=<id>`)로 들어왔을 때 상담원을 연다. 응답 200은 5.3과 같은 `AgentOut`(`warnings: []`).

오류: 404 `agent_not_found`

```json
{"detail": {"code": "agent_not_found", "message": "상담원을 찾을 수 없습니다."}}
```

### 5.5 `PATCH /api/agents/{agent_id}/settings`

보낸 필드만 바꾼다. 모르는 필드가 있으면 422. 지식은 바꿀 수 없다(새로 만든다).

요청:

```json
{"answer_length": "detailed"}
```

응답 200: 바뀐 `AgentOut` (`settings.answer_length`가 `"detailed"`, `warnings: []`).

오류: 404 `agent_not_found`, 403 `preset_read_only`, 422.

```json
{"detail": {"code": "preset_read_only", "message": "프리셋 상담원은 바꿀 수 없습니다."}}
```

이미 열린 세션에도 다음 질문부터 새 설정이 적용된다.

### 5.6 `DELETE /api/agents/{agent_id}`

응답 204 (본문 없음). 그 상담원의 세션·성적표도 더는 쓸 수 없다.

오류: 404 `agent_not_found`, 403 `preset_read_only` (`"프리셋 상담원은 지울 수 없습니다."`).

### 5.7 `GET /api/agents/{agent_id}/chunks`

"상담원이 아는 것" 목록. 쿼리 `offset`(기본 0, ≥0), `limit`(기본 50, 1..200). 근거·후보의 `chunk_id`를 눌렀을 때 원문을 보여 주는 데도 쓴다.

`GET /api/agents/ag_26e38f11fec9/chunks?offset=0&limit=2` 응답 200:

```json
{"total": 2, "items": [
  {"chunk_id": "q-001", "title": "주차는 어디에 하나요?", "text": "지하 1층 주차장을 이용하세요. 두 시간 무료입니다."},
  {"chunk_id": "q-002", "title": "영업시간이 어떻게 되나요?", "text": "매일 오전 10시부터 오후 9시까지 영업합니다."}]}
```

| 필드 | 뜻 |
|---|---|
| `total` | 전체 조각 수 (페이지 수 계산용) |
| `items[].title` | CSV면 질문, 텍스트면 문단 첫머리 |
| `items[].text` | CSV면 답변, 텍스트면 문단 본문 |

오류: 404 `agent_not_found`, 422(쿼리 범위).

### 5.8 `POST /api/agents/{agent_id}/sessions`

대화 화면에 들어갈 때 하나 연다. 요청 본문 없음.

응답 201:

```json
{"session_id": "s_1cb408e7e767", "agent_id": "ag_26e38f11fec9", "questions_left": 30, "expires_at": "2026-10-24T03:02:01Z"}
```

오류: 404 `agent_not_found`.

### 5.9 `POST /api/agents/{agent_id}/turns/stream`

글자로 묻는다. 응답은 SSE(6절).

요청:

```json
{"session_id": "s_1cb408e7e767", "text": "주차 돼요?"}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | 5.8에서 받은 세션 |
| `text` | string | 1..500자, 공백뿐이면 422 |

처리 순서와 오류 (스트림이 시작되기 전이면 일반 JSON 오류):

1. 상담원 확인 → 404 `agent_not_found`
2. 세션 확인·질문 1개 차감 → 404 `session_not_found`, 429 `question_limit`
3. 대기열 입장 → 가득 차면 503 `busy` (**차감한 질문을 되돌린다**)
4. 200 `text/event-stream` 시작. 대기열에 줄을 섰으면 먼저 `queue` 이벤트가 온다. **대기 시간 제한은 없다.** 순서가 올 때까지 1초 간격 안쪽으로 `queue`가 계속 온다.

```json
{"detail": {"code": "session_not_found", "message": "대화 세션을 찾을 수 없습니다. 새 세션을 열어 주세요."}}
{"detail": {"code": "question_limit", "message": "이 세션의 질문 수를 다 썼습니다."}}
{"detail": {"code": "busy", "message": "지금 요청이 많습니다. 잠시 뒤 다시 시도해 주세요."}}
```

사용자가 스트림 도중 연결을 끊으면 서버는 자리를 바로 돌려준다. 이미 차감된 질문은 돌아오지 않는다.

### 5.10 `POST /api/agents/{agent_id}/turns/audio-stream?session_id=<id>`

말로 묻는다. 본문은 **녹음 파일 원시 바이트**(JSON 아님). `Content-Type`은 무엇이든 되고 서버는 파일 앞부분으로 형식을 알아낸다. 지원: WAV, WebM, Ogg, MP4. 브라우저 `MediaRecorder`가 만든 Blob을 그대로 보내면 된다.

```js
await fetch(`/api/agents/${agentId}/turns/audio-stream?session_id=${sid}`, {method: "POST", body: blob});
```

응답: 5.9와 같은 SSE. `meta.transcript`에 알아들은 문장이 온다.

처리 순서 (녹음 검사는 **질문 수를 차감하기 전에** 한다. 400/413/415면 질문이 줄지 않는다):

1. 404 `agent_not_found`
2. 400 `empty_audio`(0바이트) → 413 `audio_too_large`(10 MiB 초과) → 415 `unsupported_audio`(지원 형식 아님)
3. 404 `session_not_found`, 429 `question_limit`
4. 503 `busy` (차감한 질문을 되돌림)
5. 200 SSE. 녹음이 깨졌거나 말소리가 없으면 스트림 안에서 `error` 이벤트(`audio_decode_failed`, `no_speech`)

`session_id` 쿼리가 없으면 422. `GET /api/options`의 `voice_input_available`이 `false`면 이 경로를 부르지 않는다.

### 5.11 `POST /api/agents/{agent_id}/compare`

같은 질문을 설정 A·B로 차례로 답하게 하고 나란히 돌려준다(SSE 아님, 한 번에 JSON). 질문 수는 **1개만** 차감한다. `a`·`b`는 상담원의 현재 설정에 덮어쓸 일부 필드이고 상담원 설정 자체는 바뀌지 않는다. 프리셋 상담원에도 쓸 수 있다.

요청:

```json
{"session_id": "s_1cb408e7e767", "question": "주차 돼요?", "a": {"answer_length": "one_sentence"}, "b": {"answer_length": "detailed"}}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | |
| `question` | string | 1..500자 |
| `a`, `b` | Settings 일부 | 생략하면 `{}` (현재 설정 그대로). 모르는 필드 422 |

응답 200:

```json
{"question": "주차 돼요?",
 "a": {"settings": {"persona_name": "상담원", "tone": "friendly", "voice": "calm_female", "answer_length": "one_sentence", "when_unknown": "say_unknown", "handoff_message": "담당자에게 문의해 주세요.", "avoid_topics": [], "summary": false},
       "answer_kind": "grounded", "answer": "네, 지하 1층 주차장을 이용하세요.", "sentence_count": 1, "char_count": 20, "summary_used": false,
       "candidates": [{"rank": 1, "chunk_id": "q-001", "title": "주차는 어디에 하나요?", "score": 0.74}],
       "sentences": [{"index": 0, "text": "네, 지하 1층 주차장을 이용하세요.", "supported": true,
                      "evidence": [{"chunk_id": "q-001", "title": "주차는 어디에 하나요?", "quote": "지하 1층 주차장을 이용하세요.", "overlap": 1.0}],
                      "audio_wav_b64": "UklGRqQMAABXQVZFZm10...", "speak_ms": 0.0}],
       "timings": {"listen_ms": 0.0, "search_ms": 0.0, "think_ms": 0.0, "speak_ms": 0.0, "first_audio_ms": 0.1, "total_ms": 0.1}},
 "b": {"settings": {"…": "answer_length만 detailed"}, "answer_kind": "grounded", "answer": "네, 지하 1층 주차장을 이용하세요. 두 시간 무료입니다.",
       "sentence_count": 2, "char_count": 32, "summary_used": false, "candidates": ["…"], "sentences": ["…2개"], "timings": {"…": "…"}},
 "diff": {"first_audio_ms": 0.0, "sentence_count": 1, "char_count": 12},
 "notes": ["B의 답이 1문장 깁니다.", "근거 있는 문장: A 1개 · B 2개"],
 "questions_left": 27}
```

| 필드 | 뜻 |
|---|---|
| `a`/`b.settings` | 실제로 쓰인 전체 설정 |
| `a`/`b.answer` | 문장을 이어 붙인 전체 답 |
| `a`/`b.char_count` | 답 글자 수 |
| `a`/`b.sentences[]` | SSE `sentence`와 같고 `elapsed_ms`만 없다 |
| `a`/`b.timings` | SSE `done.timings`에서 `queue_ms`만 없다 |
| `diff` | **B − A**. `first_audio_ms`가 양수면 B가 늦게 시작 |
| `notes` | 화면에 그대로 보여 줄 결론 문장(규칙으로 만든다, 아래) |
| `questions_left` | 이 비교 뒤 남은 질문 수 |

`notes` 규칙 (위에서부터 해당하는 것 모두):
- 첫 음성 차이가 0.2초 이상: `"B가 첫 음성을 {x.x}초 늦게 시작합니다."` / `"… 빨리 시작합니다."`
- 문장 수가 다르면: `"B의 답이 {n}문장 깁니다."` / `"… 짧습니다."`
- 근거 있는 문장 수가 다르면: `"근거 있는 문장: A {x}개 · B {y}개"`
- 셋 다 아니면: `"두 설정의 차이가 작습니다."`

오류: 404 `agent_not_found`·`session_not_found`, 429 `question_limit`, 503 `busy`(대기열이 가득 찼거나 **60초** 기다려도 차례가 안 옴 — 질문을 되돌린다), 422. 대기 중에는 진행 이벤트가 없으니 화면은 "비교 중…" 스피너만 둔다.

### 5.12 `POST /api/agents/{agent_id}/scorecards`

성적표 작업을 대기열에 넣는다. **본문은 생략할 수 있다**(생략 = `{"n": 30, "voice": true}`). 질문 수를 차감하지 않고 세션도 필요 없다.

요청:

```json
{"n": 10, "voice": true}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `n` | int | 10..30, 기본 30. 만들 질문 수의 상한. 지식 조각이 적으면 실제 질문 수(`report.question_count`)가 더 적다 (조각 1개당 질문 2개: 원문 그대로 + 사람 말투) |
| `voice` | bool | 기본 `true`. 질문을 음성으로도 합성해 한 번 더 묻는다. 서버가 음성 채널을 못 쓰면 무시되고 `report.voice_unavailable_reason`에 이유가 온다 |

응답 202:

```json
{"job_id": "sc_e073c84b0a00", "status": "queued", "position": 1}
```

`position`: 대기열 순서(1부터). 이미 실행이 시작됐으면 0.

오류: 404 `agent_not_found`, 409 `scorecard_running`(+`job_id`, 2.1절), 503 `busy`(성적표 대기열 가득), 422.

### 5.13 `GET /api/scorecards/{job_id}`

진행 상황과 결과. 1~2초 간격으로 폴링한다.

응답 200 (`JobOut`, 완료):

```json
{"job_id": "sc_e073c84b0a00", "agent_id": "ag_26e38f11fec9", "status": "done", "progress": {"done": 4, "total": 4},
 "report": {"agent_id": "ag_26e38f11fec9", "question_count": 4, "generated_by": "rules",
            "caveat": "질문은 규칙으로 만든 것이라 실제 사람 말투보다 쉬워 점수가 높게 나올 수 있습니다.",
            "text": {"hits": 4, "total": 4}, "voice": null, "voice_unavailable_reason": "stub_audio",
            "by_style": {"verbatim": {"hits": 2, "total": 2}, "colloquial": {"hits": 2, "total": 2}},
            "first_audio_ms": {"p50": 0.1, "p95": 0.1}, "first_audio_basis": "text", "failures": [], "hints": []},
 "error": null}
```

실패가 있는 `report.failures`·`hints` 항목 모양:

```json
{"qid": "sq-07", "question": "주차 되나여", "style": "colloquial", "channel": "voice",
 "expected": {"chunk_id": "q-012", "title": "주차 안내"}, "got": {"chunk_id": "q-004", "title": "오시는 길"},
 "heard": "주차 되나요", "reason": "misheard"}
{"code": "similar_chunks", "message": "…", "chunk_ids": ["q-004", "q-012"]}
```

| 필드 | 뜻 |
|---|---|
| `status` | `queued` → `running` → `done` \| `failed`. `done`/`failed`면 폴링을 멈춘다 |
| `progress` | `done`/`total`. `total` = 질문 수 × (음성 채널을 쓰면 2, 아니면 1) |
| `report` | `done`일 때만 객체, 그 전엔 `null` |
| `error` | `failed`일 때 `{"code": "internal", "message": "…"}`, 아니면 `null` |
| `report.question_count` | 실제로 물은 질문 수 |
| `report.caveat` | 성적표 옆에 늘 보여 줄 주의 문구 |
| `report.text` / `report.voice` | 글자 질문·음성 질문의 적중 `{hits, total}`. 음성 채널을 못 쓰면 `voice: null` |
| `report.voice_unavailable_reason` | `"stub_audio"`(서버에 실제 음성 합성이 없음) 또는 `null` |
| `report.by_style` | 원문 그대로(`verbatim`)·사람 말투(`colloquial`)별 적중 (글자 질문 기준) |
| `report.first_audio_ms` | 첫 음성까지 시간 `p50`(중앙값)·`p95`(느린 쪽 5%) |
| `report.first_audio_basis` | 위 시간을 음성 질문(`voice`)으로 쟀는지 글자 질문(`text`)으로 쟀는지 |
| `report.failures[]` | 틀린 질문. `channel` `text`\|`voice`, `got`은 못 찾았으면 `null`, `heard`는 음성 질문에서 알아들은 문장(글자 질문은 `null`) |
| `failures[].reason` | `wrong_chunk`(다른 조각을 찾음) · `no_answer`(모른다고 답함) · `misheard`(글자로는 맞았는데 음성으로 틀림) |
| `report.hints[]` | 최대 3개. `code`: `similar_chunks`(비슷한 조각) · `misheard`(음성 인식 오류) · `long_chunks`(조각이 너무 김) · `colloquial_gap`(말투 질문에 약함). `chunk_ids`는 관련 조각(5.7로 원문 표시) |

"적중" = 첫 번째 검색 후보가 그 질문을 만든 조각이고 답 종류가 `grounded`인 경우.

오류: 404 `job_not_found`

```json
{"detail": {"code": "job_not_found", "message": "성적표 작업을 찾을 수 없습니다."}}
```

작업 결과는 24시간 또는 상담원이 지워질 때까지 남는다.

### 5.14 `GET /api/demo`

데모 배너와 요청 토큰. 한도를 차감하지 않는다(데모 모드의 분당 요청 수에는 포함). 데모 모드가 아니어도 200이고, 그때는 `demo_mode: false`에 한도·토큰 필드가 `null`이다.

응답 200 (`DemoOut`, 데모 모드):

```json
{"demo_mode": true, "contact_enc": "bW9jLmVscG1heGVAb21lZA==",
 "notice": "데모 버전입니다. 기능과 사용량이 제한됩니다. 완성된 기술이 필요하면 개발자에게 문의해 주세요.",
 "privacy_notice": "질문 문장은 답 요약을 위해 외부 AI API로 전송됩니다(음성은 전송하지 않습니다).",
 "limits": {"turns": 10, "audio_seconds": 200, "agents": 2, "scorecards": 2},
 "remaining": {"turns": 9, "audio_seconds": 200, "agents": 2, "scorecards": 2},
 "reset_at": "2026-10-29T00:00:00Z", "bucket": "3f9c2a7d10b4e865", "token": "1761620000.0c1d…", "token_expires_in": 1800}
```

| 필드 | 뜻 |
|---|---|
| `demo_mode` | 데모 모드 여부 |
| `contact_enc` | 난독화한 연락처 (`DEMO_CONTACT`). 문자 순서를 뒤집은 문자열의 UTF-8 바이트를 표준 base64 로 감싼 값(`base64(reverse(contact))`, 위 예시는 `demo@example.com`). 비었으면 `null`. 평문 `contact` 키는 없다. 배너는 "연락처 보기" 버튼을 누를 때 base64 디코드 → UTF-8 → 문자 순서 뒤집기로 풀어 보여 준다. 암호화가 아니라 수집기 회피용이다 |
| `notice` | 배너 문구 (고정) |
| `privacy_notice` | 개인정보 안내 문구 (데모 모드가 아니어도 같은 문자열) |
| `limits` | 방문자 하루 한도. 키 `turns`·`audio_seconds`·`agents`·`scorecards`. 데모 아니면 `null` |
| `remaining` | 오늘 남은 양 (키는 `limits`와 같음). 데모 아니면 `null` |
| `reset_at` | 한도가 다시 차는 시각 (다음 날 00:00 UTC). 데모 아니면 `null` |
| `bucket` | 익명 방문자 버킷 id (16자 16진수). 데모 아니면 `null` |
| `token` | `X-Demo-Token`에 넣을 값. 봇 대응이 꺼져 있거나 데모가 아니면 `null`(헤더를 붙이지 않는다) |
| `token_expires_in` | 토큰 유효 초. `token`이 `null`이면 `null` |

서버 전체 사용량·차단 여부는 이 응답에 넣지 않는다.

## 6. SSE 이벤트 (턴 스트림)

`turns/stream`·`turns/audio-stream`의 200 응답은 `Content-Type: text/event-stream`이고, 이벤트마다 아래 두 줄과 빈 줄이다. `data`는 한 줄 JSON이다.

```
event: <name>
data: <json>

```

| event | 횟수 | data |
|---|---|---|
| `queue` | 0회 이상. 대기 중일 때만, 1초 이내 간격 | `{"position": 2}` — 내 앞 순서(1 이상). "앞에 1명" 표시 |
| `meta` | 1 | `{"turn_id", "transcript", "answer_kind", "sentence_count", "candidates": [CandidateOut ≤3, 점수 높은 순], "timings": {"listen_ms", "search_ms", "think_ms"}}` |
| `sentence` | `sentence_count`회, `index` 0부터 순서대로 | `{"index", "text", "supported": bool, "evidence": [EvidenceOut], "audio_wav_b64", "speak_ms", "elapsed_ms"}` |
| `done` | 1 | `{"turn_id", "sentence_count", "answer_kind", "summary_used": bool, "questions_left", "timings": {"listen_ms", "search_ms", "think_ms", "speak_ms", "first_audio_ms", "total_ms", "queue_ms"}}` |
| `error` | 0 또는 1. 나오면 마지막 | `{"code": "no_speech" \| "audio_decode_failed" \| "internal", "message": "…"}` |

순서:

```
[queue]*  →  meta  →  sentence(0) → sentence(1) → … →  done
                 \_____________ 어디서든 _____________/
                                  ↓
                                error  (스트림 끝)
```

실제 스트림 (`"주차 돼요?"`):

```
event: meta
data: {"turn_id":"t_6e1701a35608","transcript":"주차 돼요?","answer_kind":"grounded","sentence_count":2,"candidates":[{"rank":1,"chunk_id":"q-001","title":"주차는 어디에 하나요?","score":0.74}],"timings":{"listen_ms":0.0,"search_ms":0.0,"think_ms":0.0}}

event: sentence
data: {"index":0,"text":"네, 지하 1층 주차장을 이용하세요.","supported":true,"evidence":[{"chunk_id":"q-001","title":"주차는 어디에 하나요?","quote":"지하 1층 주차장을 이용하세요.","overlap":1.0}],"audio_wav_b64":"UklGRqQMAABXQVZFZm10...","speak_ms":0.0,"elapsed_ms":0.3}

event: sentence
data: {"index":1,"text":"두 시간 무료입니다.","supported":true,"evidence":[{"chunk_id":"q-001","title":"주차는 어디에 하나요?","quote":"두 시간 무료입니다.","overlap":1.0}],"audio_wav_b64":"UklGRqQMAABXQVZFZm10...","speak_ms":0.0,"elapsed_ms":0.5}

event: done
data: {"turn_id":"t_6e1701a35608","sentence_count":2,"answer_kind":"grounded","summary_used":false,"questions_left":29,"timings":{"listen_ms":0.0,"search_ms":0.0,"think_ms":0.0,"speak_ms":0.0,"first_audio_ms":0.3,"total_ms":0.6,"queue_ms":0.0}}

```

필드 설명:

| 필드 | 뜻 |
|---|---|
| `transcript` | 글자 질문이면 보낸 그대로, 음성 질문이면 알아들은 문장 |
| `sentence.audio_wav_b64` | 그 문장의 음성. base64 WAV. `new Audio("data:audio/wav;base64," + b64)`로 재생. **`index` 순서대로** 이어서 재생한다 |
| `sentence.speak_ms` | 그 문장 음성을 만드는 데 걸린 시간 |
| `sentence.elapsed_ms` | 턴 시작부터 이 문장 음성이 준비될 때까지 (대기 시간 제외) |
| `done.timings.speak_ms` | 모든 문장 음성 만드는 시간의 합 |
| `done.timings.first_audio_ms` | 턴 시작부터 첫 문장 음성 준비까지 (대기 시간 제외) |
| `done.timings.queue_ms` | 대기열에서 기다린 시간 |
| `done.summary_used` | 이번 답을 실제로 요약해서 만들었는지. 요약을 켰어도 요약이 비어 나오면 원문 문장으로 답하고 `false` |
| `done.questions_left` | 이 턴 뒤 남은 질문 수 |

서버는 투명 모드 여부와 상관없이 항상 모든 필드를 보낸다. 영수증을 보일지 말지는 화면이 정한다.

### 브라우저에서 SSE 읽기 (POST라 `EventSource`는 못 쓴다)

```js
async function ask(agentId, sessionId, text, on) {   // on = {queue, meta, sentence, done, error}: (data) => void
  const r = await fetch(`/api/agents/${agentId}/turns/stream`, {method: "POST",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify({session_id: sessionId, text})});
  if (!r.ok) return on.error((await r.json()).detail);          // 404/429/503/422 (2절)
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "", i, chunk;
  while (!(chunk = await reader.read()).done) {
    buf += chunk.value;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const [ev, data] = buf.slice(0, i).split("\n"); buf = buf.slice(i + 2);
      on[ev.slice(7)]?.(JSON.parse(data.slice(6)));
    }
  }
}
```

## 7. 시나리오별 호출 순서

### 7.1 프리셋으로 바로 체험 (시나리오 1)

1. `GET /api/presets` → 카드 4장(`title`, `description`, `sample_questions`)
2. 카드 클릭 → `POST /api/agents/{preset.agent_id}/sessions` → `session_id`, `questions_left`
3. 질문 → `POST /api/agents/{agent_id}/turns/stream` (마이크면 `…/turns/audio-stream?session_id=`)
4. `meta`에서 자막 자리·후보를, `sentence`마다 자막 한 줄 추가 + 음성 재생 대기열에 넣기, `done`에서 지연 막대·남은 질문 수 갱신

프리셋 화면에서는 설정 바꾸기·지우기 버튼을 숨긴다(`preset_id != null`). 설정 차이를 보고 싶으면 A/B(7.5)는 쓸 수 있다.

### 7.2 내 상담원 만들기 — 60초 셋업 (시나리오 2)

1. `GET /api/options` → 선택지·라벨·기본값·상한으로 폼 그리기 (`voices[].available`, `summary_available`, `voice_input_available` 반영)
2. 사용자가 텍스트 붙여 넣기 또는 CSV 파일 선택(`file.text()`) → 글자 수를 `limits`로 미리 검사
3. `POST /api/agents` → 201이면 `warnings`를 노란 알림으로 보여 주고 대화 화면으로. `share_path`(대화 화면 `/talk?agent=<id>`, 또는 `agent_id`로 만든 링크)를 "공유 링크"로 표시
4. 400/413이면 `detail.message`를 입력 칸 아래에, 422면 `loc`의 필드 칸에 표시
5. `POST /api/agents/{agent_id}/sessions` → 대화 (7.1의 3~4)
6. 공유 링크(`/talk?agent=<id>`)로 들어온 사람: `GET /api/agents/{agent_id}` → 404면 "만료된 링크" 화면, 200이면 세션 열고 대화
7. 설정 수정: `PATCH /api/agents/{agent_id}/settings` (바꾼 필드만)

### 7.3 투명 모드 — 매 턴 영수증 그리기 (시나리오 3)

한 턴에서 모을 것: `meta`(후보, 듣기·검색·생각), 각 `sentence`(문장·근거·`speak_ms`), `done`(첫 음성·전체·대기).

```
👤 {meta.transcript}
🔊 {sentence[0].text}¹ {sentence[1].text}¹          ← supported=false(grounded일 때)인 문장은 "근거 없음" 표시
   ¹ 근거: {evidence.title} — "{evidence.quote}"     ← 같은 chunk_id는 한 번만 각주로
 ⏱ 듣기 {listen_ms} ┤ 검색 {search_ms} ┤ 생각 {think_ms} ┤ 말하기 시작 {sentence[0].speak_ms} │ 첫 음성까지 {first_audio_ms}
 🔎 검색 후보: #{rank} {title} (점수 {score}) · …     ← meta.candidates
```

화면 문구 매핑 (timings 키 → 화면 라벨):

| 키 | 어디서 | 화면 라벨 |
|---|---|---|
| `listen_ms` | `meta.timings`, `done.timings` | 듣기 |
| `search_ms` | `meta.timings`, `done.timings` | 검색 |
| `think_ms` | `meta.timings`, `done.timings` | 생각 |
| `speak_ms` (index 0 문장) | `sentence[0].speak_ms` | 말하기 시작 |
| `speak_ms` | `done.timings` | 말하기(전체 문장 합) — 막대에 넣을 때 |
| `first_audio_ms` | `done.timings` | 첫 음성까지 |
| `total_ms` | `done.timings` | 전체 |
| `queue_ms` | `done.timings` | 대기 (0이 아니면만 표시) |

- 1000 ms 이상은 초로(`1.4s`), 미만은 ms로(`3ms`) 보이면 시나리오 그림과 같다.
- 글자 질문이면 `listen_ms`는 거의 0이다. 이때 "듣기" 칸을 숨겨도 된다.
- `answer_kind`가 `unknown`이면 "자료에 없어 지어내지 않았습니다" 같은 안내를, `avoided`면 "피할 주제" 표시를 영수증에 붙인다. 후보가 `[]`이면 후보 줄을 숨긴다.
- 지연 막대는 `done`이 와야 완성된다. 그 전에는 `meta`의 세 값만 그릴 수 있다.
- `queue` 이벤트가 오면 `"앞에 {position}명"`을 보여 주고, `meta`가 오면 지운다.

### 7.4 성적표 폴링 (시나리오 4)

1. "시험해보기" → `POST /api/agents/{agent_id}/scorecards` (본문 생략 가능) → 202 `{job_id, status, position}`
   - 409 `scorecard_running`이면 `detail.job_id`로 2단계부터 이어 간다
   - 503 `busy`면 "잠시 뒤 다시"
2. `GET /api/scorecards/{job_id}`를 1~2초마다 → `status`가 `queued`면 "대기 중", `running`이면 진행 막대 `progress.done / progress.total`
3. `done` → `report`로 화면:
   - "맞는 근거를 찾음": `text.hits / text.total` (음성이 있으면 `voice.hits / voice.total`도 괄호로)
   - "첫 음성까지": `first_audio_ms.p50` · `p95`
   - "틀린 n개": `failures[]`의 `question` → `got.title` (`reason` 라벨: wrong_chunk 다른 답 / no_answer 답 못 함 / misheard 음성 인식 오류)
   - "개선 힌트": `hints[].message`
   - `caveat`은 늘 표시. `voice`가 `null`이면 "이 서버에서는 음성 질문을 시험하지 않았습니다"
4. `failed` → `error.message` 표시, 다시 시도 버튼
5. 404 `job_not_found`(서버 재시작 등) → 처음부터 다시 제출

### 7.5 A/B 비교 (시나리오 5)

1. 세션이 열려 있어야 한다(질문 1개 차감).
2. 두 설정 고르기 (예: `{"summary": false}` vs `{"summary": true}`, `{"answer_length": "short"}` vs `{"answer_length": "detailed"}`)
3. `POST /api/agents/{agent_id}/compare` → 기다리는 동안 스피너(최대 60초, 넘으면 503 `busy`)
4. 응답으로 좌우 두 칸: 각 칸에 `answer`, `timings.first_audio_ms`, `sentence_count`, `char_count`, 근거 각주. "A 듣기 → B 듣기" 버튼은 각 `sentences[].audio_wav_b64`를 index 순서로 재생
5. 아래에 `notes`를 결론으로 그대로 보여 준다. `diff`는 숫자 배지(+1.2s, −2문장)에 쓴다. 부호는 B − A
6. `questions_left`로 남은 질문 수 갱신

## 부록: 내부 구현

화면 문구에는 쓰지 않는 엔진 이야기. 결과 해석이나 디버깅에만 참고한다.

- **검색(`search_ms`, `candidates`, `score`)**: 상담원마다 지식 조각으로 BM25 키워드 색인을 만든다. `score`는 BM25 점수라 상담원·질문마다 범위가 다르고 절대 기준이 없다. 후보는 top-k(최대 3개)만 내려간다. 질문 단어가 상위 후보에 충분히 덮이지 않으면 `unknown`으로 판정한다.
- **근거(`supported`, `evidence`, `overlap`)**: 답 문장과 후보 조각 문장의 bigram 겹침 비율을 재고 0.5 이상이면 근거로 붙인다. 요약을 끄면 답 문장이 조각 원문 문장이므로 보통 `overlap`이 1.0이다.
- **생각(`think_ms`)**: 요약을 끄면 답 문장을 고르고 자르는 시간뿐이라 거의 0이다. 요약을 켜면 외부 LLM(OpenAI 호환 API, 모델은 서버 `LLM_MODEL` 설정) 호출 시간이 들어간다. temperature 같은 생성 설정은 화면에 노출하지 않는다. LLM이 빈 답을 내거나 실패하면 조각 원문으로 답하고 `summary_used: false`.
- **듣기(`listen_ms`)**: 음성 질문이면 서버 안 STT(`STT_BACKEND`), 글자 질문이면 0에 가깝다. `voice_input_available`은 STT가 스텁(글자 통과)이 아닐 때 `true`다.
- **말하기(`speak_ms`, `audio_wav_b64`)**: 서버 안 TTS(`TTS_BACKEND`)가 문장마다 WAV를 만든다. 스텁 TTS(무음)면 성적표의 음성 채널은 쓰지 않는다(`voice_unavailable_reason: "stub_audio"`). 요약을 켜면 첫 문장 합성을 나머지 요약 생성과 겹쳐 돌려 `first_audio_ms`를 줄인다.
- **대기열**: 턴은 동시에 `TURN_CONCURRENCY`개 실행, 나머지는 `TURN_QUEUE_MAX`개까지 줄을 선다. A/B 비교도 같은 줄을 쓰며 한 자리에서 A·B를 차례로 실행한다. 성적표는 별도 작업 스레드 하나가 순서대로 실행한다.
- **저장**: 상담원·세션·작업은 프로세스 메모리의 딕셔너리다. 만료된 항목은 조회할 때 지운다.
- 코드 위치: 라우트 `app/api/agents.py`, 스키마 `app/api/agent_schemas.py`, 도메인 `app/agents/`, 설정 `app/config.py`.
