# 공개 데모 배포 (Hugging Face Spaces)

이 문서는 계정만 만들면 그대로 따라 할 수 있게 쓴 배포 절차다. 자리표시자:

- `<hf-user>`: Hugging Face 사용자 이름 (1단계에서 적어 둔다)
- `<space>`: Space 이름 (2단계에서 정한다, 영문 소문자·하이픈)
- `<gh-user>`: 이 저장소를 가진 GitHub 계정 이름 (`git remote get-url origin` 에서 확인)

화면 이름·메뉴 위치는 2026-10 기준이다. 화면이 바뀌어 같은 이름이 없으면 가장 가까운 메뉴를 쓴다.

## 1. 호스팅 비교 (2026-10 보도 기준, 확인 필요)

조사한 자료끼리 수치가 다른 곳이 있다. 가입 전에 각 서비스의 현재 무료 조건을 다시 확인한다.

| 호스트 | 무료 자원 | STT+TTS 메모리 | 수면·콜드스타트 | 카드 | 운영·공격 표면 | 커스텀 도메인 |
|---|---|---|---|---|---|---|
| **HF Spaces Docker (채택)** | 2 vCPU·16 GB·50 GB 비영속 디스크 | 들어감 | 48시간 미사용 시 수면, 깨울 때 컨테이너 시작 + 모델 로드 | 불필요 | 관리형 TLS·프록시, 앱 포트만 열림 | 무료 등급 지원 미확인 |
| Oracle Always Free ARM (대안) | 2 OCPU·12 GB (2026-06 축소 보도) | 들어감 | 없음 | 필요 | VM 직접 운영(OS 패치·방화벽·TLS) — 표면·부담 큼 | 자유 |
| Google Cloud Run | 월 180k vCPU-s·360k GiB-s | 들어감 (메모리 과금) | scale-to-zero, 콜드스타트마다 모델 로드 | 필요 | 관리형, 초과 시 과금 | 가능 |
| Render free | 512 MB·0.1 CPU, 15분 수면 | 안 들어감(스텁만) | 느림 | 불필요 | 관리형 | 가능 |
| Koyeb·Fly.io | 무료 compute 폐지/종료 | - | - | - | - | - |

HF 는 카드 없이, VM 운영 없이 두 음성 모델을 함께 올릴 수 있는 유일한 무료 관리형 선택지였다. 이미지는 호스트 중립(일반 Dockerfile, 포트 8765, 환경변수 설정)이라 Oracle 로 옮기는 일은 설정 변경이다. 결정 근거는 `docs/decisions.md` ADR-013.

## 2. 무엇이 자동이고 무엇이 사용자 작업인가

- 자동: `main` 에 push 하면 GitHub Actions `deploy-hf` 가 `scripts/build_space_bundle.sh dist/space` 로 번들을 만들고 `hf upload` 로 Space 에 올린 뒤 `DEMO_PUBLIC_URL/health` 가 200 이 될 때까지 최대 20분 기다린다. `HF_TOKEN` 이 없으면 배포 단계는 건너뛴다(실패 아님).
- 사용자 작업: 아래 1~9단계. 계정·토큰·키는 사용자만 만들 수 있고, 값은 사용자가 각 화면에 직접 붙여 넣는다.

## 3. 사용자 작업 단계

### 1. Hugging Face 가입
- 위치: `huggingface.co/join` → 받은 이메일 인증 메일의 링크를 누른다.
- 확인: 오른쪽 위 아바타 → 프로필 주소 `huggingface.co/<hf-user>` 의 `<hf-user>` 를 적어 둔다.

### 2. Space 만들기
- 위치: 오른쪽 위 `+ New` → `Space` (또는 `huggingface.co/new-space`). Owner=본인, Space name=영문 소문자·하이픈(`<space>`), SDK=**Docker**, template=**Blank**, Space hardware=**CPU basic (free)**, Visibility=**Public** → `Create Space`.
- SDK 는 반드시 **Docker** 로 고른다. Static 으로 만들면 `Settings` 의 Secret 칸이 막혀 6단계를 할 수 없다.
- 이미 Static 으로 만들었다면: Space 의 `Files` 탭에서 `README.md` 를 열어 맨 위 front matter 를 `sdk: docker` 와 `app_port: 8765` 로 고쳐 커밋한다. 그러면 Docker Space 로 바뀌고 Secret 칸이 열린다. (이후 배포가 `deploy/hf-space/README.md` 로 이 파일을 덮어쓴다.)
- 확인: `huggingface.co/spaces/<hf-user>/<space>` 가 열리고 빈 저장소 안내가 보인다.

### 3. Fine-grained 토큰 만들기
- 위치: 아바타 → `Settings` → `Access Tokens` → `Create new token` → Token type **Fine-grained** → `Repositories permissions` 에서 2단계 Space 를 검색해 추가 → 그 Space 에 쓰기(write) 권한만 체크하고 그 밖의 권한은 모두 해제 → `Create token`.
- 값은 이 화면에서 한 번만 보인다. 채팅·파일·명령줄 인자에 붙이지 않는다.
- **경고: 토큰은 4단계의 GitHub Secret 에만 넣는다.** GitHub Variables 는 평문이라 저장소를 볼 수 있는 누구에게나 보인다. 로컬 `.env` 에도 넣지 않는다 — 앱 `Settings` 가 모르는 키라 서버와 테스트가 시작하지 못하고, 그 오류 메시지에 값이 그대로 찍힌다. 잘못 넣었다면 그 토큰을 `Access Tokens` 에서 지우고(Invalidate) 새로 만든다.
- 확인: 토큰 목록에 방금 정한 이름과 "fine-grained" 표시가 보인다.

### 4. GitHub Secret `HF_TOKEN`
- 위치: 터미널에서 아래를 실행하고, 프롬프트가 나오면 3단계 값을 붙여 넣는다(값을 명령 인자로 쓰지 않는다). 또는 GitHub 저장소 `Settings` → `Secrets and variables` → `Actions` → **`Secrets`** 탭 → `New repository secret`.

  ```sh
  GH_TOKEN=$(gh auth token -u <gh-user>) gh secret set HF_TOKEN --repo <gh-user>/voice-agent
  ```

- 같은 화면의 `Variables` 탭에 넣지 않는다(평문). 이미 넣었다면 그 Variable 을 지우고 3단계에서 토큰을 새로 만든다.
- 확인: `GH_TOKEN=$(gh auth token -u <gh-user>) gh secret list --repo <gh-user>/voice-agent` 에 `HF_TOKEN` 이 보인다(값은 보이지 않는다).

### 5. GitHub Variables `HF_SPACE_ID`·`DEMO_PUBLIC_URL`
- 위치: 터미널(또는 4단계 화면의 `Variables` 탭 → `New repository variable`).

  ```sh
  GH_TOKEN=$(gh auth token -u <gh-user>) gh variable set HF_SPACE_ID --body '<hf-user>/<space>' --repo <gh-user>/voice-agent
  GH_TOKEN=$(gh auth token -u <gh-user>) gh variable set DEMO_PUBLIC_URL --body 'https://<hf-user>-<space>.hf.space' --repo <gh-user>/voice-agent
  ```

  `DEMO_PUBLIC_URL` 끝에 `/` 를 붙이지 않는다.
- 확인: `GH_TOKEN=$(gh auth token -u <gh-user>) gh variable list --repo <gh-user>/voice-agent` 에 두 이름이 보이고, Space 페이지 오른쪽 위 `⋮` → `Embed this Space` 의 Direct URL 이 `DEMO_PUBLIC_URL` 과 같다.

### 6. Space Secret `LLM_API_KEY` (필수)·`DEMO_TOKEN_SECRET` (선택)
- 위치: Space 페이지 `Settings` 탭 → `Variables and secrets` → `New secret`.
  - `LLM_API_KEY` = 로컬 `.env` 의 같은 이름 값. Space 화면에 직접 붙여 넣는다. 저장소·GitHub·CI 에는 넣지 않는다.
  - 선택 `DEMO_TOKEN_SECRET` = `python3 -c 'import secrets;print(secrets.token_hex(32))'` 출력. 비워 두면 서버가 켜질 때마다 새로 만든다(재시작 때 방문자 토큰이 한 번 새로 발급될 뿐 동작은 같다).
- 확인: 목록에 이름만 보이고 값은 가려져 있으며, Space 가 재시작된다.

### 7. Space Variable `DEMO_CONTACT`·`DEMO_FRAME_ANCESTORS` (선택)
- 위치: 같은 화면 `New variable`.
  - `DEMO_CONTACT` = 이메일 또는 `https://` 링크. 배너에 보인다. 비우면 안내 문장만 보인다.
  - 선택 `DEMO_FRAME_ANCESTORS` = `'self' https://huggingface.co` (HF Space 페이지 안 iframe 으로도 보이게 할 때). 기본 `'self'` 는 직접 URL(`*.hf.space`)에서만 열린다.
- 확인: 목록에 이름과 값이 보인다.

### 8. (권장) LLM 지출 상한
- 위치: DashScope(Model Studio) 콘솔의 비용·사용량 알림(또는 예산) 메뉴.
- 앱 쪽 상한은 `DEMO_LLM_DAILY_CALLS`(기본 500회/일)지만 재시작하면 카운터가 0 이 된다. 공급자 콘솔 상한이 최종 방어선이다(6절).
- 확인: 알림 수신 설정(또는 상한 금액)이 저장돼 목록에 보인다.

### 9. 배포
- 위치: orchestrator 에게 "준비 완료"를 알리면 작업 브랜치를 `main` 에 병합·push 한다 → GitHub 저장소 `Actions` 탭의 `deploy-hf` 실행. 직접 할 때는 `Actions` → `deploy-hf` → `Run workflow`.
- 첫 빌드는 음성 모델 예열(`WARM_MODELS=1`, 약 0.9 GB 다운로드) 때문에 오래 걸린다. Space 페이지 `Logs` 탭에서 진행을 본다.
- 확인: `curl -s -o /dev/null -w '%{http_code}' "$DEMO_PUBLIC_URL/health"` → `200`. 브라우저로 열면 데모 배너가 보이고, 프리셋에서 질문하면 요약 답이 나온다(이미지 기본 `AGENT_SUMMARY_DEFAULT=1`).
- 추가 확인(프록시 hop 수): `deploy-hf` 마지막 단계가 찍는 `bucket` 과 내 컴퓨터에서 `curl -s "$DEMO_PUBLIC_URL/api/demo"` 의 `bucket` 이 달라야 한다. 같으면 모든 방문자가 한 버킷을 나눠 쓰는 것이므로 Space Variable `DEMO_TRUSTED_PROXY_HOPS` 를 바꿔 본다(이미지 기본 1). `X-Forwarded-For` 를 임의 값으로 붙여 보내도 `bucket` 이 바뀌지 않아야 한다.

## 4. 수면·콜드스타트

- 무료 Space 는 일정 기간(보도 기준 48시간) 방문이 없으면 잠든다. 다음 방문자가 깨우면 컨테이너 시작 + 음성 모델 로드가 끝날 때까지 첫 화면이 늦게 뜬다. 소요 시간은 배포 후 실측 전이라 적지 않는다.
- 그동안 화면의 서버 상태 표시는 "확인 중"으로 남는다. 깨어난 뒤에는 평소대로 동작한다.
- 수면·재시작은 메모리 상태를 모두 지운다: 사용자가 만든 상담원·세션·성적표, 방문자·전체 한도 카운터, LLM 호출 카운터, 차단 목록. 프리셋은 이미지에 있어 그대로다.

## 5. 한도 조정

- 위치: Space `Settings` → `Variables and secrets` → `New variable`(또는 기존 변수 편집). 저장하면 Space 가 재시작되고 새 값이 적용된다(카운터도 0 부터).
- 이름은 `app/config.py` 필드의 대문자다. 기본값과 뜻은 `docs/api.md` 4절 "데모 모드 상한" 표와 `docs/security.md` 3절.
- 자주 바꿀 것: `DEMO_DAILY_TURNS`(방문자 하루 질문, 기본 10), `DEMO_GLOBAL_DAILY_TURNS`(서버 전체 하루 질문, 기본 500), `DEMO_DAILY_AUDIO_SECONDS`(기본 200), `DEMO_RATE_PER_MINUTE`(기본 30).
- 데모 모드 자체를 끄려면 `DEMO_MODE=0` — 한도·봇 대응·노출 차단이 모두 꺼지므로 공개 Space 에서는 하지 않는다.

## 6. LLM 비용 상한

- 앱 상한: `DEMO_LLM_DAILY_CALLS`(기본 500 = 서버 전체 하루 질문 상한과 같은 값). UTC 하루 단위로 세고, 넘으면 요약 대신 규칙 문장으로 답한다(오류 아님).
- 재시작·수면 뒤에는 카운터가 0 이 된다. 그래서 최악의 경우는 "하루 재시작 횟수 × 상한"이다. 공급자 콘솔의 지출 알림·상한(8단계)이 최종 방어선이다.
- 키가 비었거나 API 가 실패하면 요약 없이 규칙 문장·FAQ 원문으로 답한다. 실패는 화면에서 구분되지 않을 수 있으므로 Space `Logs` 탭에서 `qwen llm failed` 가 찍히는지 본다(뒤에 예외 종류만 찍히고 키·질문은 찍히지 않는다).
- 모델은 설정 기본 `qwen3.7-flash`(`LLM_MODEL`). 단가는 README "Run" 절의 공식 가격표 인용을 따른다.

## 7. 커스텀 도메인

이 플랜은 도메인을 사거나 연결하지 않는다. 나중에 연결할 때의 절차:

1. HF 가 무료 Space 에 커스텀 도메인을 지원하는지 먼저 확인한다(2026-10 미확인).
2. 지원하면: Space `Settings` 의 도메인 메뉴에 도메인을 넣고, 안내되는 CNAME 레코드를 도메인 DNS 에 추가한다. HTTPS 인증서는 HF 가 발급·갱신한다.
3. 지원하지 않으면 둘 중 하나:
   - Cloudflare Worker 프록시: 도메인을 Cloudflare 에 두고 Worker 가 `https://<hf-user>-<space>.hf.space` 로 요청을 넘긴다. 인증서는 Cloudflare 가 맡는다. 앞단 프록시가 하나 늘었으므로 `DEMO_TRUSTED_PROXY_HOPS` 를 다시 맞추고 9단계 bucket 확인을 반복한다.
   - Oracle Always Free VM 으로 이전: 같은 이미지를 띄우고 TLS(예: 리버스 프록시의 자동 인증서)와 방화벽을 직접 운영한다. 앞단 프록시 수에 맞춰 `DEMO_TRUSTED_PROXY_HOPS` 를 정한다.
4. 연결 뒤 GitHub Variable `DEMO_PUBLIC_URL` 을 새 주소로, 필요하면 Space Variable `DEMO_FRAME_ANCESTORS` 를 갱신한다.

코드에는 호스트 이름이 하드코딩돼 있지 않다(CSP 는 `'self'` 기준, 공개 주소는 Variable 로만 쓴다). 그래서 도메인 변경에 코드 수정은 필요 없다.

## 8. 선택 강화책: Cloudflare Turnstile

이 플랜에서는 구현하지 않는다. 지금의 봇 대응(요청 토큰·스크립트 UA 차단·단계적 차단, `docs/security.md` 4절)은 외부 계정 없이 돈다. 실제 헤드리스 브라우저로 화면을 따라오는 공격은 한도로만 묶인다. 그 비용이 문제가 되면 Turnstile 을 붙인다.

- 전제: 커스텀 도메인 연결 후에만 한다(7절). Turnstile 위젯은 등록한 도메인에서만 동작한다.
- 필요한 것: Cloudflare 계정, Turnstile 위젯 등록(도메인 입력) → site key(화면에 넣는 공개 값)와 secret key(서버 검증용).
- 이름(제안): Space Variable `TURNSTILE_SITE_KEY`, Space Secret `TURNSTILE_SECRET_KEY`. secret key 는 Secret 에만 둔다.
- 붙이는 자리(제안): `GET /api/demo` 토큰 발급 전에 Turnstile 응답을 Cloudflare 검증 API 로 확인한다. CSP 에 Turnstile 스크립트·프레임 출처를 추가해야 한다.
- 별도 플랜·OpenSpec change 로 진행한다.

## 9. 알려진 제약과 대비책

- 로컬 Docker 미검증: 이 개발 머신은 Docker 이미지 pull 이 프록시에서 막혀 컨테이너를 로컬에서 돌려 보지 못했다. 컨테이너 검증은 GitHub Actions `ci` 의 `docker` 작업(빌드 `WARM_MODELS=0`, 스텁 환경으로 실행, `/health` 200·`/docs` 404·uid≠0·`server` 헤더 없음)과 실제 Space 배포로만 한다.
- 바인드 주소: 이미지는 `--host ""` 로 듣는다. uvicorn 은 `--host ::` 소켓을 IPv6 전용으로 열어 IPv4 연결(Docker 포트 포워딩·호스트 프록시)을 받지 못하므로, 빈 문자열로 IPv4·IPv6 모든 주소에 각각 바인드한다(IP 리터럴 없음). Space `Logs` 에 `Uvicorn running on http://:8765` 가 보이면 정상이다.
- 배포가 20분 안에 `/health` 200 이 되지 않으면 `deploy-hf` 가 실패로 끝난다. Space `Logs` 탭에서 빌드 단계(모델 다운로드)인지 실행 단계(설정 오류)인지 본다.
- 처리되지 않은 예외는 보안 헤더가 붙은 500 `internal_error` 로 바뀌고, 로그에는 예외 종류만 남는다(`docs/security.md` 2절).
