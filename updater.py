"""
updater.py  —  Pick 5 Auto-Updater (GitHub Actions version)
=============================================================
Scrapes today's Pick 5 results from official state lottery sites
and cross-references with lotteryusa.com.
LA uses 4 sources. VA uses 3 sources. All others use 2.
 
GitHub Actions runs this on schedule and handles git push automatically.
 
Usage:
  python updater.py --states OH GA MD --draw midday
  python updater.py --states ALL --draw auto
  python updater.py --states LA VA --draw evening --skip-existing
"""
 
import re, os, sys, time, argparse, datetime
 
try:
    import requests
    from bs4 import BeautifulSoup
    USE_REQUESTS = True
except ImportError:
    import urllib.request, urllib.error
    USE_REQUESTS = False
 
# ── CONFIG ────────────────────────────────────────────────────────────
HTML_FILENAME = "index.html"   # file in repo root — do not change
# ─────────────────────────────────────────────────────────────────────
 
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
 
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
 
OFFICIAL = {
    "DC": "https://lotterycoast.com/lottery-results/washington-dc/pick5/",
    "DE": "https://lotterycoast.com/lottery-results/delaware/play5/",
    "FL": "https://lotterycoast.com/lottery-results/florida/pick5/",
    "GA": "https://lotterycoast.com/lottery-results/georgia/cash5/",
    "GE": "https://www.lotto.de/plus5",   # no lotterycoast for Germany
    "MD": "https://lotterycoast.com/lottery-results/maryland/pick5/",
    "OH": "https://lotterycoast.com/lottery-results/ohio/pick5/",
    "PA": "https://lotterycoast.com/lottery-results/pennsylvania/pick5/",
    "VA": "https://lotterycoast.com/lottery-results/virginia/pick5/",
    "LA": "https://lotterycoast.com/lottery-results/louisiana/pick5/",
}
 
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
VA_HOME   = "https://www.valottery.com/"
 
# ── HELPERS ────────────────────────────────────────────────────────────
 
def log(msg):
    ts = datetime.datetime.utcnow().strftime("%H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)
 
def fetch(url, retries=3, pause=10):
    for n in range(retries):
        try:
            if USE_REQUESTS:
                r = requests.get(url, headers=HEADERS, timeout=25)
                r.raise_for_status()
                return r.text
            else:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=25) as resp:
                    return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            log(f"  fetch attempt {n+1} failed ({url[:60]}): {e}")
            if n < retries-1: time.sleep(pause)
    return None
 
def get_et():
    utc = datetime.datetime.utcnow()
    y = utc.year
    mar1 = datetime.datetime(y,3,1)
    dst_start = mar1 + datetime.timedelta(days=(6-mar1.weekday())%7+7)
    nov1 = datetime.datetime(y,11,1)
    dst_end = nov1 + datetime.timedelta(days=(6-nov1.weekday())%7)
    return utc - datetime.timedelta(hours=4 if dst_start<=utc<dst_end else 5)
 
def today_et():
    return get_et().strftime("%Y-%m-%d")
 
def yesterday_et():
    return (get_et()-datetime.timedelta(days=1)).strftime("%Y-%m-%d")
 
def auto_draw(state):
    if state in SINGLE_DRAW: return "evening"
    et = get_et()
    et_mins = et.hour*60 + et.minute
    mid = DRAW_TIMES[state].get("midday")
    if mid and (mid[0]*60+mid[1]+5) <= et_mins < 18*60:
        return "midday"
    return "evening"
 
def parse_5digit(html, target_date):
    if not html: return None
    date_obj = datetime.datetime.strptime(target_date, "%Y-%m-%d")
    fmts = [
        date_obj.strftime("%-m/%-d/%Y"),
        date_obj.strftime("%m/%d/%Y"),
        date_obj.strftime("%B %-d, %Y"),
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
 
# ── SOURCE SCRAPERS ────────────────────────────────────────────────────
 
def src_official(state, draw, date):
    url = OFFICIAL.get(state)
    if not url: return None
    log(f"    [official/{state}]   {url[:60]}")
    html = fetch(url)
    if not html: return None
    # Ohio uses a PDF that returns plain text with format:
    # "TUE - MID  3/19/2026  911  1477  91049"
    # "TUE - EVE  3/19/2026  212  6246  98448"
    # Columns: Pick3, Pick4, Pick5 (in that order after date)
    if state != "GE" and "lotterycoast" in url:
        return parse_lotterycoast(html, draw, date)
    return parse_5digit(html, date)
 
def parse_ohio_pdf(text, draw, date):
    """Parse Ohio's annual numbers PDF (plain text).
    Format: 'DAY - MID/EVE  M/D/YYYY  pick3  pick4  pick5 ...'"""
    date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
    draw_label = "MID" if draw == "midday" else "EVE"
    for fmt in [date_obj.strftime("%-m/%-d/%Y"), date_obj.strftime("%m/%d/%Y")]:
        for line in text.split('\n'):
            if fmt in line and draw_label in line:
                after_date = line[line.find(fmt)+len(fmt):]
                nums = re.findall(r'\b(\d{3,6})\b', after_date)
                for n in nums:
                    if len(n) == 5:
                        return n.zfill(5)
    return None
 
def parse_lotterycoast(html, draw, date):
    """Parse lotterycoast.com page.
    Format: 'Sun Icon Midday · 6 2 1 2 6' or 'Moon Icon Evening · 9 2 7 3 1'"""
    date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
    draw_label = "Midday" if draw == "midday" else "Evening"
    for fmt in [date_obj.strftime("%A, %B %-d, %Y"), date_obj.strftime("%B %-d, %Y")]:
        idx = html.find(fmt)
        if idx == -1: continue
        window = html[idx:idx+600]
        label_idx = window.find(draw_label)
        if label_idx == -1: continue
        sub = window[label_idx:label_idx+120]
        digits = re.findall(r'\b(\d)\b', sub)
        if len(digits) >= 5:
            return ''.join(digits[:5]).zfill(5)
    return None
 
def src_lusa(state, draw, date):
    urls = LUSA.get(state)
    if not urls: return None
    url = urls.get(draw) or urls.get("evening")
    if not url: return None
    log(f"    [lotteryusa/{state}] {url[:60]}")
    return parse_5digit(fetch(url), date)
 
def src_la_mobile(date):
    log(f"    [la-mobile]  {LA_MOBILE[:60]}")
    return parse_5digit(fetch(LA_MOBILE), date)
 
def src_la_pdf(date):
    log(f"    [la-pdf]     {LA_PDF[:60]}")
    html = fetch(LA_PDF)
    if not html: return None
    date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
    for fmt in [date_obj.strftime("%m/%d/%Y"), date_obj.strftime("%-m/%-d/%Y")]:
        idx = html.find(fmt)
        if idx != -1:
            window = html[idx:idx+200]
            m = re.search(r'(\d)\s*-\s*(\d)\s*-\s*(\d)\s*-\s*(\d)\s*-\s*(\d)', window)
            if m: return ''.join(m.groups()).zfill(5)
    return None
 
def src_va_home(draw, date):
    log(f"    [va-home]    {VA_HOME[:60]}")
    html = fetch(VA_HOME)
    if not html: return None
    draw_label = "Day:" if draw == "midday" else "Night:"
    for marker in ["pick5","Pick5","PICK 5","Pick 5"]:
        p5_idx = html.find(marker)
        if p5_idx != -1: break
    else:
        return None
    window = html[p5_idx:p5_idx+3000]
    label_idx = window.find(draw_label)
    if label_idx == -1: return None
    sub = window[label_idx:label_idx+150]
    if re.search(r'- - -', sub): return None
    digits = re.findall(r'(?<![·\d])(\d)(?![·\d])', sub)
    if len(digits) >= 5: return ''.join(digits[:5]).zfill(5)
    return None
 
def get_confirmed(state, draw, date, retry_secs=120):
    is_la = (state == "LA")
    is_va = (state == "VA")
    for attempt in range(3):
        log(f"  {state} {draw} attempt {attempt+1}:")
        r1 = src_official(state, draw, date)
        r2 = src_lusa(state, draw, date)
        r3 = src_la_mobile(date)     if is_la else None
        r4 = src_la_pdf(date)        if is_la else None
        r5 = src_va_home(draw, date) if is_va else None
        sources = [r for r in [r1,r2,r3,r4,r5] if r]
        extra = (f"  la-mobile={r3}  la-pdf={r4}" if is_la else
                 f"  va-home={r5}"                if is_va else "")
        log(f"    official={r1}  lusa={r2}{extra}")
        if not sources:
            log(f"    ⚠️  all sources empty")
        else:
            unique = set(sources)
            if len(unique) == 1:
                log(f"    ✅ CONFIRMED: {sources[0]}")
                return sources[0]
            if len(sources) >= 3:
                from collections import Counter
                mc = Counter(sources).most_common(1)[0]
                if mc[1] >= 2:
                    log(f"    ✅ MAJORITY: {mc[0]} ({mc[1]}/{len(sources)} agree)")
                    return mc[0]
            if len(sources) == 1:
                log(f"    ⚠️  single source: {sources[0]} — using it")
                return sources[0]
            log(f"    ⚠️  MISMATCH {unique} — waiting {retry_secs//60} min")
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
    if state in SINGLE_DRAW:
        return len(vals)>0 and vals[0] not in ('null','""',"''","")
    if draw_idx >= len(vals): return False
    return vals[draw_idx] not in ('null','""',"''","")
 
def patch_html(content, state, day, month_key, draw, number):
    st_idx = content.find(f'{state}:{{name:')
    if st_idx == -1:
        log(f"  ❌ State block not found: {state}"); return content, False
    section = content[st_idx:st_idx+500000]
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
        new_block   = old_block.replace(days_str, new_days, 1)
        new_section = section.replace(old_block, new_block, 1)
    else:
        if is_single:       nm = f',"{month_key}":{{{day}:[{num_q}]}}'
        elif draw_idx==0:   nm = f',"{month_key}":{{{day}:[{num_q},null]}}'
        else:               nm = f',"{month_key}":{{{day}:[null,{num_q}]}}'
        ins = section.rfind('}}},')
        if ins==-1: ins = section.rfind('}}}')
        if ins==-1:
            log(f"  ❌ insertion point not found for {state}"); return content, False
        new_section = section[:ins] + nm + section[ins:]
    new_content = content[:st_idx] + new_section + content[st_idx+500000:]
    log(f"  ✅ Patched {state} {draw} {month_key}-{day:02d} = {number}")
    return new_content, True
 
# ── MAIN ────────────────────────────────────────────────────────────────
 
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", nargs="+", required=True)
    ap.add_argument("--draw", choices=["midday","evening","auto"], default="auto")
    ap.add_argument("--date", default=None)
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()
 
    et = get_et()
    if args.date:
        target_date = args.date
    elif et.hour < 6:
        target_date = yesterday_et()
    else:
        target_date = today_et()
 
    date_obj  = datetime.datetime.strptime(target_date, "%Y-%m-%d")
    month_key = target_date[:7]
    day       = date_obj.day
    states    = ALL_STATES if "ALL" in [s.upper() for s in args.states] else [s.upper() for s in args.states]
 
    log(f"=== Pick5 Updater | date={target_date} | states={states} | draw={args.draw} ===")
 
    # Read the HTML file
    html_path = HTML_FILENAME
    if not os.path.exists(html_path):
        log(f"❌ Not found: {html_path}")
        sys.exit(1)
 
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
 
    updated = []
    for state in states:
        draw = args.draw if args.draw != "auto" else auto_draw(state)
        if state in SINGLE_DRAW:
            draw = "evening"
            if args.draw == "midday":
                log(f"  {state} is single-draw only, skipping midday")
                continue
        if args.skip_existing and already_has(content, state, day, month_key, draw):
            log(f"  {state} {draw} already recorded — skipping")
            continue
        log(f"\n── {state} {draw} ──")
        num = get_confirmed(state, draw, target_date)
        if num:
            content, ok = patch_html(content, state, day, month_key, draw, num)
            if ok:
                updated.append(f"{state}_{draw}={num}")
 
    if updated:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"✅ Saved: {', '.join(updated)}")
    else:
        log("Nothing updated.")
 
    log("=== Done ===")
 
if __name__ == "__main__":
    main()
 
