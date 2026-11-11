# app/static/studio/vendor

스튜디오 화면(`/studio`, `/studio/app`)이 외부 CDN 없이 쓰는 벤더 자산. 내려받은 날짜: 2026-10-23.

| 파일 | 출처 | 버전 | 라이선스 | SHA-256 |
|------|------|------|----------|---------|
| `tailwind-3.4.16.js` | `https://cdn.tailwindcss.com/3.4.16?plugins=forms,container-queries` | Tailwind CSS Play CDN 3.4.16 (forms, container-queries 플러그인 포함) | MIT | `65a00ffae891994a069ad731ed4ca080b71f9881c6e6cf935a2565e0cff3bddd` |
| `material-symbols.woff2` | Google Fonts CSS2 API `Material Symbols Outlined` (`opsz,wght,FILL,GRAD@20..48,400,0..1,0`, `icon_names=` 아래 목록) 가 돌려준 `fonts.gstatic.com` woff2 | 응답 CSS 의 `v=v380` | Apache-2.0 | `ebbc706bb44dd4f5a4b645b4f132e9221b6f6737cbb9b794398f845494d7016d` |
| `icons.css` | 직접 작성 (`@font-face` 는 로컬 woff2, `.material-symbols-outlined` 기본 스타일) | - | 이 저장소 | - |

## 아이콘 목록 (이 밖의 아이콘은 글리프가 없다)

```
add,arrow_back,arrow_forward,balance,bolt,cancel,chat_bubble_outline,check,check_circle,close,compare_arrows,content_copy,dark_mode,delete,delete_forever,description,download,error,error_outline,expand_less,expand_more,file_download,graphic_eq,help_outline,hourglass_bottom,hourglass_top,info,library_books,light_mode,lightbulb,link,lock,lock_person,menu_book,mic,more_vert,north_east,open_in_new,play_arrow,progress_activity,record_voice_over,refresh,restart_alt,save,schedule,search,search_off,security,send,share,source,speed,stop_circle,tips_and_updates,tune,upload_file,verified_user,volume_up,warning,wifi_off
```

아이콘을 추가하려면 위 목록에 이름을 넣고(알파벳순) 아래 재생성 명령을 다시 돌린다.

## 재생성 명령 (저장소 루트에서)

```bash
curl -sSL -o app/static/studio/vendor/tailwind-3.4.16.js "https://cdn.tailwindcss.com/3.4.16?plugins=forms,container-queries"

NAMES="add,arrow_back,arrow_forward,balance,bolt,cancel,chat_bubble_outline,check,check_circle,close,compare_arrows,content_copy,dark_mode,delete,delete_forever,description,download,error,error_outline,expand_less,expand_more,file_download,graphic_eq,help_outline,hourglass_bottom,hourglass_top,info,library_books,light_mode,lightbulb,link,lock,lock_person,menu_book,mic,more_vert,north_east,open_in_new,play_arrow,progress_activity,record_voice_over,refresh,restart_alt,save,schedule,search,search_off,security,send,share,source,speed,stop_circle,tips_and_updates,tune,upload_file,verified_user,volume_up,warning,wifi_off"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
WOFF=$(curl -sS -A "$UA" "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,400,0..1,0&icon_names=$NAMES" | grep -o 'https://fonts.gstatic.com/[^)]*')
curl -sS -o app/static/studio/vendor/material-symbols.woff2 "$WOFF"
```

User-Agent 가 최신 Chrome 이 아니면 woff2 대신 다른 형식이 올 수 있다.
