"""
updater.py  —  Pick 5 Auto-Updater (Playwright version)
=========================================================
Uses headless Chromium to render JavaScript lottery sites.
All 10 states now work reliably regardless of JS rendering.
 
GitHub Actions installs Playwright + Chromium automatically via updater.yml.
"""
 
import re, os, sys, time, argparse, datetime
 
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    USE_PLAYWRIGHT = True
except ImportError:
    import urllib.request
    USE_PLAYWRIGHT = False
    print("WARNING: Playwright not available, using urllib fallback")
 
# ── CONFIG ────────────────────────────────────────────────────────────
HTML_FILENAME = "index.html"
# ─────────────────────────────────────────────────────────────────────
 
ALL_STATES  = ["OH","GA","MD","FL","PA","GE","DC","DE","VA","LA"]
SINGLE_DRAW = {"LA","GE"}
 
DRAW_TIMES = {
    "OH": {"midday":(12,14), "evening":(19,14)},
    "GA": {"midday":(12,14), "evening":(18,44)},
    "MD": {"midday":(12,13), "evening":(19,41)},
    "PA": {"midday":(13,35), "evening":(18,59)},
    "FL": {"midday":(13,30), "evening":(21,45)},
    "GE": {                  "evening":(19,35)},
    "DC": {"midday":(13,50), "evening":(19,50)},
    "DE": {"midday":(13,58), "evening":(19,57)},
    "VA": {"midday":(13,59), "evening":(23, 0)},
    "LA": {                  "evening":(22,25)},
}
 
# Official state lottery sites — now work with Playwright
OFFICIAL = {
    "DC": "https://dclottery.com/winning-numbers",
    "DE": "https://www.delottery.com/Drawing-Games/Play-5",
    "FL": "https://www.flalottery.com/pick5",
    "GA": "https://www.galottery.com/en-us/results/drawgame/quickdraw.html?game=CASH5",
    "GE": "https://www.lotto.de/plus5",
    "MD": "https://www.mdlottery.com/games/pick-5/",
    "OH": "https://www.ohiolottery.com/winning-numbers",
    "PA": "https://www.palottery.pa.gov/Draw-Games/PICK-5.aspx",
    "VA": "https://www.valottery.com/",
    "LA": "https://louisianalottery.com/draw-games/pick-5/",
}
 
# Cross-reference
LUSA = {
    "DC": {"midday":"https://www.lotteryusa.com/district-of-columbia/midday-dc5/",
           "evening":"https://www.lotteryusa.com/district-of-columbia/dc-5/"},
    "DE": {"midday":"https://www.lotteryusa.com/delaware/play-5-midday/",
           "evening":"https://www.lotteryusa.com/delaware/play-5/"},
    "FL": {"midday":"https://www.lotteryusa.com/florida/pick-5-midday/",
           "evening":"https://www.lotteryusa.com/florida/pick-5/"},
    "GA": {"midday":"https://www.lotteryusa.com/georgia/cash-5-midday/",
           "evening":"https://www.lotteryusa.com/georgia/cash-5/"},
    "GE": None,
    "MD": {"midday":"https://www.lotteryusa.com/maryland/pick-5-midday/",
           "evening":"https://www.lotteryusa.com/maryland/pick-5/"},
    "OH": {"midday":"https://www.lotteryusa.com/ohio/pick-5-midday/",
           "evening":"https://www.lotteryusa.com/ohio/pick-5/"},
    "PA": {"midday":"https://www.lotteryusa.com/pennsylvania/pick-5-midday/",
           "evening":"https://www.lotteryusa.com/pennsylvania/pick-5/"},
    "VA": {"midday":"https://www.lotteryusa.com/virginia/pick-5-day/",
           "evening":"https://www.lotteryusa.com/virginia/pick-5/"},
    "LA": {"evening":"https://www.lotteryusa.com/louisiana/pick-5/"},
}
 
LA_MOBILE = "https://louisianalottery.com/m/winning-numbers/?tname=pick5"
LA_PDF    = "https://louisianalottery.com/pdf-creation/?pdfID=pick-5"
 
# ── HELPERS ────────────────────────────────────────────────────────────
 
def log(msg):
    ts = datetime.datetime.utcnow().strftime("%H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)
 
def get_et():
    utc = datetime.datetime.utcnow()
    y = utc.year
    mar1 = datetime.datetime(y,3,1)
    dst_start = mar1 + datetime.timedelta(days=(6-mar1.weekday())%7+7)
    nov1 = datetime.datetime(y,11,1)
    dst_end = nov1 + datetime.timedelta(days=(6-nov1.weekday())%7)
    return utc - datetime.timedelta(hours=4 if dst_start<=utc<dst_end else 5)
 
def today_et():  return get_et().strftime("%Y-%m-%d")
def yesterday_et(): return (get_et()-datetime.timedelta(days=1)).strftime("%Y-%m-%d")
 
def auto_draw(state):
    if state in SINGLE_DRAW: return "evening"
    et = get_et()
    et_mins = et.hour*60 + et.minute
    mid = DRAW_TIMES[state].get("midday")
    if mid and (mid[0]*60+mid[1]+5) <= et_mins < 18*60:
        return "midday"
    return "evening"
 
# ── BROWSER ────────────────────────────────────────────────────────────
 
_browser = None
_pw      = None
 
def get_browser():
    global _browser, _pw
    if _browser is None:
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-setuid-sandbox",
                  "--disable-dev-shm-usage","--disable-gpu"]
        )
    return _browser
 
def close_browser():
    global _browser, _pw
    try:
        if _browser: _browser.close()
        if _pw: _pw.stop()
    except: pass
    _browser = None
    _pw = None
 
def fetch(url, wait_ms=4000, retries=2):
    """Fetch URL with headless browser, wait for JS to render."""
    if not USE_PLAYWRIGHT:
        import urllib.request
        headers = {"User-Agent":"Mozilla/5.0 Chrome/122.0 Safari/537.36"}
        for n in range(retries):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=25) as r:
                    return r.read().decode("utf-8", errors="replace")
            except Exception as e:
                log(f"  urllib attempt {n+1} failed: {e}")
                if n < retries-1: time.sleep(5)
        return None
 
    for attempt in range(retries):
        ctx = None
        try:
            ctx = get_browser().new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
                viewport={"width":1280,"height":800}
            )
            page = ctx.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            html = page.content()
            ctx.close()
            return html
        except PlaywrightTimeout:
            log(f"  timeout attempt {attempt+1} ({url[:55]})")
            if ctx:
                try: ctx.close()
                except: pass
            if attempt < retries-1: time.sleep(5)
        except Exception as e:
            log(f"  error attempt {attempt+1}: {e}")
            if ctx:
                try: ctx.close()
                except: pass
            if attempt < retries-1: time.sleep(5)
    return None
 
# ── PARSERS ────────────────────────────────────────────────────────────
 
def parse_5digit(html, target_date):
    """Find a 5-digit Pick 5 number near the target date."""
    if not html: return None
    date_obj = datetime.datetime.strptime(target_date, "%Y-%m-%d")
    fmts = [
        date_obj.strftime("%-m/%-d/%Y"),
        date_obj.strftime("%m/%d/%Y"),
        date_obj.strftime("%B %-d, %Y"),
        date_obj.strftime("%b. %-d, %Y"),
        date_obj.strftime("%b %-d, %Y"),
        date_obj.strftime("%Y-%m-%d"),
    ]
    for fmt in fmts:
        idx = html.find(fmt)
        if idx == -1: continue
        window = html[idx:idx+3000]
        m = re.search(r'\b(\d)-(\d)-(\d)-(\d)-(\d)\b', window)
        if m: return ''.join(m.groups()).zfill(5)
        m = re.search(r'(?<!\d)(\d{5})(?!\d)', window)
        if m: return m.group(1).zfill(5)
    all_m = re.findall(r'\b(\d)-(\d)-(\d)-(\d)-(\d)\b', html)
    if all_m: return ''.join(all_m[-1]).zfill(5)
    return None
 
def parse_va(html, draw, target_date):
    """VA homepage: 'Day: 2 · 8 · 9 · 3 · 8' or 'Night: 2 · 3 · 4 · 5 · 1'"""
    if not html: return None
    draw_label = "Day:" if draw == "midday" else "Night:"
    for marker in ["pick5","Pick5","PICK 5","Pick 5"]:
        idx = html.find(marker)
        if idx != -1: break
    else:
        return parse_5digit(html, target_date)
    window = html[idx:idx+3000]
    label_idx = window.find(draw_label)
    if label_idx == -1: return parse_5digit(html, target_date)
    sub = window[label_idx:label_idx+150]
    if re.search(r'- - -|·\s*-', sub): return None
    digits = re.findall(r'(?<![·\d])(\d)(?![·\d])', sub)
    if len(digits) >= 5: return ''.join(digits[:5]).zfill(5)
    return None
 
def parse_la_pdf(text, date):
    """Louisiana PDF endpoint: '03/19/2026 2 - 5 - 3 - 2 - 9'"""
    if not text: return None
    date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
    for fmt in [date_obj.strftime("%m/%d/%Y"), date_obj.strftime("%-m/%-d/%Y")]:
        idx = text.find(fmt)
        if idx == -1: continue
        window = text[idx:idx+200]
        m = re.search(r'(\d)\s*-\s*(\d)\s*-\s*(\d)\s*-\s*(\d)\s*-\s*(\d)', window)
        if m: return ''.join(m.groups()).zfill(5)
    return None
 
# ── SCRAPERS ────────────────────────────────────────────────────────────
 
def src_official(state, draw, date):
    url = OFFICIAL.get(state)
    if not url: return None
    log(f"    [official/{state}]   {url[:60]}")
    html = fetch(url)
    if state == "VA": return parse_va(html, draw, date)
    return parse_5digit(html, date) if html else None
 
def src_lusa(state, draw, date):
    urls = LUSA.get(state)
    if not urls: return None
    url = urls.get(draw) or urls.get("evening")
    if not url: return None
    log(f"    [lotteryusa/{state}] {url[:60]}")
    html = fetch(url)
    return parse_5digit(html, date) if html else None
 
def src_la_extras(date):
    results = []
    for url, parser in [(LA_MOBILE, lambda h: parse_5digit(h, date)),
                        (LA_PDF,    lambda h: parse_la_pdf(h, date))]:
        log(f"    [la-extra]   {url[:60]}")
        html = fetch(url, wait_ms=2000)
        r = parser(html) if html else None
        if r: results.append(r)
    return results
 
def get_confirmed(state, draw, date, retry_secs=120):
    is_la = (state == "LA")
    for attempt in range(3):
        log(f"  {state} {draw} attempt {attempt+1}:")
        r1 = src_official(state, draw, date)
        r2 = src_lusa(state, draw, date)
        extras = src_la_extras(date) if is_la else []
        sources = [r for r in [r1, r2] + extras if r]
        log(f"    official={r1}  lusa={r2}" + (f"  la-extras={extras}" if is_la else ""))
 
        if not sources:
            log(f"    ⚠️  all sources empty")
        else:
            unique = set(sources)
            if len(unique) == 1:
                log(f"    ✅ CONFIRMED: {sources[0]}"); return sources[0]
            if len(sources) >= 3:
                from collections import Counter
                mc = Counter(sources).most_common(1)[0]
                if mc[1] >= 2:
                    log(f"    ✅ MAJORITY: {mc[0]} ({mc[1]}/{len(sources)})"); return mc[0]
            if len(sources) == 1:
                log(f"    ⚠️  single source: {sources[0]}"); return sources[0]
            log(f"    ⚠️  MISMATCH {unique} — waiting {retry_secs}s")
 
        if attempt < 2: time.sleep(retry_secs)
    log(f"    ❌ gave up on {state} {draw}")
    return None
 
# ── HTML PATCHER ────────────────────────────────────────────────────────
 
def already_has(content, state, day, month_key, draw):
    st_idx = content.find(f'{state}:{{name:')
    if st_idx == -1: return False
    section = content[st_idx:st_idx+500000]
    mo_m = re.search(rf'"{re.escape(month_key)}":\{{([^}}]+)\}}', section)
    if not mo_m: return False
    day_m = re.search(rf'{day}:\[([^\]]*)\]', mo_m.group(1))
    if not day_m: return False
    vals = [v.strip() for v in day_m.group(1).split(",")]
    draw_idx = 0 if draw=="midday" else 1
    if state in SINGLE_DRAW: return len(vals)>0 and vals[0] not in ('null','""',"''","")
    if draw_idx >= len(vals): return False
    return vals[draw_idx] not in ('null','""',"''","")
 
def patch_html(content, state, day, month_key, draw, number):
    st_idx = content.find(f'{state}:{{name:')
    if st_idx == -1: log(f"  ❌ State block not found: {state}"); return content, False
    section  = content[st_idx:st_idx+500000]
    is_single = state in SINGLE_DRAW
    draw_idx  = 0 if draw=="midday" else 1
    num_q     = f'"{number}"'
    mo_m = re.search(rf'"{re.escape(month_key)}":\{{([^}}]+)\}}', section)
    if mo_m:
        old_block = mo_m.group(0); days_str = mo_m.group(1)
        day_m = re.search(rf'{day}:\[([^\]]*)\]', days_str)
        if day_m:
            vals = [v.strip() for v in day_m.group(1).split(",")]
            if is_single: vals = [num_q]
            else:
                while len(vals)<2: vals.append("null")
                vals[draw_idx] = num_q
            new_days = days_str.replace(day_m.group(0), f'{day}:[{",".join(vals)}]', 1)
        else:
            if is_single:       new_entry = f',{day}:[{num_q}]'
            elif draw_idx==0:   new_entry = f',{day}:[{num_q},null]'
            else:               new_entry = f',{day}:[null,{num_q}]'
            new_days = days_str + new_entry
        new_section = section.replace(old_block, old_block.replace(days_str, new_days, 1), 1)
    else:
        if is_single:       nm = f',"{month_key}":{{{day}:[{num_q}]}}'
        elif draw_idx==0:   nm = f',"{month_key}":{{{day}:[{num_q},null]}}'
        else:               nm = f',"{month_key}":{{{day}:[null,{num_q}]}}'
        ins = section.rfind('}}},')
        if ins==-1: ins = section.rfind('}}}')
        if ins==-1: log(f"  ❌ insertion point not found"); return content, False
        new_section = section[:ins] + nm + section[ins:]
    log(f"  ✅ Patched {state} {draw} {month_key}-{day:02d} = {number}")
    return content[:st_idx] + new_section + content[st_idx+500000:], True
 
# ── MAIN ────────────────────────────────────────────────────────────────
 
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", nargs="+", required=True)
    ap.add_argument("--draw", choices=["midday","evening","auto"], default="auto")
    ap.add_argument("--date", default=None)
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()
 
    et = get_et()
    if args.date:        target_date = args.date
    elif et.hour < 6:    target_date = yesterday_et()
    else:                target_date = today_et()
 
    date_obj  = datetime.datetime.strptime(target_date, "%Y-%m-%d")
    month_key = target_date[:7]
    day       = date_obj.day
    states    = ALL_STATES if "ALL" in [s.upper() for s in args.states] \
                else [s.upper() for s in args.states]
 
    log(f"=== Pick5 Updater (Playwright) | date={target_date} | states={states} | draw={args.draw} ===")
    log(f"  Playwright: {'YES - headless Chromium' if USE_PLAYWRIGHT else 'NO - urllib fallback'}")
 
    if not os.path.exists(HTML_FILENAME):
        log(f"❌ Not found: {HTML_FILENAME}"); sys.exit(1)
 
    with open(HTML_FILENAME, "r", encoding="utf-8") as f:
        content = f.read()
 
    updated = []
    try:
        for state in states:
            draw = args.draw if args.draw != "auto" else auto_draw(state)
            if state in SINGLE_DRAW:
                draw = "evening"
                if args.draw == "midday":
                    log(f"  {state} is single-draw, skipping midday"); continue
            if args.skip_existing and already_has(content, state, day, month_key, draw):
                log(f"  {state} {draw} already recorded — skipping"); continue
            log(f"\n── {state} {draw} ──")
            num = get_confirmed(state, draw, target_date)
            if num:
                content, ok = patch_html(content, state, day, month_key, draw, num)
                if ok: updated.append(f"{state}_{draw}={num}")
    finally:
        close_browser()
 
    if updated:
        with open(HTML_FILENAME, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"✅ Saved: {', '.join(updated)}")
    else:
        log("Nothing updated.")
    log("=== Done ===")
 
if __name__ == "__main__":
    main()
 
