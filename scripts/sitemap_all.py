#!/usr/bin/env python3
"""Write `site/sitemap-all.xml`: one sitemap index that lists the sitemaps of all the archives.

Submit this single file in Google Search Console (Domain property `sauthier.family`): a sitemap
index may list sitemaps hosted on other hosts of the same verified domain. A sitemap index cannot
contain another index, so a site whose own sitemap is an index (Nectarine) is listed through its
child files. The list below is static, so the build stays offline and deterministic.

Run it after `scripts/seo.py` (which deletes every `sitemap*.xml` first); `publish.sh` does.
It also adds a `Sitemap:` line for the index to `site/robots.txt`.

Usage: python3 -I scripts/sitemap_all.py [--site DIR] [--check]
  --check  fetch every listed sitemap from the live sites (retries on network hiccups) and verify
           it is reachable, well formed and that no site now has a sitemap index not listed here.
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parent.parent
DOMAIN = "sauthier.family"
# One entry per archive; the value lists its sitemap file(s) at the site root.
SITES = {
    "bomb98": ["sitemap.xml"],
    "chandra97": ["sitemap.xml"],
    "citeweb97": ["sitemap.xml"],
    "citeweb98": ["sitemap.xml"],
    "ltp2-party": ["sitemap.xml"],
    "ltp3": ["sitemap.xml"],
    "ltp3-party": ["sitemap.xml"],
    "ltp4": ["sitemap.xml"],
    "ltp4-party": ["sitemap.xml"],
    "ltp4-postparty": ["sitemap.xml"],
    "made99": ["sitemap.xml"],
    "nectarine": ["sitemap-1.xml", "sitemap-2.xml"],  # its sitemap.xml is itself an index
    "orangejuice97": ["sitemap.xml"],
    "orangejuice98": ["sitemap.xml"],
    "orangejuice99": ["sitemap.xml"],
    "orangejuicev3": ["sitemap.xml"],
    "ribbon98": ["sitemap.xml"],
    "sceneorg": ["sitemap.xml"],
}
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
OWN = "chandra97"


def sitemap_urls():
    return ["https://%s.%s/%s" % (name, DOMAIN, f) for name, files in sorted(SITES.items()) for f in files]


def build_index():
    body = "".join("  <sitemap><loc>%s</loc></sitemap>\n" % escape(u) for u in sitemap_urls())
    return '<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="%s">\n%s</sitemapindex>\n' % (NS, body)


def fetch(url, tries=4):
    last = None
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sitemap-all-check"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except Exception as e:  # network hiccup or HTTP error: retry, then report
            last = e
            time.sleep(2 * (n + 1))
    return None, str(last).encode()


def check():
    problems = []
    for name, files in sorted(SITES.items()):
        host = "%s.%s" % (name, DOMAIN)
        for f in files:
            status, raw = fetch("https://%s/%s" % (host, f))
            if status != 200:
                problems.append("%s/%s: HTTP %s (%s)" % (host, f, status, raw[:80]))
                continue
            text = raw.decode("utf-8", "replace")
            if "<urlset" not in text:
                problems.append("%s/%s: not a <urlset>" % (host, f))
            elif not re.search(r"<loc>https://%s/" % re.escape(host), text):
                problems.append("%s/%s: no URL on its own host" % (host, f))
        if files == ["sitemap.xml"]:
            continue
        status, raw = fetch("https://%s/sitemap.xml" % host)
        kids = sorted(re.findall(r"<loc>https://%s/([^<]+)</loc>" % re.escape(host), raw.decode("utf-8", "replace")))
        if status == 200 and kids != sorted(files):
            problems.append("%s: its sitemap.xml lists %s, expected %s" % (host, kids, sorted(files)))
    for name, files in SITES.items():  # a site that became an index since the list was written
        if files != ["sitemap.xml"]:
            continue
        status, raw = fetch("https://%s.%s/sitemap.xml" % (name, DOMAIN))
        if status == 200 and b"<sitemapindex" in raw:
            problems.append("%s: sitemap.xml is now a sitemap index, list its children" % name)
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", type=Path, default=REPO / "site")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.check:
        problems = check()
        for p in problems:
            print("FAIL", p)
        print("sitemap_all --check: %d sitemap(s), %d problem(s)" % (len(sitemap_urls()), len(problems)))
        sys.exit(1 if problems else 0)
    site = args.site.resolve()
    if not site.is_dir():
        sys.exit("no site directory: %s" % site)
    host = json.loads((REPO / "site.json").read_text(encoding="utf-8"))["hostname"]
    (site / "sitemap-all.xml").write_text(build_index(), encoding="utf-8")
    robots = site / "robots.txt"
    line = "Sitemap: https://%s/sitemap-all.xml\n" % host
    text = robots.read_text(encoding="ascii") if robots.is_file() else "User-agent: *\nAllow: /\n"
    if line not in text:
        robots.write_text(text.rstrip("\n") + "\n" + line, encoding="ascii")
    print("sitemap_all: %d sitemaps listed in sitemap-all.xml" % len(sitemap_urls()))


if __name__ == "__main__":
    main()
