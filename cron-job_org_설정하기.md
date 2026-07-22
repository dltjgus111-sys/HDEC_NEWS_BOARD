# 정확한 시각에 갱신하기 — cron-job.org 설정 절차

GitHub 자체 예약(`schedule:`)은 대기열에 밀려 **최대 3시간 12분** 지연이 실측됐습니다
(07-20 15:30 예정 → 18:42 실행). cron-job.org 같은 외부 스케줄러는 오차가
**4~40초**라 훨씬 정확합니다.

**방식**: 외부 스케줄러가 정해진 시각에 GitHub API를 호출해 "지금 실행해"라고
신호만 보냅니다. 실제 수집·커밋은 지금과 똑같이 `daily-news.yml`이 합니다.
코드·데이터 구조는 전혀 안 바뀝니다.

> **토큰은 제가 대신 만들 수 없습니다.** 아래 1번은 직접 하셔야 하고,
> 발급된 토큰 값은 저에게 알려주지 마세요. cron-job.org 설정 화면에만 넣으세요.

---

## 1. GitHub 토큰(PAT) 만들기 — 이 저장소 전용, 최소 권한

1. GitHub 우측 상단 프로필 → **Settings**
2. 좌측 맨 아래 **Developer settings**
3. **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
4. 아래처럼 설정
   - **Token name**: `HDEC_NEWS_BOARD 자동 실행용` (아무 이름)
   - **Expiration**: 90일 또는 사용자 정의(너무 길게 잡지 마세요 — 만료되면 다시 발급하시면 됩니다)
   - **Repository access**: **Only select repositories** → `HDEC_NEWS_BOARD` 만 선택
     (전체 저장소 접근 권한을 주지 마세요)
   - **Permissions** → **Repository permissions** → **Actions** = **Read and write**
     (다른 항목은 전부 No access 로 둬도 됩니다)
5. **Generate token** → `github_pat_...` 로 시작하는 값이 딱 한 번 보입니다.
   이 창을 닫으면 다시 못 보니, 바로 2번으로 가서 붙여넣으세요.

---

## 2. cron-job.org 가입 + 작업 등록

1. https://cron-job.org 가입 (무료, 카드 정보 불필요)
2. **CREATE CRONJOB** 클릭
3. 아래 값을 그대로 입력

| 항목 | 값 |
|---|---|
| **Title** | 건설뉴스 아침 갱신 (또는 원하는 이름) |
| **URL** | `https://api.github.com/repos/dltjgus111-sys/HDEC_NEWS_BOARD/actions/workflows/daily-news.yml/dispatches` |
| **Request method** | `POST` |

4. **Advanced** 펼치기 → **Headers** 에 아래 3개 추가

| Header 이름 | 값 |
|---|---|
| `Accept` | `application/vnd.github+json` |
| `Authorization` | `Bearer github_pat_여기에_1번에서_받은_토큰` |
| `X-GitHub-Api-Version` | `2022-11-28` |

5. **Advanced → Request body** (Content-Type: `application/json` 선택 후) 에 입력
   ```json
   {"ref":"main"}
   ```

6. **Schedule** 탭에서 시각 지정
   - **Timezone**을 **Asia/Seoul** 로 맞추면 한국 시각을 그대로 입력하면 됩니다
     (GitHub cron처럼 UTC로 환산할 필요가 없습니다 — 이게 GitHub 대비 장점입니다)
   - 권장 시각 (기존 안내 배너·인수인계 문서의 근거와 동일):
     - **07:00** — 아침 (전날 저녁~새벽 기사 반영)
     - **15:30** 평일만 — 오후 (오전 피크 + 14시 건설 피크 반영)
   - 시각당 하나씩, 총 2개의 cronjob을 만드세요 (같은 URL·헤더·본문, 시각만 다름)

7. **CREATE** 저장

---

## 3. 테스트

cron-job.org 작업 목록에서 방금 만든 작업의 **⋮ 메뉴 → Run now** (또는 Test) 클릭.

- 5초 안에 GitHub 저장소 **Actions 탭**에 새 실행이 뜨면 성공입니다.
- 안 뜨면 **History** 탭에서 응답 코드를 확인하세요.
  - `401` → 토큰이 잘못됐거나 만료. 1번부터 다시.
  - `403` → 토큰 권한이 부족. 1번의 Permissions에서 Actions = Read and write 확인.
  - `404` → URL의 저장소명·파일명 오타.
  - `204` → **성공입니다.** (본문 없이 성공을 뜻하는 정상 응답)

---

## 4. GitHub 자체 예약은 어떻게 되나

`daily-news.yml`에 **하루 1번(05:13 KST) 안전망만** 남겨뒀습니다.
cron-job.org가 통째로 멈추는 날을 대비한 최소한의 보험입니다.
평소엔 cron-job.org가 먼저 돌기 때문에 이 실행은 대개
"변경 없음 — 커밋 생략"으로 조용히 끝납니다. 신경 쓰지 않으셔도 됩니다.

cron-job.org 설정을 마치면 갱신 시각이 사실상 07:00 / 15:30 정각(±40초)이 됩니다.
화면 상단 안내 배너도 상황 보고 다시 단정형 문구로 되돌릴 수 있습니다 — 며칠 지켜보고 알려주세요.

---

## 참고: 왜 무료로 되나

cron-job.org는 15년 넘게 운영된 무료 크론 서비스로, 광고나 카드 등록 없이
작업 개수 제한 없이 씁니다(공정 사용 범위 내). 정확도는 자체 공지 기준
4~40초입니다. 유료로 전환할 필요가 전혀 없습니다.
