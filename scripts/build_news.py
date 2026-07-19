# -*- coding: utf-8 -*-
"""
건설 뉴스 브리핑 보드 — 데이터 빌더
GitHub Actions에서 매일 실행되어 data.js 를 갱신한다. (Claude 불필요)

  뉴스  : Google News RSS (무료·키 불필요)
  유가  : Yahoo Finance BZ=F (브렌트유)
  환율  : Yahoo Finance KRW=X, 실패 시 frankfurter.app
  수동  : config.json 의 기준금리·건설공사비지수

출력: data.js (window.NEWS_DATA, 최신이 맨 앞, 최대 30일 보관)
      email.html / notify.txt (알림 메일용)
"""
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# 윈도우 cmd 콘솔은 cp949 라서 em대시(—)나 일부 따옴표를 print 하면 죽는다.
# (기사 제목에 이런 문자가 자주 섞여 들어온다)
# 콘솔 인코딩은 그대로 두고 표현 못 하는 글자만 대체해 크래시를 막는다.
# 파일 저장은 항상 encoding="utf-8" 을 명시하므로 여기 영향을 받지 않는다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_JS = os.path.join(ROOT, "data.js")
CONFIG = os.path.join(ROOT, "config.json")

MAX_ARCHIVE = 30       # 보관 일수
FRESH_DAYS = 4         # 며칠 이내 기사만 채택
UA = {"User-Agent": "Mozilla/5.0 (compatible; HDEC-NewsBoard/1.0)"}
CTX = ssl.create_default_context()

# 카테고리별 검색어와 채택 건수
CATEGORIES = {
    "order": {
        "max": 3,
        "queries": ["현대건설 수주", "건설사 수주", "해외건설 수주", "플랜트 수주"],
    },
    "industry": {
        "max": 3,
        "queries": ["건설업계", "국토교통부 건설 정책", "부동산 대책", "분양 착공"],
    },
    "economy": {
        "max": 2,
        "queries": ["건설 자재 가격", "건설공사비 지수", "기준금리 인상", "원달러 환율"],
    },
    "geo": {
        # 주요 신문사 필터 때문에 후보가 줄어드는 카테고리라 검색어를 넉넉히 둔다
        "max": 2,
        "queries": ["중동 정세 유가", "국제유가", "지정학 리스크 원자재",
                    "유가 급등", "호르무즈 원유", "관세 무역 분쟁"],
    },
}

# 대형 건설사 — 제목에 있으면 상단 배치
MAJORS = ["현대건설", "삼성물산", "현대엔지니어링", "GS건설", "대우건설",
          "DL이앤씨", "포스코이앤씨", "삼성E&A", "롯데건설", "HDC현대산업개발", "SK에코플랜트"]

# 광고/저품질 제외
BLOCK_WORDS = ["분양광고", "협찬", "특별기고", "부고", "인사말"]

# config.json 의 allowedPress 를 담아둔다 (load_config 에서 채움)
ALLOWED_PRESS = []
_press_dropped = {}


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"  ! config.json 읽기 실패({type(e).__name__}) — 기본값 사용")
        return {}


def is_allowed_press(source):
    """주요 신문사만 통과. 목록이 비어 있으면 필터를 끈다."""
    if not ALLOWED_PRESS:
        return True
    s = source.replace(" ", "").lower()
    if not s:
        return False
    for name in ALLOWED_PRESS:
        n = name.replace(" ", "").lower()
        if n and (n in s or s in n):
            return True
    return False


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout, context=CTX).read()


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- 뉴스

def parse_pubdate(s):
    """RFC822 -> aware datetime. 실패하면 None."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except ValueError:
            continue
    return None


def clean_title(title, source):
    """구글뉴스 제목 끝의 ' - 언론사' 제거."""
    t = (title or "").strip()
    if source and t.endswith(" - " + source):
        t = t[: -(len(source) + 3)].strip()
    else:
        t = re.sub(r"\s+-\s+[^-]{2,20}$", "", t).strip()
    # 언론사가 제목 끝에 남긴 구분자 찌꺼기 제거 ("… 홍해 통과 |")
    t = re.sub(r"[\s|·\-–—]+$", "", t).strip()
    return t


def bigrams(title):
    """글자 2-gram 집합.

    단어 단위로 비교하면 '홍해'/'홍해로', '수송'/'수송선' 처럼
    조사·접미사만 다른 같은 사건 기사를 놓친다. 한국어에서는 글자 2-gram 이
    이런 변형에 훨씬 강하다.
    """
    s = re.sub(r"[^가-힣A-Za-z0-9]", "", title)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def is_similar(title, picked_titles):
    """같은 사건을 다룬 기사 걸러내기 - 2-gram 겹침이 절반 이상이면 중복."""
    ta = bigrams(title)
    if not ta:
        return True
    for other in picked_titles:
        tb = bigrams(other)
        if not tb:
            continue
        if len(ta & tb) / min(len(ta), len(tb)) >= 0.5:
            return True
    return False


def search_news(query):
    q = urllib.parse.quote(query)
    url = ("https://news.google.com/rss/search"
           f"?q={q}&hl=ko&gl=KR&ceid=KR:ko")
    try:
        raw = fetch(url)
    except Exception as e:
        log(f"  ! RSS 실패 [{query}]: {type(e).__name__}")
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        log(f"  ! RSS 파싱 실패 [{query}]: {e}")
        return []

    now = datetime.now(timezone.utc)
    out = []
    for item in root.findall(".//item"):
        pub = parse_pubdate(item.findtext("pubDate"))
        if pub is None:
            continue
        age_days = (now - pub).total_seconds() / 86400.0
        if age_days > FRESH_DAYS or age_days < -1:
            continue

        src_el = item.find("source")
        source = (src_el.text if src_el is not None else "") or ""
        if not is_allowed_press(source):
            _press_dropped[source.strip() or "(무기명)"] = \
                _press_dropped.get(source.strip() or "(무기명)", 0) + 1
            continue
        title = clean_title(item.findtext("title"), source)
        if not title or any(w in title for w in BLOCK_WORDS):
            continue
        # 잘린 제목("…에 미국은...")과 너무 짧은 낚시성 제목은 정보가 없어 제외
        if title.endswith(("...", "…", "..")) or len(title) < 18:
            continue

        link = (item.findtext("link") or "").strip()
        if not link.startswith("http"):
            continue

        # 점수: 최신일수록 +, 대형사 언급 +, 검색어 토큰 일치 +
        score = max(0.0, FRESH_DAYS - age_days) * 10
        if any(m in title for m in MAJORS):
            score += 25
        for tok in query.split():
            if tok in title:
                score += 6

        out.append({
            "title": title, "source": source.strip() or "출처",
            "url": link, "pub": pub, "score": score,
        })
    return out


def build_category(key, spec, used_keys):
    log(f"[{key}] 검색 {len(spec['queries'])}건")
    pool = []
    for q in spec["queries"]:
        got = search_news(q)
        log(f"  - {q}: {len(got)}건")
        pool.extend(got)

    pool.sort(key=lambda a: a["score"], reverse=True)

    picked = []
    for art in pool:
        # used_keys 는 카테고리 간, picked 는 카테고리 내 중복 차단
        if is_similar(art["title"], used_keys) or is_similar(art["title"], [p["title"] for p in picked]):
            continue
        picked.append(art)
        if len(picked) >= spec["max"]:
            break
    used_keys.extend(p["title"] for p in picked)

    # 대형 건설사 소식을 카테고리 맨 위로
    picked.sort(key=lambda a: 0 if any(m in a["title"] for m in MAJORS) else 1)

    items = []
    for i, a in enumerate(picked):
        items.append({
            "text": a["title"],
            "source": f"{a['source']} · {a['pub'].astimezone(KST):%m/%d}",
            "url": a["url"],
            # 대형 건설사가 언급된 최상단 기사만 '주목' 표시
            "hot": i == 0 and any(m in a["title"] for m in MAJORS),
        })
    log(f"  => 채택 {len(items)}건")
    return items


# ---------------------------------------------------------------- 지표

def yahoo_quote(symbol):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           "?range=5d&interval=1d")
    d = json.loads(fetch(url))
    r = d["chart"]["result"][0]
    closes = [c for c in r["indicators"]["quote"][0]["close"] if c is not None]
    if not closes:
        raise ValueError("no close data")
    return closes[-1], closes[0]


def indicator_oil():
    try:
        cur, base = yahoo_quote("BZ=F")
        pct = (cur / base - 1) * 100
        return {
            "label": "국제유가 (Brent)", "value": f"{cur:,.1f}", "unit": "$/배럴",
            "delta": f"5일 {pct:+.1f}%",
            "dir": "up" if pct > 0.3 else ("down" if pct < -0.3 else "flat"),
            "note": "Yahoo Finance BZ=F",
        }
    except Exception as e:
        log(f"  ! 유가 실패: {type(e).__name__}")
        return {"label": "국제유가 (Brent)", "value": "-", "unit": "$/배럴",
                "note": "수집 실패", "dir": "flat"}


def indicator_fx():
    try:
        cur, base = yahoo_quote("KRW=X")
        pct = (cur / base - 1) * 100
        return {
            "label": "원/달러 환율", "value": f"{cur:,.0f}", "unit": "원",
            "delta": f"5일 {pct:+.1f}%",
            "dir": "up" if pct > 0.15 else ("down" if pct < -0.15 else "flat"),
            "note": "Yahoo Finance KRW=X",
        }
    except Exception:
        try:  # 예비 경로
            d = json.loads(fetch("https://api.frankfurter.app/latest?from=USD&to=KRW"))
            return {"label": "원/달러 환율", "value": f"{d['rates']['KRW']:,.0f}",
                    "unit": "원", "dir": "flat", "note": f"ECB {d['date']}"}
        except Exception as e:
            log(f"  ! 환율 실패: {type(e).__name__}")
            return {"label": "원/달러 환율", "value": "-", "unit": "원",
                    "note": "수집 실패", "dir": "flat"}


def indicators_manual(cfg):
    """자동 수집이 어려운 지표는 config.json 에서 읽는다."""
    out = []
    for m in cfg.get("manualIndicators", []):
        out.append({
            "label": m.get("label", "-"), "value": str(m.get("value", "-")),
            "unit": m.get("unit", ""), "delta": m.get("delta", ""),
            "dir": m.get("dir", "flat"),
            "note": m.get("note", "") + (f" · {m['asOf']} 기준" if m.get("asOf") else ""),
        })
    return out


# ---------------------------------------------------------------- data.js

def load_archive():
    """기존 data.js 에서 배열만 떼어내 파싱."""
    if not os.path.exists(DATA_JS):
        return []
    try:
        with open(DATA_JS, encoding="utf-8") as f:
            src = f.read()
        m = re.search(r"window\.NEWS_DATA\s*=\s*(\[.*?\])\s*;\s*$", src, re.S)
        if not m:
            log("  ! 기존 data.js 형식을 못 읽음 — 새로 시작")
            return []
        return json.loads(m.group(1))
    except Exception as e:
        log(f"  ! 기존 data.js 파싱 실패({type(e).__name__}) — 새로 시작")
        return []


HEADER = """/* 건설 뉴스 브리핑 보드 — 데이터 파일
 * !! 자동 생성 파일입니다. 직접 고쳐도 다음 실행 때 덮어써집니다.
 * 생성: scripts/build_news.py  (GitHub Actions, 매일 오전)
 * 지표 중 기준금리·공사비지수는 config.json 에서 수동 관리합니다.
 */
"""


def write_data_js(archive):
    body = json.dumps(archive, ensure_ascii=False, indent=2)
    with open(DATA_JS, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER + "window.NEWS_DATA = " + body + ";\n")
    log(f"data.js 작성 완료 - {len(archive)}일치, {os.path.getsize(DATA_JS):,} bytes")


# ---------------------------------------------------------------- 메일

def write_email(entry, board_url):
    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    titles = {"order": "🏆 수주", "industry": "🏗️ 건설업계",
              "economy": "💰 물가·경제", "geo": "🌍 지정학적 이슈"}

    rows = []
    for k, label in titles.items():
        items = entry["categories"].get(k, [])
        if not items:
            continue
        lis = "".join(
            f'<li style="margin:0 0 9px;line-height:1.6">'
            f'<a href="{esc(i["url"])}" style="color:#111;text-decoration:none">{esc(i["text"])}</a>'
            f'<br><span style="color:#888;font-size:12px">{esc(i["source"])}</span></li>'
            for i in items)
        rows.append(
            f'<h3 style="margin:22px 0 10px;font-size:15px;color:#008C46">{label}</h3>'
            f'<ul style="margin:0;padding-left:18px;font-size:14px">{lis}</ul>')

    inds = "".join(
        f'<td style="padding:10px 14px;border:1px solid #e5e5e5;border-radius:8px">'
        f'<div style="font-size:11px;color:#666">{esc(i["label"])}</div>'
        f'<div style="font-size:18px;font-weight:700">{esc(i["value"])}'
        f'<span style="font-size:11px;color:#666"> {esc(i.get("unit",""))}</span></div>'
        f'<div style="font-size:11px;color:#888">{esc(i.get("delta",""))}</div></td>'
        for i in entry["indicators"])

    # 회사망에서 보드판(github.io)이 차단될 수 있으므로
    # 메일 하나만으로 브리핑이 완결되도록 지난주·전망까지 담는다.
    extra = ""
    lw = [x for x in entry.get("lastWeek", []) if x]
    if lw:
        extra += ('<h3 style="margin:22px 0 10px;font-size:15px;color:#008C46">📅 지난주 돌아보기</h3>'
                  '<ul style="margin:0;padding-left:18px;font-size:13px;color:#444">'
                  + "".join(f'<li style="margin:0 0 6px;line-height:1.6">{esc(x)}</li>' for x in lw)
                  + "</ul>")
    if entry.get("outlook"):
        extra += ('<h3 style="margin:22px 0 10px;font-size:15px;color:#008C46">🔭 다음주 전망</h3>'
                  f'<div style="font-size:13px;line-height:1.7;color:#444">{esc(entry["outlook"])}</div>')

    board_btn = (
        f'<div style="margin:26px 0 10px"><a href="{esc(board_url)}" '
        'style="background:#008C46;color:#fff;padding:12px 22px;border-radius:999px;'
        'text-decoration:none;font-weight:700;font-size:14px">보드판 전체 보기 →</a></div>'
    ) if board_url else ""

    html = f"""<div style="font-family:'Malgun Gothic',sans-serif;max-width:640px;margin:0 auto">
  <div style="background:#1F2B40;color:#fff;padding:22px 24px;border-radius:12px">
    <div style="font-size:11px;color:#7ee2b0;letter-spacing:.1em;font-weight:700">오늘의 핵심</div>
    <div style="font-size:17px;font-weight:700;margin-top:8px;line-height:1.5">{esc(entry['headline'])}</div>
    <div style="font-size:12px;color:#9aa4b2;margin-top:12px">{esc(entry['date'])} 기준</div>
  </div>
  <table style="width:100%;margin-top:14px;border-collapse:separate;border-spacing:6px"><tr>{inds}</tr></table>
  {''.join(rows)}
  {extra}
  {board_btn}
  <div style="color:#999;font-size:11px;margin-top:18px">
    자동 발송 · GitHub Actions · 뉴스 출처 Google News</div>
</div>"""

    with open(os.path.join(ROOT, "email.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(ROOT, "notify.txt"), "w", encoding="utf-8") as f:
        f.write(f"[건설브리핑] {entry['headline']}")


# ---------------------------------------------------------------- main

def main():
    global ALLOWED_PRESS
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    log(f"=== 건설 뉴스 보드 빌드 {today} {now:%H:%M} KST ===")

    cfg = load_config()
    ALLOWED_PRESS = cfg.get("allowedPress", [])
    log(f"주요 신문사 필터: {'ON - ' + str(len(ALLOWED_PRESS)) + '개 허용' if ALLOWED_PRESS else 'OFF'}")

    used = []  # 이미 채택한 제목들 — 카테고리 간 중복 방지
    categories = {k: build_category(k, spec, used) for k, spec in CATEGORIES.items()}

    if _press_dropped:
        top = sorted(_press_dropped.items(), key=lambda x: -x[1])[:8]
        log("필터로 제외된 매체 상위: " + ", ".join(f"{s}({c})" for s, c in top))

    total = sum(len(v) for v in categories.values())
    if total == 0:
        log("!! 수집된 기사가 0건 - data.js 를 덮어쓰지 않고 종료")
        log("   (allowedPress 목록이 너무 좁지 않은지 확인해 보세요)")
        return 1

    log("[지표] 수집")
    indicators = [indicator_oil(), indicator_fx()] + indicators_manual(cfg)

    # 헤드라인 = 대형 건설사가 언급된 수주 기사 우선, 없으면 카테고리 우선순위대로
    headline = None
    for k in ("order", "geo", "economy", "industry"):
        for it in categories.get(k, []):
            if any(m in it["text"] for m in MAJORS):
                headline = it["text"]
                break
        if headline:
            break
    if not headline:
        for k in ("order", "geo", "economy", "industry"):
            if categories.get(k):
                headline = categories[k][0]["text"]
                break

    archive = load_archive()
    archive = [e for e in archive if e.get("date") != today]  # 같은 날 재실행 시 교체

    # 지난주 돌아보기 = 직전 7일 아카이브의 헤드라인
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    last_week = [f"{e['date'][5:]} {e['headline']}"
                 for e in archive if e.get("date", "") >= week_ago][:3]

    entry = {
        "date": today,
        "generatedAt": now.strftime("%H:%M"),
        "headline": headline,
        "indicators": indicators,
        "categories": categories,
        "lastWeek": last_week or ["아카이브가 쌓이면 지난주 요약이 자동으로 표시됩니다."],
        "outlook": cfg.get("outlook", ""),
    }

    archive.insert(0, entry)
    archive = archive[:MAX_ARCHIVE]

    write_data_js(archive)
    board_url = os.environ.get("BOARD_URL", "")
    write_email(entry, board_url)
    log(f"완료 - 기사 {total}건, 헤드라인: {headline[:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
