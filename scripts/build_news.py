# -*- coding: utf-8 -*-
"""
건설 뉴스 브리핑 보드 — 데이터 빌더
GitHub Actions에서 매일 실행되어 data.js 를 갱신한다. (Claude 불필요)

  뉴스  : Google News RSS (무료·키 불필요)
  유가  : Yahoo Finance BZ=F (브렌트유)
  환율  : Yahoo Finance KRW=X, 실패 시 frankfurter.app
  수동  : config.json 의 기준금리·건설공사비지수

출력: data.js (window.NEWS_DATA, 최신이 맨 앞, 최대 7일 보관)
      email.html / notify.txt (알림 메일용)
"""
import json
import os
import re
import ssl
import sys
import time
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

MAX_ARCHIVE = 7        # 보관 일수 (일주일치만 — data.js 가 무한정 커지지 않게)
FRESH_DAYS = 4         # 며칠 이내 기사만 채택
UA = {"User-Agent": "Mozilla/5.0 (compatible; HDEC-NewsBoard/1.0)"}
CTX = ssl.create_default_context()

# 카테고리별 검색어와 채택 건수.
# config.json 의 searchKeywords 가 있으면 그쪽이 우선하고, 없으면 아래 값을 쓴다.
DEFAULT_CATEGORIES = {
    "order": {
        "label": "수주", "max": 3,
        "queries": ["현대건설 수주", "건설사 수주", "해외건설 수주", "플랜트 수주"],
    },
    "competitor": {
        "label": "경쟁사", "max": 3,
        "queries": ["삼성물산 건설", "GS건설", "대우건설", "DL이앤씨", "포스코이앤씨",
                    "현대엔지니어링", "롯데건설", "HDC현대산업개발", "SK에코플랜트"],
    },
    "trend": {
        "label": "핵심상품 트렌드", "max": 3,
        "queries": ["데이터센터 건설", "양수발전", "해상풍력", "수전해 그린수소",
                    "원자력 발전소", "SAF 지속가능항공유", "SMR 소형모듈원자로", "건설 로보틱스"],
    },
    "industry": {
        "label": "건설업계", "max": 2,
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
_pool_titles = []   # 키워드 추출용 - 필터를 통과한 후보 기사 제목 전체
_pool_hours = []    # 통계용 - 후보 기사들의 발행 시각(KST 시)


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
    # 제목 맨 앞 말머리 태그 제거 ("[기업]", "[종목Pick]", "[모닝 리포트]" 등 섹션 라벨).
    # 짧은 태그만( ]안 12자 이하), 그리고 떼고 나서 충분히 남을 때만( 12자 이상) 벗긴다.
    m = re.match(r"^\s*\[[^\]]{1,12}\]\s*", t)
    if m and len(t) - len(m.group()) >= 12:
        t = t[m.end():].strip()
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
        src_el = item.find("source")
        art = make_article(
            raw_title=item.findtext("title"),
            source=(src_el.text if src_el is not None else "") or "",
            link=(item.findtext("link") or "").strip(),
            pub=parse_pubdate(item.findtext("pubDate")),
            query=query, now=now,
        )
        if art:
            out.append(art)
    return out


# 빙은 한국어 결과를 MSN 재배포본으로 준다. 그래서 언론사가 '비즈워치 on MSN' 처럼 붙어 나온다.
# 이걸 그대로 두면 구글의 '비즈워치'와 다른 언론사로 세어져 교차보도 수가 부풀고,
# 신뢰도 배지(N개사 보도)가 거짓말을 하게 된다. 반드시 꼬리를 떼서 맞춰야 한다.
_MSN_TAIL = re.compile(r"\s+on\s+MSN\s*$", re.I)


def normalize_source(s):
    return _MSN_TAIL.sub("", (s or "").strip()).strip()


def make_article(raw_title, source, link, pub, query, now):
    """RSS 한 건을 공통 규칙으로 걸러 기사 dict 를 만든다(구글·빙 공용).
    통과 못 하면 None."""
    if pub is None:
        return None
    age_days = (now - pub).total_seconds() / 86400.0
    if age_days > FRESH_DAYS or age_days < -1:
        return None

    source = normalize_source(source)
    if not is_allowed_press(source):
        _press_dropped[source or "(무기명)"] = _press_dropped.get(source or "(무기명)", 0) + 1
        return None
    title = clean_title(raw_title, source)
    if not title or any(w in title for w in BLOCK_WORDS):
        return None
    # 잘린 제목("…에 미국은...")과 너무 짧은 낚시성 제목은 정보가 없어 제외
    if title.endswith(("...", "…", "..")) or len(title) < 18:
        return None
    if not link.startswith("http"):
        return None

    # 점수: 최신일수록 +, 대형사 언급 +, 검색어 토큰 일치 +
    score = max(0.0, FRESH_DAYS - age_days) * 10
    if any(m in title for m in MAJORS):
        score += 25
    for tok in query.split():
        if tok in title:
            score += 6
    return {"title": title, "source": source or "출처",
            "url": link, "pub": pub, "score": score}


def search_bing(query):
    """빙 뉴스 검색 RSS. 구글이 놓친 기사를 보강한다(쿼리당 12건 안팎).

    네이버·다음은 뉴스검색 RSS 를 폐지해 키 없이는 못 쓴다.
    빙은 키가 필요 없어 유일하게 바로 붙일 수 있는 두 번째 플랫폼이다.
    """
    q = urllib.parse.quote(query)
    url = f"https://www.bing.com/news/search?q={q}&format=RSS&setmkt=ko-KR"
    try:
        raw = fetch(url)
    except Exception as e:
        log(f"  ! 빙 실패 [{query}]: {type(e).__name__}")
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        log(f"  ! 빙 파싱 실패 [{query}]: {e}")
        return []

    now = datetime.now(timezone.utc)
    out = []
    for item in root.findall(".//item"):
        # 언론사는 빙 전용 네임스페이스에 들어 있어 태그 끝으로 찾는다.
        source = ""
        for child in item:
            if child.tag.endswith("}Source"):
                source = child.text or ""
                break
        # link 는 bing.com 리디렉트다. url= 파라미터에 실제 주소가 들어 있으니 꺼내 쓴다.
        link = (item.findtext("link") or "").strip()
        real = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("url")
        if real:
            link = real[0]

        art = make_article(raw_title=item.findtext("title"), source=source,
                           link=link, pub=parse_pubdate(item.findtext("pubDate")),
                           query=query, now=now)
        if art:
            out.append(art)
    return out


def build_category(key, spec, used_keys):
    queries = spec.get("queries") or []
    limit = int(spec.get("max") or 3)
    log(f"[{key}] 검색 {len(queries)}건")
    pool = []
    for q in queries:
        g = search_news(q)
        # 검색어가 늘고 플랫폼이 둘이 되면서 요청 수가 2배가 됐다.
        # 몰아치면 429(요청 과다)를 맞으니 사이를 살짝 띄운다.
        time.sleep(0.35)
        b = search_bing(q)
        time.sleep(0.35)
        log(f"  - {q}: 구글 {len(g)} + 빙 {len(b)}건")
        pool.extend(g)
        pool.extend(b)

    _pool_titles.extend(a["title"] for a in pool)              # 키워드 추출용 표본
    _pool_hours.extend(a["pub"].astimezone(KST).hour for a in pool)  # 시간대 통계용
    pool.sort(key=lambda a: a["score"], reverse=True)

    # --- 같은 사건끼리 묶어 '몇 개 언론사가 다뤘나'를 센다 ---
    # 거시 뉴스(금리·유가)는 15개사가 쓰고 건설 뉴스는 1~2개사만 쓴다.
    # 그래서 보도 수는 정렬의 주 기준이 아니라 신뢰도 배지 + 약한 가산점으로만 쓴다.
    # (카테고리가 분리돼 있어 거시가 건설을 밀어내지 않는다)
    clusters = []
    for art in pool:
        for c in clusters:
            if is_similar(art["title"], [m["title"] for m in c]):
                c.append(art)
                break
        else:
            clusters.append([art])

    ranked = []
    for members in clusters:
        outlets = sorted({m["source"] for m in members if m["source"]})
        rep = max(members, key=lambda m: m["score"])
        boost = min(len(outlets) - 1, 5) * 6
        ranked.append({"rep": rep, "outlets": outlets, "score": rep["score"] + boost})
    ranked.sort(key=lambda c: c["score"], reverse=True)

    picked = []
    for c in ranked:
        if is_similar(c["rep"]["title"], used_keys):   # 다른 카테고리와 중복 차단
            continue
        picked.append(c)
        if len(picked) >= limit:
            break
    used_keys.extend(c["rep"]["title"] for c in picked)

    # 대형 건설사 소식을 카테고리 맨 위로
    picked.sort(key=lambda c: 0 if any(m in c["rep"]["title"] for m in MAJORS) else 1)

    items = []
    for i, c in enumerate(picked):
        a = c["rep"]
        items.append({
            "text": a["title"],
            "source": f"{a['source']} · {a['pub'].astimezone(KST):%m/%d}",
            "url": a["url"],
            "coverage": len(c["outlets"]),          # 1이면 단독
            "outlets": c["outlets"][:8],            # 어느 언론사들이 다뤘는지
            # 대형 건설사가 언급된 최상단 기사만 '주목' 표시
            "hot": i == 0 and any(m in a["title"] for m in MAJORS),
        })
    multi = sum(1 for it in items if it["coverage"] >= 2)
    log(f"  => 채택 {len(items)}건 (복수보도 {multi}, 단독 {len(items) - multi})")
    return items


# ---------------------------------------------------------------- 키워드

# 뉴스 제목에 흔하지만 내용이 없는 말들
STOPWORDS = {
    "있다", "없다", "한다", "된다", "했다", "이다", "위해", "통해", "대한", "관련",
    "지난", "올해", "내년", "이번", "오늘", "내일", "최근", "다시", "아직", "이미",
    "전망", "예상", "분석", "발표", "추진", "확대", "강화", "예정", "방침", "계획",
    "지역", "사업", "경우", "때문", "가운데", "상황", "문제", "필요", "가능", "우려",
    "속으로", "종합", "상보", "속보", "단독", "인터뷰", "기자", "그래픽", "포토",
    "머니", "종목", "리포트", "모닝", "주간", "마감", "개장", "장중", "코스피", "코스닥",
    # 단위·수량 조각 (숫자와 붙어 다녀 의미가 없다)
    "만에", "개월", "달러", "원대", "억원", "조원", "만원", "포인트", "퍼센트",
    "이후", "대비", "전년", "기록", "수준", "규모", "돌파", "육박", "가운데서",
    "번째", "눈앞", "속에", "에서", "으로", "하며", "이며", "라며", "까지",
    # 조사를 떼고 나면 남는 흔한 껍데기
    "격화", "확산", "지속", "본격", "잇따", "나선", "밝혀", "따르", "위한",
    "재돌파", "재진입", "급등", "급락", "상승", "하락",   # '돌파'와 같은 결의 시황 동사
}

# 조사(뒤에 붙어 의미를 흐리는 꼬리). 긴 것부터 떼어야 '에서는'이 '에서'로 안 잘린다.
JOSA_LONG = ("에서는", "에서도", "으로는", "으로도", "에게서",
             "에서", "에는", "에도", "으로", "라며", "하며", "이며", "까지", "부터",
             "보다", "처럼", "만큼", "에게", "만에", "라고", "이라", "지만", "다는")
# 한 글자 조사는 위험하다. '국제유가'의 '가', '제도'의 '도'처럼 명사 끝소리와 겹친다.
# 그래서 비교적 안전한 것만, 그것도 3글자 이상 단어에서만 뗀다.
JOSA_SHORT = ("에", "은", "는", "을", "를", "의")


def strip_josa(tok):
    """'격화에' -> '격화', '부동산은' -> '부동산'. 떼고 2글자 미만이면 원형을 둔다."""
    for j in JOSA_LONG:
        if tok.endswith(j) and len(tok) - len(j) >= 2:
            return tok[:-len(j)]
    if len(tok) >= 3:
        for j in JOSA_SHORT:
            if tok.endswith(j) and len(tok) - 1 >= 2:
                return tok[:-1]
    # '이'는 4글자 이상에서만. '현대건설이'는 떼야 하지만 '어린이'는 두어야 한다.
    if len(tok) >= 4 and tok.endswith("이"):
        return tok[:-1]
    return tok


def extract_keywords(titles, queries_used, top=6):
    """그날 기사 제목에서 자주 나온 단어를 뽑아 '오늘의 키워드'를 만든다.

    보드에 실린 10건만 보면 표본이 너무 작아 한 번씩만 나온 잡음
    ('17만5000원' 같은)이 올라온다. 그래서 필터를 통과한 **후보 기사 전체**
    (보통 100건 이상)에서 빈도를 센다.

    검색어 자체(건설·수주 등)는 모든 기사에 들어 있어 정보가 없으므로 뺀다.
    남는 건 그날 실제로 일어난 사건의 말들(호르무즈·기준금리·재건축 등)이다.
    """
    banned = set(STOPWORDS)
    for q in queries_used:
        for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", q):
            banned.add(tok)

    counts = {}
    for t in titles:
        seen = set()
        # 숫자를 통째로 빼면 '상도15구역'이 '상도'+'구역'으로 쪼개져 뜻이 사라진다.
        # 그래서 숫자를 품은 토큰도 받되, 아래에서 '금액·수치 덩어리'만 걸러낸다.
        for raw in re.findall(r"[가-힣A-Za-z0-9]{2,}", t):
            if raw[0].isdigit():            # 1조4367억원 · 113억달러 · 90달러
                continue
            if re.search(r"\d{3,}", raw):   # 17만5000원 처럼 숫자가 긴 것
                continue
            tok = strip_josa(raw)
            if len(tok) < 2 or tok in banned or tok in seen:
                continue
            seen.add(tok)
            counts[tok] = counts.get(tok, 0) + 1

    # 표본이 크므로 3회 이상 나온 말만 신뢰한다
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    strong = [w for w, c in ranked if c >= 3]
    if len(strong) < 3:                                    # 뉴스가 적은 날 대비
        strong = [w for w, c in ranked if c >= 2]
    return strong[:top]


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

def extract_array(src, varname):
    """window.<varname> = [ ... ] 의 배열 부분만 잘라낸다.

    data.js 에는 NEWS_DATA 말고 NEWS_CONFIG 도 들어가므로 정규식으로
    끝까지 훑으면 안 된다. 대괄호 짝을 세되 문자열 안의 괄호는 무시한다.
    """
    i = src.find("window." + varname)
    if i < 0:
        return None
    j = src.find("[", i)
    if j < 0:
        return None
    depth, in_str, esc = 0, False, False
    for k in range(j, len(src)):
        c = src[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return src[j:k + 1]
    return None


def _headline_url(entry):
    """아카이브 항목의 헤드라인 원문 링크를 찾는다.
    신규 항목은 headlineUrl 을 갖고, 옛 항목은 categories 에서 제목이 같은 기사를 찾는다."""
    if entry.get("headlineUrl"):
        return entry["headlineUrl"]
    hl = entry.get("headline", "")
    for items in entry.get("categories", {}).values():
        for it in items:
            if it.get("text") == hl:
                return it.get("url", "")
    return ""


def load_archive():
    """기존 data.js 에서 뉴스 배열만 떼어내 파싱."""
    if not os.path.exists(DATA_JS):
        return []
    try:
        with open(DATA_JS, encoding="utf-8") as f:
            src = f.read()
        raw = extract_array(src, "NEWS_DATA")
        if not raw:
            log("  ! 기존 data.js 형식을 못 읽음 - 새로 시작")
            return []
        return json.loads(raw)
    except Exception as e:
        log(f"  ! 기존 data.js 파싱 실패({type(e).__name__}) - 새로 시작")
        return []


HEADER = """/* 건설 뉴스 브리핑 보드 - 데이터 파일
 * !! 자동 생성 파일입니다. 직접 고쳐도 다음 실행 때 덮어써집니다.
 * 생성: scripts/build_news.py  (GitHub Actions, 매일 오전)
 * 설정 변경은 config.json 또는 보드판 관리자 화면에서 하세요.
 */
"""


def write_data_js(archive, cfg):
    """data.js 에 뉴스와 함께 현재 설정도 싣는다.

    관리자 화면이 현재 키워드·언론사를 보여주려면 config.json 을 읽어야 하는데,
    file:// 로 열면 fetch 가 CORS 로 막힌다. data.js 에 같이 실어 보내면
    로컬에서도 GitHub Pages 에서도 문제없이 읽힌다.
    """
    shown = {k: v for k, v in cfg.items() if not k.startswith("_")}
    body = json.dumps(archive, ensure_ascii=False, indent=2)
    conf = json.dumps(shown, ensure_ascii=False, indent=2)
    with open(DATA_JS, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER
                + "window.NEWS_DATA = " + body + ";\n\n"
                + "window.NEWS_CONFIG = " + conf + ";\n")
    log(f"data.js 작성 완료 - {len(archive)}일치, {os.path.getsize(DATA_JS):,} bytes")


# ---------------------------------------------------------------- 메일

def write_email(entry, board_url):
    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    # 보드의 6개 카테고리와 순서를 맞춘다.
    # (경쟁사·핵심상품을 나중에 추가하면서 여기에 반영을 빠뜨려
    #  메일에만 기사 3분의 1이 누락됐던 적이 있다. 카테고리를 늘리면 여기도 같이 고칠 것)
    titles = {"order": "🏆 수주", "competitor": "⚔️ 경쟁사",
              "trend": "🔬 핵심상품 트렌드", "industry": "🏗️ 건설업계",
              "economy": "💰 물가·경제", "geo": "🌍 지정학적 이슈"}

    rows = []
    for k, label in titles.items():
        items = entry["categories"].get(k, [])
        if not items:
            continue
        lis = "".join(
            f'<li style="margin:0 0 9px;line-height:1.6">'
            f'<a href="{esc(i["url"])}" style="color:#111;text-decoration:none">{esc(i["text"])}</a>'
            f'<br><span style="color:#888;font-size:12px">{esc(i["source"])}'
            + (f' · {i["coverage"]}개사 보도' if i.get("coverage", 1) >= 2 else " · 단독")
            + '</span></li>'
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
    # 전망은 사람이 매주 써야 해서 결국 빈칸이 됐다. 보드는 카테고리별 자동 요약으로
    # 대체했고, 메일은 이미 전 카테고리를 나열하므로 코멘트가 있을 때만 덧붙인다.
    if entry.get("outlook"):
        extra += ('<h3 style="margin:22px 0 10px;font-size:15px;color:#008C46">📝 한 줄 코멘트</h3>'
                  f'<div style="font-size:13px;line-height:1.7;color:#444">{esc(entry["outlook"])}</div>')

    board_btn = (
        f'<div style="margin:26px 0 10px"><a href="{esc(board_url)}" '
        'style="background:#008C46;color:#fff;padding:12px 22px;border-radius:999px;'
        'text-decoration:none;font-weight:700;font-size:14px">보드판 전체 보기 →</a></div>'
    ) if board_url else ""

    # charset 선언이 없으면 메일 클라이언트가 인코딩을 추측하다 한글이 깨진다
    # (실제로 '대우건설'이 'ëŒ€ìš°ê±´ì„¤'로 보였다). MIME 헤더에만 기대지 말 것.
    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#EDF1ED">
<div style="font-family:'Malgun Gothic',sans-serif;max-width:640px;margin:0 auto;padding:16px">
  <div style="background:#0F2C1D;color:#fff;padding:22px 24px;border-radius:12px">
    <div style="font-size:11px;color:#5FCB93;letter-spacing:.1em;font-weight:700">오늘의 핵심</div>
    <div style="font-size:17px;font-weight:700;margin-top:8px;line-height:1.5">{esc(entry['headline'])}</div>
    <div style="font-size:12px;color:#A9BBB0;margin-top:12px">{esc(entry['date'])} {esc(entry.get('generatedAt',''))} 기준</div>
  </div>
  <table style="width:100%;margin-top:14px;border-collapse:separate;border-spacing:6px"><tr>{inds}</tr></table>
  {''.join(rows)}
  {extra}
  {board_btn}
  <div style="color:#999;font-size:11px;margin-top:18px">
    자동 발송 · GitHub Actions · 뉴스 출처 Google News + Bing News (주요 언론사 한정)</div>
</div>
</body></html>"""

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

    # 관리자 화면에서 저장한 키워드가 있으면 그것을 쓴다
    cats_cfg = cfg.get("searchKeywords") or DEFAULT_CATEGORIES
    cats_cfg = {k: v for k, v in cats_cfg.items() if v.get("queries")}
    if not cats_cfg:
        log("!! searchKeywords 가 비어 있음 - 기본 키워드로 대체")
        cats_cfg = DEFAULT_CATEGORIES
    log("검색 카테고리: " + ", ".join(
        f"{v.get('label', k)}({len(v.get('queries', []))}개 키워드)" for k, v in cats_cfg.items()))

    used = []  # 이미 채택한 제목들 - 카테고리 간 중복 방지
    categories = {k: build_category(k, spec, used) for k, spec in cats_cfg.items()}

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

    # 아카이브를 먼저 읽어둔다 (헤드라인 중복 회피와 지난주 목록에 둘 다 쓴다)
    archive = load_archive()
    prev_today = next((e for e in archive if e.get("date") == today), None)
    archive = [e for e in archive if e.get("date") != today]  # 같은 날 재실행 시 교체

    # --- 오늘의 핵심 고르기 ---
    # 견적팀 기준 중요도: 수주 > 경쟁사 > 핵심상품 > 지정학 > 물가 > 업계.
    # 여기에 대형 건설사 언급과 보도 언론사 수를 얹어 하나를 고르고,
    # '왜 이게 오늘의 핵심인지'를 한 줄로 붙인다 (눈길을 끄는 후킹 문구 역할).
    PRIORITY = {"order": 60, "competitor": 50, "trend": 44,
                "geo": 30, "economy": 26, "industry": 20}

    # 최상단이 매 실행/매일 같은 기사에 고정되지 않도록, 직전 실행(같은 날)과
    # 어제 헤드라인과 겹치면 점수를 눌러 다른 기사가 올라올 여지를 준다.
    # (진짜 대형 뉴스라 다른 후보가 없으면 페널티를 먹어도 여전히 1등 → 그대로 유지)
    recent_headlines = []
    if prev_today and prev_today.get("headline"):
        recent_headlines.append(prev_today["headline"])
    if archive and archive[0].get("headline"):
        recent_headlines.append(archive[0]["headline"])

    best, best_key, best_score = None, None, -1
    for k, items in categories.items():
        for it in items:
            s = PRIORITY.get(k, 10)
            if any(m in it["text"] for m in MAJORS):
                s += 30
            s += min(it.get("coverage", 1) - 1, 6) * 5
            if it.get("hot"):
                s += 5
            if recent_headlines and is_similar(it["text"], recent_headlines):
                s -= 22
            if s > best_score:
                best, best_key, best_score = it, k, s

    headline = best["text"] if best else "오늘 수집된 기사가 없습니다"
    headline_cat = (cats_cfg.get(best_key, {}) or {}).get("label", best_key) if best else ""

    # 후킹 문구: 사실에 근거한 것만 붙인다 (없는 말을 지어내지 않는다)
    note_bits = []
    if best:
        cov = best.get("coverage", 1)
        if cov >= 5:
            note_bits.append(f"오늘 가장 많이 다뤄진 이슈 · {cov}개 언론사 보도")
        elif cov >= 2:
            note_bits.append(f"{cov}개 언론사가 함께 보도")
        else:
            note_bits.append("단독 보도")
        hit = [m for m in MAJORS if m in best["text"]]
        if hit:
            note_bits.append(f"{hit[0]} 관련")
    headline_note = " · ".join(note_bits[:2])   # 길어지면 후킹이 아니라 잡음이 된다

    # 지난주 돌아보기 = 직전 7일 아카이브의 헤드라인 (원문 링크 포함)
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    last_week = [{"date": e["date"][5:], "text": e["headline"], "url": _headline_url(e)}
                 for e in archive if e.get("date", "") >= week_ago][:6]

    entry = {
        "date": today,
        "generatedAt": now.strftime("%H:%M"),
        "headline": headline,
        "headlineUrl": best["url"] if best else "",   # 지난주 목록에서 원문 링크로 씀
        "headlineNote": headline_note,
        "headlineCat": headline_cat,
        "indicators": indicators,
        "categories": categories,
        # 통계용: 후보 기사들이 몇 시에 발행됐는지 24칸 히스토그램.
        # 보드에 실린 15건만으로는 표본이 작아 후보 전체(100건 이상)를 센다.
        "hourHistogram": [_pool_hours.count(h) for h in range(24)],
        "poolSize": len(_pool_hours),
        "keywords": extract_keywords(
            _pool_titles, [q for v in cats_cfg.values() for q in v.get("queries", [])]),
        "lastWeek": last_week or ["아카이브가 쌓이면 지난주 요약이 자동으로 표시됩니다."],
        "outlook": cfg.get("outlook", ""),
    }

    # 오후 2차 실행용: 새 기사가 없으면 아무것도 바꾸지 않고 끝낸다.
    # (generatedAt 만 바뀐 커밋으로 Pages 를 매번 재배포하는 낭비를 막는다)
    if "--only-if-new" in sys.argv and prev_today:
        old_urls = {it.get("url") for v in prev_today.get("categories", {}).values() for it in v}
        new_urls = {it.get("url") for v in categories.values() for it in v}
        added = new_urls - old_urls
        if not added:
            log("새 기사 없음 - data.js 를 그대로 두고 종료 (커밋/재배포 없음)")
            return 0
        log(f"새 기사 {len(added)}건 발견 - 갱신 진행")

    archive.insert(0, entry)
    archive = archive[:MAX_ARCHIVE]

    write_data_js(archive, cfg)
    board_url = os.environ.get("BOARD_URL", "")
    write_email(entry, board_url)
    log(f"완료 - 기사 {total}건, 헤드라인: {headline[:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
