# Claude Design 요청문 — 확정된 디자인을 CSS로 뽑기

> **사용법**: 아래 `---` 아래쪽 전체를 복사해서 Claude Design 대화창에 붙여넣으세요.
> 이미 디자인을 확정하신 상태에서, 그 디자인을 **이식 가능한 CSS로 다시 뱉게** 하는 요청문입니다.
> 결과로 나온 CSS를 Claude Code(저)에게 주시면 `index.html`에 바로 넣습니다.

---

지금까지 확정한 디자인을, 이미 만들어져 있는 실제 페이지에 이식하려고 합니다.
**새 화면을 그리지 말고, 확정된 디자인을 아래 규격에 맞춘 CSS로 다시 출력해 주세요.**

## 출력 형식 (이것만 주시면 됩니다)

1. **`:root` 토큰 블록** — 색·타이포·간격·radius·그림자를 CSS 변수로
2. **아래 선택자 목록에 대한 CSS 한 덩어리** — 제가 그대로 붙여넣을 수 있게
3. 폰트를 바꾸셨다면 **폰트 이름과 웹폰트 없이 쓸 대체 스택**

산문 설명서·이미지·목업은 필요 없습니다. **CSS 코드만** 주세요.

## 절대 조건

- **HTML 구조와 클래스명을 바꾸지 마세요.** 아래 선택자가 이미 페이지에 존재합니다.
  새 클래스가 꼭 필요하면 별도로 "추가 필요"라고 표시해 주세요.
- **외부 리소스 금지** — 웹폰트 CDN, 아이콘 폰트, 차트 라이브러리 전부 안 됩니다.
  회사망에서 차단될 수 있어 단일 HTML로 자체 완결되어야 합니다.
  폰트는 Windows 기본 탑재(맑은고딕 등)로 폴백되어도 무너지지 않아야 합니다.
- **카테고리 6색은 CSS에 하드코딩하지 마세요.**
  각 카드에 `--sec`(진한색) / `--secsoft`(연한 배경)가 **인라인으로 주입**됩니다.
  → `var(--sec)`, `var(--secsoft)`로만 참조해 주세요.
- 데스크톱 우선(회사 PC). 본문은 **거의 전부 한글**이라 한글 가독성이 최우선입니다.
- **보드 화면은 스크롤 없이 한 화면**에 들어와야 합니다 (콘텐츠 높이 920px 이내, 1440×900에서도).

## 데이터가 매일 바뀝니다

- 기사 **사진이 없습니다.** 이미지 자리를 쓰는 디자인은 불가. 타이포·색·여백으로만 위계를 만듭니다.
- 제목 길이가 **18자~60자**로 들쭉날쭉합니다. 양 극단에서 카드 높이가 무너지면 안 됩니다.
- 기사 **0건인 카테고리**가 생깁니다 (빈 상태 필요).
- 카드는 **접힘/펼침** 두 상태가 있습니다.

---

# 스타일이 필요한 선택자 전체 목록

## 1. 상단 바
```
.topbar          상단 전체 바
.logo / .logo .mark    로고 + [HDEC] 배지
.viewtabs / .vt / .vt.on   보드·스크랩·통계 탭 (세그먼트 컨트롤)
.tools / .tool / .tool:hover   우측 도구 버튼들 (날짜▾ 복사 인쇄 관리자)
.schedule / .schedule b / .schedule .detail / .schedule .ic
                 "매일 07시·평일 15시30분 갱신" 안내 배너
```

## 2. 헤더 (오늘의 핵심) — 눈길이 가장 먼저 닿는 곳
```
.hero                    헤더 영역 전체
.hero .kicker            "오늘의 핵심" 작은 라벨
.hero h1                 헤드라인 (가장 큰 글자)
.hero .hook              후킹 배지 — "오늘 가장 많이 다뤄진 이슈 · 16개 언론사 보도"
.hero .hook .cat         그 안의 카테고리 이름
.hero .hook:empty        후킹이 없는 날 (숨김 처리)
.hero .sub               "2026.7.19 (일) · 18:04 갱신 · 뉴스 15건"
.stats                   지표 4칸 묶음
.stat / .stat .k / .stat .v / .stat .v span / .stat .n
                         지표 1칸: 이름 / 값 / 단위 / 비고
.stat .d / .d.up / .d.down / .d.flat
                         등락 — 상승 빨강, 하락 파랑 (한국 금융 관례, 반대로 하지 마세요)
```

## 3. 카테고리 카드 — **이 화면의 핵심입니다**
```
.grid                    카드 6개가 한 줄 (좁아지면 카드 폭 223px까지 내려갑니다)
.card                    카드 1장. --sec / --secsoft 가 여기 주입됩니다
.card-head               카드 머리 (카테고리 이름 줄)
.card-head .ic / .nm / .cnt    아이콘 / 이름 / 건수
.lead                    대표 기사 블록
.lead h3                 대표 기사 제목  ← 223px 폭에서 44자가 읽혀야 합니다
.lead .meta              "뉴시스 · 07/19"
.lead .go / .go:hover    "원문 →" 링크
.cov / .cov.solo / .cov.multi
                         신뢰도 배지. solo="단독", multi="16개 언론사 보도"
                         ★ 둘 다 부정적으로 보이면 안 됩니다.
                           단독이 나쁜 게 아니라 건설 뉴스는 원래 대부분 단독입니다.
.hotbadge                대형 건설사 언급 기사 표시
.more / .more:hover / .more .cx / .card.open .more .cx
                         "2건 더 ▼" 펼침 버튼 (.cx 는 열렸을 때 회전하는 화살표)
.rest / .card.open .rest 펼쳤을 때 나오는 나머지 기사 목록
.rest .row / .row p / .row a / .row .meta / .row:last-child
.empty                   기사 0건인 카테고리의 빈 상태
```

## 4. 오늘의 키워드
```
.kwbar / .kwbar .t / .kwbar .tag    "오늘의 키워드" + 태그들
.kw / .kw .kwtop / .kwtop .nm / .kwtop .mx / .kwtop input   (관리자 편집용)
```

## 5. 하단 2단
```
.bottom / .foot          하단 영역
.panel / .panel h3 / .panel ol / .panel ol li / .panel .cap    지난주 돌아보기
.panel.fc / .fc h3 / .fc p                                     다음주 전망 (강조 배경)
.note / .note code       안내 문구
```

## 6. 스크랩 화면
```
.scrapbar / .scrapacts   상단 필터 + 액션 줄
.chipline / .fchip / .fchip.on / .fchip .sw    카테고리 필터 칩 (.sw = 색 스와치)
.scgroup / .scgroup > .gh     날짜별 묶음 + 그 머리말
.scitem                  스크랩 1건. --sec 주입됨 (왼쪽 세로선이 카테고리 색)
.scitem h4 / .body / .m / .m a / .del / .del:hover
.scempty                 스크랩 0건
.scrapbtn / :hover / .done    기사에 붙는 [스크랩] 버튼 (관리자만 보임)
```

## 7. 통계 화면 — 차트 3종
```
.stgrid / .stwide        차트 배치
.hbar / .track / .fill / .lb / .vl     카테고리별 가로막대
.hours / .h / .h .b / .h .t / .h.peak .b    24시간 발행 히스토그램
.lchart / .lchart svg / .peak               일자별 추이 선그래프
.cap / .tblnote          차트 아래 설명
```
**차트 규칙** (지켜주세요)
- 모든 점에 숫자 라벨 금지 — **첫·끝·최댓값만**
- 축·그리드는 흐리게, 이중축 금지
- 24시간 막대는 **단일 색** (높이로 이미 크기를 표현하므로 색으로 또 표현하지 않음)

## 8. 관리자 모달
```
.mask / .mask.hide       배경 딤
.dlg / .dlg h2 / .dlg .lead / .dlg label / .dlg textarea
.dlg input:focus, .dlg textarea:focus
.dlgfoot                 하단 버튼 줄
.btn / .btn.primary / .btn.ghost / .btn:hover
```

## 9. 공통
```
.wrap                    콘텐츠 폭 컨테이너
.view / .view.on         화면 전환 (한 번에 하나만 표시)
.toast / .toast.show     하단 알림 토스트
```

---

# 우선순위

전부 다 못 주시면 **1 → 2 → 3 순서**로만 주셔도 됩니다.

1. `:root` 토큰 + `.card` 계열 (카드가 화면의 80%입니다)
2. `.hero` 계열 (헤드라인·후킹 배지·지표)
3. 나머지

# 마지막으로

색을 바꾸셨다면 **바꾼 6색 hex를 따로 적어주세요.**
현재 팔레트는 색약 검증(OKLab ΔE, Machado 2009)을 통과한 조합이라,
바뀌면 Claude Code 쪽에서 검증기를 다시 돌려야 합니다.
