# 공개 데모 배포 (Google Cloud Run)

이 문서는 공개 데모를 Google Cloud Run 에 올리는 절차다. 자리표시자:

- `<project-id>`: GCP 프로젝트 ID (3단계에서 정한다)
- `<project-number>`: GCP 프로젝트 번호 (`gcloud projects describe <project-id> --format 'value(projectNumber)'`)
- `<gh-user>`: 이 저장소를 가진 GitHub 계정 이름 (`git remote get-url origin` 에서 확인)
- 리전은 `asia-northeast1`, 서비스·Artifact Registry 저장소 이름은 `voice-agent` 로 쓴다.

화면 이름·메뉴 위치는 2026-10 기준이다. 화면이 바뀌어 같은 이름이 없으면 가장 가까운 메뉴를 쓴다.

## 1. 왜 HF Spaces 에서 옮겼나

처음 호스트는 Hugging Face Spaces 무료 등급(CPU basic)이었다(ADR-013). 배포해 보니 Space 가 시작되지 않았고, 계정의 무료 cpu-basic 할당량이 0(limit=0)으로 확인됐다. 무료로는 띄울 수 없고 HF 를 계속 쓰려면 PRO 구독이 필요하다.

Cloud Run 은 카드가 필요하지만 사용량 과금이고, 유휴 시 인스턴스 0 개로 내려가(scale-to-zero) 방문이 적은 데모는 비용이 거의 없다. 관리형 TLS·프록시라 VM 을 운영하지 않는다. 이미지는 호스트 중립(일반 Dockerfile, 포트 8765, 환경변수 설정)이라 코드 수정 없이 옮겼다. 결정 근거는 `docs/decisions.md` ADR-014.

| 호스트 (2026-10 기준, 확인 필요) | 무료 자원 | 카드 | 비고 |
|---|---|---|---|
| **Google Cloud Run (채택)** | 월 180k vCPU-s·360k GiB-s | 필요 | scale-to-zero, 콜드스타트마다 모델 로드 |
| HF Spaces Docker (대안) | 이 계정 무료 할당량 0 | 불필요(PRO 는 구독) | 10절 |
| Oracle Always Free ARM | 2 OCPU·12 GB | 필요 | VM 직접 운영(OS 패치·방화벽·TLS) |
| Render free | 512 MB | 불필요 | 음성 모델이 안 들어감 |

## 2. 무엇이 자동이고 무엇이 사용자 작업인가

- 자동: `main` 에 push 하면 GitHub Actions `deploy-cloudrun` 이 Workload Identity Federation 으로 GCP 에 로그인(키 없음) → 이미지 빌드(`WARM_MODELS=1`, 음성 모델 포함) → Artifact Registry `voice-agent` 에 push → `gcloud run deploy voice-agent` → 서비스 URL 의 `/health` 가 200 이 될 때까지 최대 10분 기다린 뒤 `bucket` 과 URL 을 찍는다. GitHub Variable `GCP_PROJECT_ID` 나 `GCP_WIF_PROVIDER` 가 없으면 배포 단계는 건너뛴다(실패 아님).
- 사용자 작업: 3절 1~5단계. 계정·결제·키는 사용자만 만들 수 있다.
- orchestrator 작업: 4절의 리소스 준비 명령과 5절 GitHub Variables. 사용자가 `gcloud` 로그인을 마친 터미널에서 실행한다.

## 3. 사용자 작업 단계

### 1. GCP 계정과 결제 계정
- 위치: `console.cloud.google.com` 로그인 → `Billing`(결제) → 결제 계정 만들기(카드 등록).
- 확인: `Billing` → `My billing accounts` 에 결제 계정이 "활성"으로 보인다.

### 2. 프로젝트 만들고 결제 연결
- 위치: 위쪽 프로젝트 선택기 → `New project` → 이름 입력 → 만든 프로젝트의 `Billing` → `Link a billing account` 로 1단계 계정을 연결한다.
- 확인: 프로젝트 `Billing` 화면에 연결된 결제 계정 이름이 보인다. 프로젝트 ID 를 `<project-id>` 로 적어 둔다.

### 3. 예산 알림
- 위치: `Billing` → `Budgets & alerts` → `Create budget` → 범위=2단계 프로젝트, 금액=**₩10,000**(월), 알림 기준=**50%·90%·100%**, 이메일 알림 켜기.
- 예산은 알림일 뿐 자동으로 서비스를 멈추지 않는다. 비용은 `max-instances 1`·앱 한도(6·7절)로 묶는다.
- 확인: 예산 목록에 금액과 세 기준이 보인다.

### 4. gcloud 설치·로그인
- 위치: 터미널.

  ```sh
  brew install --cask gcloud-cli
  gcloud init
  ```

  `gcloud init` 에서 1단계 계정으로 로그인하고 2단계 프로젝트를 기본으로 고른다.
- 확인: `gcloud config get-value project` 가 `<project-id>` 를 찍는다.

### 5. LLM 키를 Secret Manager 에 넣기
- 전제: 4절의 API 활성화와 비밀 `llm-api-key` 생성이 먼저 끝나야 한다(활성화 직후 몇 분은 실패할 수 있다).
- 위치: 터미널. 아래를 실행하고 프롬프트 없이 멈춰 있으면 로컬 `.env` 의 `LLM_API_KEY` 값을 붙여 넣고 Enter 를 누른다. 값은 화면에 보이지 않고, 명령 인자·셸 기록에 남지 않는다.

  ```sh
  read -rs K && printf '%s' "$K" | gcloud secrets versions add llm-api-key --data-file=- --quiet ; unset K
  ```

- 키를 채팅·파일·GitHub Variables·Secrets 에 넣지 않는다. 잘못 넣었다면 공급자 콘솔에서 키를 폐기하고 새로 만든다.
- 확인: `gcloud secrets versions list llm-api-key` 에 `enabled` 버전이 하나 보인다(값은 보이지 않는다).

## 4. 리소스 준비 (orchestrator 가 실행)

사용자가 3절 4단계를 마친 터미널에서 실행한다. 이미 있는 리소스는 오류가 나도 넘어간다.

```sh
gcloud config set project <project-id>

# API
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iamcredentials.googleapis.com sts.googleapis.com

# 이미지 저장소 (최신 2개만 남긴다)
gcloud artifacts repositories create voice-agent --repository-format=docker --location=asia-northeast1
# 정리 정책 파일(keep 2 most recent + delete rest)을 만들어 적용:
gcloud artifacts repositories set-cleanup-policies voice-agent --location=asia-northeast1 --policy=<policy.json>

# 비밀 (값은 3절 5단계에서 사용자가 넣는다)
gcloud secrets create llm-api-key --replication-policy=automatic

# 서비스 계정: 런타임(비밀 하나만 읽음) · 배포
gcloud iam service-accounts create va-runtime
gcloud iam service-accounts create va-deployer
gcloud secrets add-iam-policy-binding llm-api-key \
  --member=serviceAccount:va-runtime@<project-id>.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor
gcloud projects add-iam-policy-binding <project-id> \
  --member=serviceAccount:va-deployer@<project-id>.iam.gserviceaccount.com --role=roles/run.admin
gcloud artifacts repositories add-iam-policy-binding voice-agent --location=asia-northeast1 \
  --member=serviceAccount:va-deployer@<project-id>.iam.gserviceaccount.com --role=roles/artifactregistry.writer
gcloud iam service-accounts add-iam-policy-binding va-runtime@<project-id>.iam.gserviceaccount.com \
  --member=serviceAccount:va-deployer@<project-id>.iam.gserviceaccount.com --role=roles/iam.serviceAccountUser

# Workload Identity Federation (이 저장소의 main 브랜치만)
gcloud iam workload-identity-pools create github --location=global
gcloud iam workload-identity-pools providers create-oidc github-oidc --location=global \
  --workload-identity-pool=github --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref \
  --attribute-condition="assertion.repository=='<gh-user>/voice-agent' && assertion.ref=='refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding va-deployer@<project-id>.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member=principalSet://iam.googleapis.com/projects/<project-number>/locations/global/workloadIdentityPools/github/attribute.repository/<gh-user>/voice-agent
```

## 5. GitHub Variables

모두 Variables(평문)다. 키가 아니라 이름·주소뿐이라 Secret 이 필요 없다.

```sh
GH_TOKEN=$(gh auth token -u <gh-user>) gh variable set GCP_PROJECT_ID --body '<project-id>' --repo <gh-user>/voice-agent
GH_TOKEN=$(gh auth token -u <gh-user>) gh variable set GCP_REGION --body 'asia-northeast1' --repo <gh-user>/voice-agent
GH_TOKEN=$(gh auth token -u <gh-user>) gh variable set GCP_WIF_PROVIDER --body 'projects/<project-number>/locations/global/workloadIdentityPools/github/providers/github-oidc' --repo <gh-user>/voice-agent
GH_TOKEN=$(gh auth token -u <gh-user>) gh variable set GCP_DEPLOY_SA --body 'va-deployer@<project-id>.iam.gserviceaccount.com' --repo <gh-user>/voice-agent
GH_TOKEN=$(gh auth token -u <gh-user>) gh variable set GCP_RUNTIME_SA --body 'va-runtime@<project-id>.iam.gserviceaccount.com' --repo <gh-user>/voice-agent
```

- 선택 `DEMO_CONTACT` = 이메일 또는 `https://` 링크. 배너에 보인다. 설정하면 배포 때 Cloud Run 환경변수로 넘어간다(쉼표가 있어도 된다, `|` 는 쓰지 않는다). 비우면 안내 문장만 보인다.
- 확인: `GH_TOKEN=$(gh auth token -u <gh-user>) gh variable list --repo <gh-user>/voice-agent` 에 다섯 이름이 보인다.

### 배포
- `main` 에 push 하거나 `Actions` → `deploy-cloudrun` → `Run workflow`.
- 첫 빌드는 음성 모델 예열(약 0.9 GB 다운로드) 때문에 오래 걸린다.
- 확인: 실행 요약(Summary)에 `Deployed: https://...run.app` 가 찍히고, `curl -s -o /dev/null -w '%{http_code}' "<url>/health"` → `200`. 브라우저로 열면 데모 배너가 보이고, 프리셋에서 질문하면 요약 답이 나온다(이미지 기본 `AGENT_SUMMARY_DEFAULT=1`).
- 추가 확인(프록시 hop 수): `deploy-cloudrun` 의 `Report bucket` 단계가 찍는 `bucket` 과 내 컴퓨터에서 `curl -s "<url>/api/demo"` 의 `bucket` 이 달라야 한다. 같으면 모든 방문자가 한 버킷을 나눠 쓰는 것이므로 환경변수 `DEMO_TRUSTED_PROXY_HOPS` 를 바꿔 본다(이미지 기본 1). `X-Forwarded-For` 를 임의 값으로 붙여 보내도 `bucket` 이 바뀌지 않아야 한다.

## 6. 콜드스타트 (scale-to-zero)

- `--min-instances 0` 이라 방문이 없으면 인스턴스가 0 개로 내려간다. 다음 첫 요청은 컨테이너 시작 + 음성 모델 로드가 끝날 때까지 늦다(1~2분 수준, 확인 필요). `--cpu-boost` 로 시작 중 CPU 를 더 받는다.
- 그동안 화면의 서버 상태 표시는 "확인 중"으로 남는다. 뜬 뒤에는 평소대로 동작한다.
- 인스턴스가 내려가거나 새 배포가 되면 메모리 상태가 모두 지워진다: 사용자가 만든 상담원·세션·성적표, 방문자·전체 한도 카운터, LLM 호출 카운터, 차단 목록. 프리셋은 이미지에 있어 그대로다.
- `--max-instances 1` 은 필수다. 비용 상한이고, 카운터가 메모리에 있어 인스턴스가 둘이면 한도가 나뉜다.

## 7. 한도 조정

- 위치: 콘솔 `Cloud Run` → `voice-agent` → `Edit & deploy new revision` → `Variables & secrets`, 또는

  ```sh
  gcloud run services update voice-agent --region asia-northeast1 --update-env-vars DEMO_DAILY_TURNS=20
  ```

  새 리비전이 뜨며 적용된다(카운터도 0 부터). 워크플로는 `--update-env-vars` 만 쓰므로 직접 넣은 변수는 다음 배포에도 남는다.
- 이름은 `app/config.py` 필드의 대문자다. 기본값과 뜻은 `docs/api.md` 4절 "데모 모드 상한" 표와 `docs/security.md` 3절.
- 자주 바꿀 것: `DEMO_DAILY_TURNS`(방문자 하루 질문, 기본 10), `DEMO_GLOBAL_DAILY_TURNS`(서버 전체 하루 질문, 기본 500), `DEMO_DAILY_AUDIO_SECONDS`(기본 200), `DEMO_RATE_PER_MINUTE`(기본 30).
- 선택 `DEMO_TOKEN_SECRET`: 비우면 서버가 켜질 때마다 새로 만든다(콜드스타트 때 방문자 토큰이 한 번 새로 발급될 뿐 동작은 같다).
- 데모 모드 자체를 끄려면 `DEMO_MODE=0` — 한도·봇 대응·노출 차단이 모두 꺼지므로 공개 서비스에서는 하지 않는다.

## 8. LLM 비용 상한

- 앱 상한: `DEMO_LLM_DAILY_CALLS`(기본 500 = 서버 전체 하루 질문 상한과 같은 값). UTC 하루 단위로 세고, 넘으면 요약 대신 규칙 문장으로 답한다(오류 아님).
- 콜드스타트·재배포 뒤에는 카운터가 0 이 된다. 그래서 최악의 경우는 "하루 기동 횟수 × 상한"이다. DashScope(Model Studio) 콘솔의 지출 알림·상한이 최종 방어선이다 — 설정해 둔다.
- 키가 비었거나 API 가 실패하면 요약 없이 규칙 문장·FAQ 원문으로 답한다. 실패는 화면에서 구분되지 않을 수 있으므로 `Cloud Run` → `voice-agent` → `Logs` 에서 `qwen llm failed` 가 찍히는지 본다(뒤에 예외 종류만 찍히고 키·질문은 찍히지 않는다).
- 모델은 설정 기본 `qwen3.7-flash`(`LLM_MODEL`). 단가는 README "Run" 절의 공식 가격표 인용을 따른다.

## 9. 커스텀 도메인

이 플랜은 도메인을 사거나 연결하지 않는다. 나중에 연결할 때의 둘 중 하나:

- Cloud Run 도메인 매핑: `Cloud Run` → `Manage custom domains` 에서 도메인을 넣고 안내되는 DNS 레코드를 추가한다. 인증서는 Google 이 발급·갱신한다. 리전별 지원 여부를 먼저 확인한다(확인 필요).
- 앞단 프록시(예: Cloudflare): 도메인을 Cloudflare 에 두고 `*.run.app` 주소로 요청을 넘긴다. 인증서는 Cloudflare 가 맡는다.

앞단 프록시가 하나 늘 때마다 `DEMO_TRUSTED_PROXY_HOPS` 를 하나씩 올리고 5절 bucket 확인을 반복한다. 코드에는 호스트 이름이 하드코딩돼 있지 않다(CSP 는 `'self'` 기준). iframe 으로 넣을 때만 `DEMO_FRAME_ANCESTORS` 를 바꾼다.

## 10. 선택 강화책: Cloudflare Turnstile

이 플랜에서는 구현하지 않는다. 지금의 봇 대응(요청 토큰·스크립트 UA 차단·단계적 차단, `docs/security.md` 4절)은 외부 계정 없이 돈다. 실제 헤드리스 브라우저로 화면을 따라오는 공격은 한도로만 묶인다. 그 비용이 문제가 되면 Turnstile 을 붙인다.

- 전제: 커스텀 도메인 연결 후에만 한다(9절). Turnstile 위젯은 등록한 도메인에서만 동작한다.
- 필요한 것: Cloudflare 계정, Turnstile 위젯 등록(도메인 입력) → site key(화면에 넣는 공개 값)와 secret key(서버 검증용).
- 이름(제안): 환경변수 `TURNSTILE_SITE_KEY`, Secret Manager 비밀 `TURNSTILE_SECRET_KEY`. secret key 는 Secret Manager 에만 둔다.
- 붙이는 자리(제안): `GET /api/demo` 토큰 발급 전에 Turnstile 응답을 Cloudflare 검증 API 로 확인한다. CSP 에 Turnstile 스크립트·프레임 출처를 추가해야 한다.
- 별도 플랜·OpenSpec change 로 진행한다.

## 11. 알려진 제약과 대비책

- 로컬 Docker 미검증: 이 개발 머신은 Docker 이미지 pull 이 프록시에서 막혀 컨테이너를 로컬에서 돌려 보지 못했다. 컨테이너 검증은 GitHub Actions `ci` 의 `docker` 작업(빌드 `WARM_MODELS=0`, 스텁 환경으로 실행, `/health` 200·`/docs` 404·uid≠0·`server` 헤더 없음)과 실제 Cloud Run 배포로만 한다.
- 바인드 주소: 이미지는 `--host ""` 로 듣는다. uvicorn 은 `--host ::` 소켓을 IPv6 전용으로 열어 IPv4 연결을 받지 못하므로, 빈 문자열로 IPv4·IPv6 모든 주소에 각각 바인드한다(IP 리터럴 없음). 로그에 `Uvicorn running on http://:8765` 가 보이면 정상이다.
- 배포 뒤 10분 안에 `/health` 200 이 되지 않으면 `deploy-cloudrun` 이 실패로 끝난다. `Cloud Run` → `voice-agent` → `Logs` 에서 시작 단계(모델 로드)인지 설정 오류인지 본다.
- 러너 디스크: 모델이 이미지에 들어가 이미지가 크다. 워크플로가 빌드 전에 러너의 쓰지 않는 도구를 지워 공간을 만든다.
- 처리되지 않은 예외는 보안 헤더가 붙은 500 `internal_error` 로 바뀌고, 로그에는 예외 종류만 남는다(`docs/security.md` 2절).

## 12. 대안: HF Spaces (수동)

HF 무료 등급 할당량이 0 이라 HF PRO 구독이 있을 때만 쓴다. Docker SDK Space 를 만들고 Space Secret `LLM_API_KEY`, GitHub Secret `HF_TOKEN`(Space 쓰기 전용 fine-grained 토큰), GitHub Variables `HF_SPACE_ID`·`DEMO_PUBLIC_URL` 을 넣은 뒤 `Actions` → `deploy-hf` → `Run workflow` 로 수동 배포한다(push 로는 돌지 않는다). 번들은 `scripts/build_space_bundle.sh dist/space` 가 만든다.
