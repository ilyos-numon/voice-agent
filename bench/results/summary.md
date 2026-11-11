| 지표 | before (/api/ask) | after (/api/ask-stream) | 비고 |
|---|---|---|---|
| 첫 음성까지 (p50 / p95) | 4135.6 / 6399.3 ms | 2121.2 / 3100.2 ms | 서버 측. before 는 응답 완료 = total_ms |
| 전체 응답 (p50 / p95) | 4135.6 / 6399.3 ms | 4241.5 / 5984.0 ms | total_ms (after 는 마지막 문장 WAV 까지) |
| STT (p50) | 0.0 ms | 0.0 ms | 글자 입력, STT 미포함 |
| 검색 (p50) | 0.0 ms | 0.0 ms | BM25 |
| LLM (p50) | 1266.0 ms | 1248.2 ms | Qwen qwen3.7-flash (API) |
| TTS (p50) | 2938.8 ms | 3291.1 ms | after 는 문장별 합 |
| TTS RTF (동시 1) | 0.19 | 0.20 | tts_ms / 음성 길이 |
| 동시 4 요청 | 미측정 | 아래 추가 표 (summary-extra.md) | 구성은 표 아래 설명 |
| 검색 적중 (top1 = 질문 id) | 150/150 | 150/150 | |
| 요청 수 (오류) | 150 (0) | 150 (0) | 50 질문 × 3 회 |

클라이언트 측 첫 음성 p50: before 4140.8 ms / after 2124.1 ms
