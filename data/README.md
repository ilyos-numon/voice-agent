# Data: voice-agent

This project uses public or synthetic data only. Raw downloads go to data/raw/ (ignored by git). Processed files go to data/processed/.

## Sources

| Dataset | Source URL | License | Version or date | Subset used |
|---|---|---|---|---|
| 합성 FAQ 샘플 | 이 저장소 | CC0 | 2026-10-22 | 5건 |

## Download

없음. 이번 단계는 저장소에 들어 있는 합성 샘플(`data/faq/sample_faq.json`)만 쓴다. 공개 FAQ 다운로드 스크립트는 후속 태스크에서 추가한다.

## Preprocessing

없음. `app/pipeline/stubs.py`의 `load_faq`가 JSON을 그대로 읽는다.

## Synthetic data

`data/faq/sample_faq.json` 5건(faq-001~005)은 손으로 작성, 실제 기관 안내 아님. 생성 스크립트·시드는 없다. 수수료·운영 시간 등 문장 속 수치도 예시일 뿐이다. 각 항목은 `id`, `question`, `answer`, `source` 필드를 가진다.
