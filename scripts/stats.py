#!/usr/bin/env python3
"""Rewrite the stats blocks in README.md from every repo the token's owner has, private ones included.

LANGS: share of code per language. COMMITS: your commits by time of day and by weekday, across all branches.
RECENT: your most recently pushed public repos, plus how many private ones were active lately.
Only totals leave the private repos: never repo names, messages or code.
Needs GH_TOKEN: a token that can read all your repos (fine-grained: All repositories, Metadata + Contents: read).
TZ sets the time zone the commit hours are counted in (default Asia/Kolkata).
"""
import datetime
import json
import os
import re
import sys
import urllib.request
from zoneinfo import ZoneInfo

TOP = 8
WIDTH = 25
RECENT = 5
ACTIVE_DAYS = 30
IGNORE = {"Dockerfile", "Makefile", "Procfile", "Batchfile"}
README = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "README.md")
TZ = ZoneInfo(os.environ.get("TZ") or "Asia/Kolkata")
PERIODS = [("🌞 Morning", 6, 12), ("🌆 Daytime", 12, 18), ("🌃 Evening", 18, 24), ("🌙 Night", 0, 6)]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def get(url):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req) as r:
        link = r.headers.get("Link", "")
        nxt = re.search(r'<([^>]+)>;\s*rel="next"', link)
        body = r.read()
        return (json.loads(body) if body else []), nxt.group(1) if nxt else None


def pages(url):
    while url:
        page, url = get(url)
        yield from page


def bars(rows, total, label_w, value_w=0):
    out = []
    for label, value, shown in rows:
        pct = value * 100 / total if total else 0
        filled = round(pct * WIDTH / 100)
        out.append(f"{label.ljust(label_w)}  {shown.ljust(value_w)}{'█' * filled}{'░' * (WIDTH - filled)}  {pct:5.1f} %")
    return "```text\n" + "\n".join(out) + "\n```\n"


def replace(text, marker, block):
    pattern = rf"(<!--{marker}:START-->\n).*?(<!--{marker}:END-->)"
    if not re.search(pattern, text, flags=re.S):
        sys.exit(f"{marker} markers not found in README.md")
    return re.sub(pattern, lambda m: m.group(1) + block + m.group(2), text, flags=re.S)


def ago(when, now):
    days = (now - when).days
    return "today" if days < 1 else "yesterday" if days < 2 else f"{days} days ago"


def recent_block(public, private_active, recent_commits, now):
    rows = []
    for repo in sorted(public, key=lambda r: r["pushed_at"], reverse=True)[:RECENT]:
        desc = (repo["description"] or "").replace("|", "\\|").strip()
        if len(desc) > 90:
            desc = desc[:90].rsplit(" ", 1)[0].rstrip(".,;:—-") + "…"
        lang = f"`{repo['language']}`" if repo["language"] else ""
        rows.append(f"| [{repo['name']}]({repo['html_url']}) | {desc} | {lang} | {ago(parse(repo['pushed_at']), now)} |")
    out = "| Repo | What it is | Lang | Last push |\n|---|---|---|---|\n" + "\n".join(rows) + "\n\n"
    extra = [f"🔥 {recent_commits} commits in the last {ACTIVE_DAYS} days"]
    if private_active:
        extra.append(f"🔒 +{private_active} private repo{'s' * (private_active != 1)} active")
    return out + "<sub>" + " · ".join(extra) + "</sub>\n"


def parse(stamp):
    return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def main():
    me, _ = get("https://api.github.com/user")
    login = me["login"]
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=ACTIVE_DAYS)
    langs, shas, count = {}, {}, 0
    public, private_active = [], 0
    for repo in pages("https://api.github.com/user/repos?affiliation=owner&per_page=100"):
        if repo["fork"] or repo["name"] == login:
            continue
        count += 1
        if not repo["private"]:
            public.append(repo)
        elif repo["pushed_at"] and parse(repo["pushed_at"]) >= cutoff:
            private_active += 1
        sizes, _ = get(repo["languages_url"])
        for lang, size in sizes.items():
            if lang not in IGNORE:
                langs[lang] = langs.get(lang, 0) + size
        if repo["size"] == 0:
            continue
        base = repo["url"]
        for branch in pages(f"{base}/branches?per_page=100"):
            for c in pages(f"{base}/commits?sha={branch['name']}&author={login}&per_page=100"):
                shas[c["sha"]] = c["commit"]["author"]["date"]
    if not langs:
        sys.exit("no languages found: check GH_TOKEN can read your repos")

    ranked = sorted(langs.items(), key=lambda kv: -kv[1])
    rows = ranked[:TOP]
    rest = sum(size for _, size in ranked[TOP:])
    if rest:
        rows.append(("Other", rest))
    today = datetime.date.today().isoformat()
    lang_block = (bars([(n, s, "") for n, s in rows], sum(langs.values()), max(len(n) for n, _ in rows))
                  + f"<sub>{count} repos · updated {today}</sub>\n")

    times = [parse(d).astimezone(TZ) for d in shas.values()]
    total = len(times)
    by_period = [(name, sum(lo <= t.hour < hi for t in times)) for name, lo, hi in PERIODS]
    by_day = [(day, sum(t.weekday() == i for t in times)) for i, day in enumerate(DAYS)]
    early = sum(n for name, n in by_period if "Morning" in name or "Daytime" in name)
    kind = "an early 🐤" if early >= total - early else "a night 🦉"
    best = max(by_day, key=lambda kv: kv[1])[0]
    fmt = lambda rows: [(name, n, f"{n} commits") for name, n in rows]
    commit_block = (f"**I'm {kind}** · {total} commits\n\n"
                    + bars(fmt(by_period), total, 10, 14)
                    + f"\n📅 **I'm most productive on {best}**\n\n"
                    + bars(fmt(by_day), total, 10, 14))

    with open(README, encoding="utf-8") as f:
        text = f.read()
    text = replace(text, "LANGS", lang_block)
    text = replace(text, "COMMITS", commit_block)
    recent_commits = sum(parse(d) >= cutoff for d in shas.values())
    text = replace(text, "RECENT", recent_block(public, private_active, recent_commits, now))
    with open(README, "w", encoding="utf-8") as f:
        f.write(text)
    print(lang_block + "\n" + commit_block)


if __name__ == "__main__":
    main()
