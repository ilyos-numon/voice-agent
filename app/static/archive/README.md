# 보관된 옛 화면

보관용이다. 새 기능 추가 금지. 보관 날짜: 2026-10-23.
새 화면은 `app/static/studio/` (`/studio`, `/studio/app`) 이다.

## two-page/ (두 페이지 UI)

| 파일 | 옛 경로 | 옛 라우트 | 대체 화면 |
|------|---------|-----------|-----------|
| home.html | app/static/home.html | `/` | `/studio` (studio.html) |
| home.js | app/static/home.js | `/` 에서 로드 | `/studio` (studio.js) |
| talk.html | app/static/talk.html | `/talk?agent=` | `/studio/app?agent=` (workspace.html) |
| talk.js | app/static/talk.js | `/talk` 에서 로드 | `/studio/app` (ws-core.js, ws-chat.js) |
| talk-tabs.js | app/static/talk-tabs.js | `/talk` 에서 로드 | `/studio/app` (ws-knowledge.js, ws-settings.js, ws-scorecard.js, ws-compare.js) |
| common.js | app/static/common.js | `/`, `/talk` 에서 로드 | `/static/studio/api.js` |
| ui.css | app/static/ui.css | `/`, `/talk` 에서 로드 | Tailwind (`/static/studio/vendor/`, tw-config.js) |

보관 후 주소: `/static/archive/two-page/home.html`, `/static/archive/two-page/talk.html`.
`/` 와 `/talk` 는 이제 307 로 `/studio`, `/studio/app` 에 넘긴다.

## kiosk/ (키오스크 데모)

| 파일 | 옛 경로 | 옛 라우트 | 대체 화면 |
|------|---------|-----------|-----------|
| index.html | app/static/index.html | `/static/index.html` | 없음 (데모·E2E 용으로 보관 경로에서 계속 제공) |
| app.js | app/static/app.js | `/static/index.html` 에서 로드 | 없음 |
| style.css | app/static/style.css | `/static/index.html` 에서 로드 | 없음 |

보관 후 주소: `/static/archive/kiosk/index.html`.
