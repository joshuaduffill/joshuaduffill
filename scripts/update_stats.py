"""Regenerate BTS-USA org stats: assets/*.svg + README blocks between <!-- STATS:x --> markers.

Env: GH_TOKEN (repo + read:org on BTS-USA), USERNAME, ORG, YEAR (default current), EXCLUDE (comma-separated logins).
"""
import json, os, re, sys, time, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote

TOKEN = os.environ["GH_TOKEN"]
USER = os.environ.get("USERNAME", "joshuaduffill")
ORG = os.environ.get("ORG", "BTS-USA")
NOW = datetime.now(timezone.utc)
YEAR = int(os.environ.get("YEAR", NOW.year))
# Automation accounts that would skew the org ranking
EXCLUDE = {l.strip().lower() for l in os.environ.get("EXCLUDE", "jakeportarobts").split(",") if l.strip()}
SINCE = f"{YEAR}-01-01T00:00:00Z"
FONT = 'font-family="Segoe UI,Helvetica,Arial,sans-serif"'
LANG_COLORS = {"TypeScript": "#3178c6", "HTML": "#e34c26", "JavaScript": "#f1e05a", "CSS": "#663399",
               "Stylus": "#ff6347", "Python": "#3572A5", "SCSS": "#c6538c", "Vue": "#41b883",
               "C#": "#178600", "Shell": "#89e051", "Less": "#1d365d"}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def get(path):
    """GET with pagination; returns list (or dict for non-list endpoints)."""
    url, out = f"https://api.github.com/{path}", []
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}",
                                                   "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req) as r:
                if r.status in (202, 204):  # stats still computing / empty repo
                    return {} if r.status == 202 else out
                data = json.load(r)
                link = r.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            if e.code in (404, 409):  # deleted / empty repo
                return out
            if e.code in (403, 429) and ("retry-after" in e.headers or e.headers.get("x-ratelimit-remaining") == "0"):
                reset = int(e.headers.get("x-ratelimit-reset", 0)) - time.time()
                time.sleep(int(e.headers.get("retry-after") or max(reset, 60)) + 1)
                continue
            raise
        if not isinstance(data, list):
            return data
        out += data
        m = re.search(r'<([^>]+)>; rel="next"', link)
        url = m and m.group(1)
    return out


def contributors(repo):
    """Per-author weekly commit counts (default branch). GitHub returns 202 while it computes."""
    for _ in range(10):
        data = get(f"repos/{ORG}/{repo}/stats/contributors")
        if isinstance(data, list):
            return data
        time.sleep(3)
    print(f"warn: stats not ready for {repo}", file=sys.stderr)
    return []


def fmt(n):
    return f"{n:,}"


def size(b):
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024 or unit == "GB":
            return f"{b:.0f} {unit}" if unit in ("B", "KB") else f"{b:.1f} {unit}"
        b /= 1024


def collect():
    since_ts = datetime(YEAR, 1, 1, tzinfo=timezone.utc).timestamp()
    repos = [r["name"] for r in get(f"orgs/{ORG}/repos?per_page=100&type=all") if r["pushed_at"] >= SINCE]
    members = [m["login"] for m in get(f"orgs/{ORG}/members?per_page=100") if m["login"].lower() not in EXCLUDE]
    # Commit search counts real authors (contributor stats also credit Co-authored-by trailers).
    # ponytail: sequential, ~2s/member under the 30/min search limit; fine up to a few hundred members
    by_author = Counter()
    for login in members:
        by_author[login.lower()] = get(f"search/commits?q=org:{ORG}+author:{login}+author-date:>={YEAR}-01-01&per_page=1")["total_count"]
        time.sleep(2.2)
    # Contributor stats narrow down which repos to scan for my own commits.
    candidates = set()
    with ThreadPoolExecutor(4) as pool:
        for repo, stats in zip(repos, pool.map(contributors, repos)):
            if any((e.get("author") or {}).get("login", "").lower() == USER.lower()
                   and any(w["c"] for w in e["weeks"] if w["w"] >= since_ts) for e in stats):
                candidates.add(repo)
    mine, my_repos, langs = [], set(), Counter()
    for repo in candidates:
        dates = [c["commit"]["author"]["date"][:10] for c in get(f"repos/{ORG}/{repo}/commits?author={USER}&since={SINCE}&per_page=100")]
        if dates:
            mine += dates
            my_repos.add(repo)
            langs.update(get(f"repos/{ORG}/{repo}/languages"))
    ranking = [(a, n) for a, n in by_author.most_common() if n]
    return Counter(dict(ranking)), mine, my_repos, langs


def monthly_svg(months, total, end_label):
    n = len(months)
    top = max(months) or 1
    step = max(300, -(-top // 4 // 300) * 300)
    scale = 254 / (step * 4)
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="420" viewBox="0 0 900 420" role="img" aria-label="Monthly commits {YEAR}">',
         '<defs>',
         '<linearGradient id="barBlue" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#79b8ff"/><stop offset="1" stop-color="#1f6feb"/></linearGradient>',
         '<linearGradient id="barPeak" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffd257"/><stop offset="1" stop-color="#e0a70a"/></linearGradient>',
         '</defs>',
         '<rect x="1" y="1" width="898" height="418" rx="16" fill="#0d1117" stroke="#21262d"/>',
         f'<text x="64" y="42" {FONT} font-size="22" font-weight="700" fill="#e6edf3">Monthly Commits &#183; {YEAR}</text>',
         f'<text x="64" y="64" {FONT} font-size="13" fill="#7d8590">{ORG} private org &#183; 1 Jan &#8211; {end_label} &#183; {fmt(total)} total</text>']
    for i in range(5):
        y = 340 - i * step * scale
        s.append(f'<line x1="64" y1="{y:.1f}" x2="868" y2="{y:.1f}" stroke="#21262d" stroke-width="1"/>')
        s.append(f'<text x="54" y="{y + 4:.1f}" text-anchor="end" {FONT} font-size="11" fill="#7d8590">{i * step}</text>')
    slot = 804 / n
    w = slot * 0.6
    peak = months.index(max(months))
    for i, v in enumerate(months):
        cx = 64 + slot * (i + 0.5)
        if v:
            h = v * scale
            color, grad = ("#ffd257", "barPeak") if i == peak else ("#79b8ff", "barBlue")
            s.append(f'<rect x="{cx - w / 2:.1f}" y="{340 - h:.1f}" width="{w:.1f}" height="{h:.1f}" rx="6" fill="url(#{grad})"/>')
            s.append(f'<text x="{cx:.1f}" y="{332 - h:.1f}" text-anchor="middle" {FONT} font-size="13" font-weight="700" fill="{color}">{fmt(v)}</text>')
            if i == peak:
                s.append(f'<text x="{cx:.1f}" y="{310 - h:.1f}" text-anchor="middle" {FONT} font-size="12" fill="#ffd257">&#9733; biggest</text>')
        s.append(f'<text x="{cx:.1f}" y="362.0" text-anchor="middle" {FONT} font-size="13" fill="#c9d1d9">{MONTHS[i]}</text>')
    return "\n".join(s + ["</svg>"])


def languages_svg(langs, repo_count):
    total = sum(langs.values()) or 1
    top = langs.most_common(5)
    rest = langs.most_common()[5:]
    rows = top + ([("Other", sum(b for _, b in rest))] if rest else [])
    s = ['<svg xmlns="http://www.w3.org/2000/svg" width="900" height="384" viewBox="0 0 900 384" role="img" aria-label="Language breakdown">',
         '<rect x="1" y="1" width="898" height="382" rx="16" fill="#0d1117" stroke="#21262d"/>',
         f'<text x="40" y="46" {FONT} font-size="22" font-weight="700" fill="#e6edf3">Languages</text>',
         f'<text x="40" y="70" {FONT} font-size="13" fill="#7d8590">by bytes across {repo_count} {ORG} repositories &#183; {YEAR}</text>']
    circ, offset = 2 * 3.14159265 * 96, 0.0
    for name, b in rows:
        dash = b / total * circ
        color = LANG_COLORS.get(name, "#6e7681")
        s.append(f'<circle cx="175" cy="190" r="96" fill="none" stroke="{color}" stroke-width="40" stroke-dasharray="{dash:.3f} {circ - dash:.3f}" stroke-dashoffset="{-offset:.3f}" transform="rotate(-90 175 190)"/>')
        offset += dash
    s.append(f'<text x="175" y="184" text-anchor="middle" {FONT} font-size="26" font-weight="800" fill="#e6edf3">{len(langs)}</text>')
    s.append(f'<text x="175" y="208" text-anchor="middle" {FONT} font-size="12" fill="#7d8590">languages</text>')
    for i, (name, b) in enumerate(rows):
        y, color = 120 + i * 40, LANG_COLORS.get(name, "#6e7681")
        s.append(f'<rect x="380" y="{y - 13}" width="16" height="16" rx="4" fill="{color}"/>')
        s.append(f'<text x="406" y="{y}" {FONT} font-size="15" font-weight="600" fill="#e6edf3">{name}</text>')
        s.append(f'<text x="630" y="{y}" text-anchor="end" {FONT} font-size="15" font-weight="700" fill="{color}">{b / total * 100:.1f}%</text>')
        s.append(f'<text x="860" y="{y}" text-anchor="end" {FONT} font-size="13" fill="#7d8590">{size(b)}</text>')
    if rest:
        names = ", ".join(n for n, _ in rest[:6])
        s.append(f'<text x="406" y="362" {FONT} font-size="11" fill="#6e7681">Other includes {names}</text>')
    return "\n".join(s + ["</svg>"])


def badge(label, message, color, logo, style_extra=""):
    esc = lambda t: quote(t.replace("-", "--").replace("_", "__").replace(" ", "_"), safe="_")
    msg = f"-{esc(message)}" if message else ""
    logo_q = f"&logo={logo}&logoColor=white" if logo else ""
    return f'  <img src="https://img.shields.io/badge/{esc(label)}{msg}-{color}?style=for-the-badge{style_extra}{logo_q}" alt="{f'{label} {message}'.strip()}"/>'


def replace_block(readme, name, body):
    pat = re.compile(rf"(<!-- STATS:{name}:START -->\n).*?(<!-- STATS:{name}:END -->)", re.S)
    if not pat.search(readme):
        sys.exit(f"README missing STATS:{name} markers")
    return pat.sub(lambda m: m.group(1) + body + "\n" + m.group(2), readme)


def main():
    by_author, mine, my_repos, langs = collect()
    total = len(mine)
    if not total:
        sys.exit(f"no commits found for {USER} in {ORG} — check token access")
    days = Counter(mine)
    ranking = by_author.most_common()
    rank = next((i for i, (a, _) in enumerate(ranking, 1) if a == USER.lower()), len(ranking))
    runner_up = next((n for a, n in ranking if a != USER.lower()), 0)
    lead = f"{total / runner_up:.1f}×" if rank == 1 and runner_up else None
    share = round(by_author[USER.lower()] / sum(by_author.values()) * 100)
    active, busiest = len(days), max(days.values())
    months = [0] * (NOW.month if YEAR == NOW.year else 12)
    for d in mine:
        months[int(d[5:7]) - 1] += 1
    end_label = NOW.strftime("%-d %b") if YEAR == NOW.year else "31 Dec"
    ts_pct = round(langs.get("TypeScript", 0) / (sum(langs.values()) or 1) * 100)

    open("assets/monthly-commits.svg", "w").write(monthly_svg(months, total, end_label))
    open("assets/languages.svg", "w").write(languages_svg(langs, len(my_repos)))

    readme = open("README.md").read()
    readme = replace_block(readme, "COUNTER", f'  <sub><b>Total commits shipped in {YEAR}</b></sub><br/>\n'
        f'  <img src="https://count.getloli.com/get/@{USER}-commits?theme=moebooru&num={total}&padding=4" alt="Total {YEAR} commits counter"/>')
    readme = replace_block(readme, "NUMBERS", "\n".join([
        f"> Private engineering output across the **{ORG}** organization · *1 Jan – {end_label} {YEAR}*.",
        "> These are private-org contributions, so they don't show up in the public graphs below — but they're the real story.",
        "", '<p align="center">',
        badge(f"Commits in {YEAR}", fmt(total), "58A6FF", "git"),
        badge("Org Rank", f"#{rank} of {len(ranking)}", "F5B942", "github"),
        badge("Repositories", str(len(my_repos)), "26C258", "github"),
        "</p>", '<p align="center">',
        badge("Active Days", str(active), "58A6FF", "googlecalendar"),
        badge("Avg / Active Day", str(round(total / active)), "8A63D2", "speedtest"),
        badge("Busiest Day", f"{busiest} commits", "EA4335", "fireship"),
        badge("Share of Org", f"{share}%", "C98BFF", "databricks"),
        "</p>", "",
        f'<p align="center"><b>#{rank} committer of {len(ranking)} org members' + (f" — {lead} the runner-up." if lead else ".") + "</b></p>"]))
    lb = "&labelColor=0d1117"
    readme = replace_block(readme, "HIGHLIGHTS", "\n".join([
        '<p align="center">',
        badge(f"#{rank} Committer", f"of {len(ranking)} in {ORG}", "F5B942", "github", lb),
        badge(fmt(total), f"commits in {YEAR}", "58A6FF", "git", lb),
        *([badge(lead, "lead over #2", "26C258", "", lb)] if lead else []),
        "</p>", '<p align="center">',
        badge(str(busiest), "commits in one day", "EA4335", "fireship", lb),
        badge(str(active), "active coding days", "8A63D2", "googlecalendar", lb),
        badge(str(len(my_repos)), "repositories shipped", "10A37F", "github", lb),
        "</p>", '<p align="center">',
        badge("TypeScript-first", f"{ts_pct}% of the stack", "3178C6", "typescript", lb),
        "</p>"]))
    open("README.md", "w").write(readme)
    print(f"{total} commits, rank {rank}/{len(ranking)}, {len(my_repos)} repos, {active} days, busiest {busiest}")


if __name__ == "__main__":
    main()
