# 공개 데모 보안

공개 데모(`DEMO_MODE=1`, 컨테이너 이미지 기본)에서 무엇을 열고 무엇을 막는지 정리한다. 로컬 기본(`DEMO_MODE` 꺼짐)에서는 보안 헤더만 켜지고 나머지는 꺼진다. 배포 절차는 `docs/deploy.md`, 결정 근거는 `docs/decisions.md` ADR-013.

## 1. 노출 엔드포인트 (화이트리스트)

데모 모드에서는 아래 메서드·경로만 라우팅까지 간다(`app/demo/security.py` `ALLOWLIST`). 그 밖은 라우팅 전에 404(`{"detail":"Not Found"}`)다. 403 이 아니라 404 라서 무엇이 숨겨져 있는지 알려 주지 않는다. GET 허용 경로는 HEAD 도 허용하고, `.`·`..` 경로 조각은 항상 거절한다.

| 메서드 | 경로 | 비용 요청(토큰·UA 검사) |
|---|---|---|
| GET | `/health` | - |
| GET | `/`, `/talk`, `/studio`, `/studio/app` | - |
| GET | `/static/studio/…` | - |
| GET | `/api/demo`, `/api/options`, `/api/presets` | - |
| GET | `/api/agents/{id}`, `/api/agents/{id}/chunks` | - |
| GET | `/api/scorecards/{id}` | - |
| POST | `/api/agents` | 예 |
| POST | `/api/agents/{id}/sessions` | - |
| POST | `/api/agents/{id}/turns/stream` | 예 |
| POST | `/api/agents/{id}/turns/audio-stream` | 예 |
| POST | `/api/agents/{id}/compare` | 예 |
| POST | `/api/agents/{id}/scorecards` | 예 |
| PATCH | `/api/agents/{id}/settings` | - |
| DELETE | `/api/agents/{id}` | - |

숨겨지는 것: 1차 키오스크 `/api/ask*`, `/static/archive/…`, `/docs`·`/redoc`·`/openapi.json`. `routes.py` 는 바꾸지 않고 미들웨어로만 막는다.

## 2. 응답 헤더와 이유 (모든 모드에서 켜짐)

| 헤더 | 값 | 이유 |
|---|---|---|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob: data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors <DEMO_FRAME_ANCESTORS>` | 외부 출처 스크립트·연결 차단(XSS 피해 축소). 화면은 인라인 `<script>` 가 없고 외부 출처를 쓰지 않는다. `'unsafe-inline'` 은 Tailwind 런타임이 `<style>` 을 넣어서 스타일에만 허용 |
| `X-Content-Type-Options` | `nosniff` | 업로드·응답의 형식 추측 실행 방지 |
| `Referrer-Policy` | `no-referrer` | 공유 링크의 상담원 id 가 다른 사이트로 새지 않게 |
| `Permissions-Policy` | `microphone=(self), camera=(), geolocation=()` | 마이크는 이 출처에서만, 카메라·위치는 끔 |
| `Cross-Origin-Opener-Policy` | `same-origin` | 다른 창과 브라우징 문맥 분리 |
| `Strict-Transport-Security` | `max-age=31536000` | HTTPS 일 때만(직접 https 이거나, 신뢰 프록시가 있고 `X-Forwarded-Proto` 오른쪽 값이 https) |
| `server` | 없음 | 서버 소프트웨어 이름을 알리지 않음(`--no-server-header`, CI `docker` 작업이 확인) |

- 앱이 같은 이름의 헤더나 `Access-Control-Allow-Origin` 을 붙여도 미들웨어가 지우고 위 값으로 바꾼다(CORS 미허용).
- 처리되지 않은 예외는 보안 헤더가 붙은 500 `{"detail":{"code":"internal_error","message":"서버 오류가 발생했습니다."}}` 로 바뀐다. 로그에는 예외 종류 이름만 남고 스택·요청 내용은 응답에 나가지 않는다.
- HF 페이지 안 iframe 으로 보이게 하려면 `DEMO_FRAME_ANCESTORS` 에 HF 출처를 넣는다(`docs/deploy.md` 7단계). 기본 `'self'`.

## 3. 한도 (기본값 근거 `app/config.py`)

방문자 한도는 익명 버킷(5절) 기준, 매일 00:00 UTC 에 비워진다. 서버 전체 한도는 방문자 수와 관계없는 하루 총량이다. 재시작하면 둘 다 0 부터 다시 센다.

| 항목 | 방문자·하루 | 서버 전체·하루 | 넘으면 |
|---|---|---|---|
| 질문(글자·음성 1, A/B 1회=2) | `DEMO_DAILY_TURNS` 10 | `DEMO_GLOBAL_DAILY_TURNS` 500 | 429 `demo_quota_exceeded` / 503 `demo_daily_cap` |
| 녹음 초 | `DEMO_DAILY_AUDIO_SECONDS` 200 | `DEMO_GLOBAL_DAILY_AUDIO_SECONDS` 2000 | 같음 |
| 상담원 만들기 | `DEMO_DAILY_AGENTS` 2 | `DEMO_GLOBAL_DAILY_AGENTS` 100 | 같음 |
| 성적표 | `DEMO_DAILY_SCORECARDS` 2 | `DEMO_GLOBAL_DAILY_SCORECARDS` 30 | 같음 |
| 외부 LLM 호출 | - | `DEMO_LLM_DAILY_CALLS` 500 | 규칙 문장으로 답(오류 아님) |

| 항목 | 값 | 넘으면 |
|---|---|---|
| `/api/` 요청 수 | `DEMO_RATE_PER_MINUTE` 30/분/방문자 | 429 `rate_limited` |
| JSON 본문 | `DEMO_MAX_JSON_BYTES` 524288 (512 KiB) | 413 `payload_too_large` |
| 녹음 본문 | `DEMO_MAX_AUDIO_BYTES` 2097152 (2 MiB) | 413 `payload_too_large` |
| 녹음 1회 길이 | `DEMO_MAX_AUDIO_SECONDS_PER_TURN` 20초 | 413 `audio_too_large`(차감 없음) |

기존 상한(`MAX_AGENTS`·`SESSION_MAX_QUESTIONS`·대기열 등, `docs/api.md` 4절)은 그대로 함께 적용된다. 데모 한도를 먼저 차감하고, 기존 상한에 걸리면 되돌린다.

## 4. 봇 대응 (`DEMO_BOT_GUARD`, 기본 켜짐, `/api/` 요청만)

| 장치 | 동작 | 막는 것 | 못 막는 것 |
|---|---|---|---|
| 요청 토큰 | `GET /api/demo` 가 버킷에 묶인 HMAC 토큰(`DEMO_TOKEN_TTL_S` 1800초)을 주고, 비용 요청 5종은 `X-Demo-Token` 이 맞아야 한다. 아니면 403 `demo_token_required` | 화면 흐름 없이 비용 엔드포인트를 바로 부르는 스크립트, 다른 네트워크에서 훔친 토큰 재사용 | 먼저 `/api/demo` 를 부르고 토큰을 붙이는 스크립트(→ 한도·레이트·차단에 걸림) |
| 스크립트 UA 차단 | 비용 요청의 `User-Agent` 가 비었거나 curl·wget·python-requests·httpx·aiohttp·Go·okhttp·Java·node-fetch·axios·scrapy·httpie·Postman 등이면 403 `automated_client` | 기본 설정 그대로 쓰는 도구 | UA 를 브라우저로 위장한 스크립트, 헤드리스 브라우저 |
| 단계적 차단 | 403·413·429 응답을 버킷별로 `DEMO_ABUSE_WINDOW_S` 300초 창에서 세고 `DEMO_ABUSE_THRESHOLD` 10회에 도달하면 `DEMO_BLOCK_STEPS` 600→3600→86400초 차단(단계는 UTC 하루 유지). 차단 중엔 모든 `/api/` 가 429 `temporarily_blocked` + `Retry-After` | 한도·토큰을 계속 두드리는 반복 시도 | 버킷(IP)을 계속 바꾸는 공격(→ 서버 전체 한도에 걸림) |

- 헤드리스 브라우저로 화면을 정상적으로 따라오는 공격은 사람과 구별하지 않는다. 그 비용은 방문자·서버 전체 한도와 LLM 일일 상한으로만 묶인다. 더 강한 사람 확인은 도메인 연결 뒤의 선택 강화책 Cloudflare Turnstile(`docs/deploy.md` 8절, 미구현).
- `/health`·`/api/demo` 는 비용 요청이 아니라 curl 로도 열린다(상태 확인·버킷 확인용).
- NAT 뒤 사용자는 한 버킷을 나눈다. 같은 네트워크의 한 사람이 남용하면 다른 사람도 최소 10분 막힐 수 있다(데모라서 받아들임).

## 5. 정보 최소화·식별·개인정보

- `GET /api/demo` 는 이 방문자의 한도·잔량·버킷 id·토큰만 준다. 서버 전체 사용량, 전체 한도 소진 여부, LLM 예산, 차단 여부는 넣지 않는다.
- 식별은 IP 만 쓴다(쿠키·계정 없음). 버킷 = 프로세스마다 새로 만드는 솔트(`secrets.token_hex(16)`) + IP 의 해시. IPv6 는 /64 로 묶는다. 원 IP 는 저장하지 않고, 재시작하면 솔트가 바뀌어 이전 버킷과 이어지지 않는다.
- 클라이언트 주소는 `X-Forwarded-For` 오른쪽에서 `DEMO_TRUSTED_PROXY_HOPS`(이미지 기본 1) 번째 값이다. 클라이언트가 앞에 붙인 값은 쓰이지 않는다.
- 컨테이너는 access log 를 끈다(`--no-access-log`). 요청 경로·IP 가 로그에 쌓이지 않는다.
- 올린 문서·상담원·세션은 메모리에만 있고 기본 24시간 뒤, 또는 재시작 때 사라진다.

## 6. LLM 데이터 흐름

- 외부로 나가는 것: 요약이 켜진 턴의 질문 문장과 검색된 근거 조각 몇 개 → DashScope 국제 엔드포인트(`LLM_BASE_URL`), 모델 `qwen3.7-flash`.
- 나가지 않는 것: 음성(STT·TTS 는 컨테이너 안에서 돈다), IP·버킷 id, 올린 문서 전체.
- 이미지 기본 `AGENT_SUMMARY_DEFAULT=1` 이라 데모에서는 요약이 기본 켜짐이고, 배너가 외부 AI 전송을 한 줄로 알린다.
- 키 `LLM_API_KEY` 는 Space Secret 에만 있다. 저장소·이미지(ENV·ARG)·CI·로그 어디에도 없다. CI 와 데모 E2E 는 `LLM_BACKEND=stub` 로 키 없이 돈다. 실패 로그는 `qwen llm failed: <예외 종류>` 만 남긴다.
- 키가 없거나 실패하거나 일일 상한에 닿으면 규칙 문장으로 답한다.

## 7. 업로드 처리

- 녹음: 본문 크기 제한(데모 2 MiB) → 앞 바이트 검사(sniff)로 WAV·WebM·Ogg·MP4 만 허용(아니면 415 `unsupported_audio`) → 메모리에서 디코드 → 길이 검사(20초). 디스크에 쓰지 않는다.
- 지식(텍스트·CSV): JSON 본문 512 KiB 와 글자·행 수 상한(`docs/api.md` 4절) 안에서 메모리에만 둔다.

## 8. 위협 모델

| 위협 | 대응 |
|---|---|
| 남용(무료 자원·LLM 비용 소진) | 방문자·서버 전체 일일 한도, LLM 일일 호출 상한, 공급자 콘솔 지출 상한(사용자 설정) |
| DoS(요청 폭주·큰 본문) | 분당 요청 제한, 본문 크기 제한(라우팅 전), 기존 동시 턴·대기열 상한, 단계적 차단. 대규모 분산 공격은 HF 앞단에 맡긴다(WAF/CDN 없음) |
| 스크립트 직접 호출 | 요청 토큰, 스크립트 UA 차단, 단계적 차단 |
| XSS | CSP(`script-src 'self'`, 외부 연결 차단), 인라인 스크립트 없음, `nosniff` |
| 클릭재킹 | CSP `frame-ancestors`(기본 `'self'`) |
| 키 유출 | 키는 Space Secret 에만, CI 미참조, gitleaks 전체 이력 검사, `scripts/ci_hygiene.sh`(추적 `.env` 금지·키 모양 문자열 금지), 로그에 예외 종류만 |
| 공급망 | `uv.lock` 고정 설치(`--frozen`), GitHub Actions 는 커밋 SHA 로 고정, CI `audit` 작업 `pip-audit --strict`, 배포 도구 버전 고정 |
| IP 스푸핑(`X-Forwarded-For`) | 오른쪽 N hop 만 신뢰. 배포 뒤 버킷 비교로 hop 수 확인(`docs/deploy.md` 9단계) |
| 숨은 엔드포인트 탐색 | 화이트리스트 밖 404, API 문서 비노출, `server` 헤더 없음 |
| 컨테이너 권한 | uid 1000 비루트 사용자로 실행(CI 가 uid≠0 확인) |

## 9. pip-audit 무시 정책

- CI `audit` 작업은 런타임 의존성(`uv export --no-dev --extra stt --extra tts`)을 `pip-audit --strict` 로 검사하고, 보고가 있으면 실패한다. 현재 무시 목록은 없다.
- 고칠 수 있는 버전이 있으면 무시하지 않고 올린다.
- 고칠 버전이 없고 이 앱의 사용 경로와 무관하다고 검토한 경우에만 `--ignore-vuln <ID>` 를 추가한다. 그때 이 절에 ID·이유·검토 날짜·다시 볼 날짜를 표로 남긴다.
