#!/usr/bin/env python3
"""Generate site/ from the raw store (Chandra's web site, January 1997).

    python3 -I scripts/build.py [--raw ~/Code/id3x/raw] [--out site]

Read-only on the raw store. Deterministic: the output only depends on the inputs.

Two raw folders are merged:
  chandra_rebuts/  the Chandra site (frameset index.html, title.htm, main.htm, ...)
  hotdir97/        the HotDIR home page, formerly published alone (its index.html becomes hdir.htm,
                   the page that main.htm always linked)

Only what a page of the site reaches is published (crawl from index.html). Paths are lowercased,
`me.shtm` becomes `me.htm`, links to dead third-party hosts become plain text, counters and the SSI
sponsor include are removed, e-mail addresses are masked as `local＠????` and the pages that show one
(or a real name, or archives with personal data) end with the removal footer. Third-party files
(zip, rar, exe, ra, mid, mp3) are copied byte-identical.
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from posixpath import normpath, join as pjoin, dirname
from urllib.parse import unquote

REPO = Path(__file__).resolve().parent.parent
ENC = "iso-8859-1"
FULLWIDTH_AT = "&#65312;"
NICK = "chandra"  # addresses with this local part (the author's nick, defunct) are left complete

# HotDIR files that are not published, by reason (everything else is reached by the crawl).
HOTDIR_SKIP = {"copy of index.html", "robots.txt", "sitemap.xml", "wired98/newsf.htm"}
RENAME = {"me.shtm": "me.htm"}                     # Chandra: SSI page, its own links already say me.htm
HOTDIR_RENAME = {"index.html": "hdir.htm"}         # HotDIR: home page -> the page main.htm links
EXTRA_LINKS = {                                    # one link added: the optimised module page of HotDIR
    "modules.htm": (
        "(S3M, 2149 ko)</h3>",
        '(S3M, 2149 ko)</h3>\n\n<p align="center"><a href="index_sheep.html">Same module, optimised by '
        "me (zipped XM, 1191 ko)</a></p>",
    ),
}
# Pages that get the removal footer even without an e-mail address: real names, or archives whose
# text files hold personal data (shipped untouched).
FOOTER_PAGES = {"hdir.htm", "modules.htm", "index_sheep.html", "software.htm"}

REMOVAL_NOTE = (
    '<div id="removal-note" style="clear:both;margin:28px auto 8px;padding:6px 8px 0;width:60%;'
    'border-top:1px solid #808080;text-align:center;font:10px/14px Verdana,Arial,Helvetica,sans-serif;'
    'color:#808080;background:transparent">To be removed from this page, '
    '<a href="mailto:chandra_oj@pm.me" style="color:#808080;text-decoration:underline">contact me</a>.</div>'
)
HOME_NOTE = (
    '<div id="archive-note" style="margin:24px auto 8px;padding:6px 8px 0;width:70%;'
    'border-top:1px solid #808080;text-align:center;font:11px/15px Verdana,Arial,Helvetica,sans-serif;'
    'color:#a0a0a0;background:transparent">Archive of Chandra\'s web site as it was in January 1997 (pages '
    "updated 1997-01-29). Read-only: counters, e-mail links and links to other sites no longer work. Full "
    'list of the old sites: <a href="https://chanoj.github.io/" target="_top" style="color:#a0a0a0">'
    "chanoj.github.io</a>.</div>"
)
NOT_FOUND = """<HTML>
<HEAD>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=iso-8859-1">
<TITLE>Chandra's Web Site - page not found</TITLE>
</HEAD>
<BODY BACKGROUND="/back.gif" BGCOLOR="#000000" TEXT="#00FF00" LINK="#FFFFFF" VLINK="#C0C0C0">
<CENTER><BR><BR>
<H1>404 - File not found</H1>
<TT>This page is not part of the archive of Chandra's web site (1997).
<A HREF="/">Back to the home page</A>.</TT>
</CENTER>
</BODY>
</HTML>
"""

TAG_A = re.compile(r"(?is)<a\b[^>]*>|</a\s*>")
TAG_MEDIA = re.compile(r"(?is)<(?:img|frame|embed)\b[^>]*>")
ATTR = lambda name: re.compile(r"""(?is)(\s%s\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s>]+))""" % name)
HREF, SRCATTR, BACKGROUND = ATTR("href"), ATTR("src"), ATTR("background")
MAILTO_A = re.compile(r"""(?is)<a\b[^>]*href\s*=\s*["']?mailto:([^"'>\s?]+)[^>]*>(.*?)</a\s*>""")
EMAIL = re.compile(r"(?i)\b([A-Za-z0-9._+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
COUNTER_LINE = re.compile(r"(?is)(?:<strong>)?Number of visitors:\s*(?:<img\b[^>]*compteur\.gif[^>]*>)?")
SSI = re.compile(r"(?is)<!--#exec[^>]*-->")
HTML_EXT = (".htm", ".html")


def rd(p):
    return Path(p).read_bytes().decode(ENC)


def wr(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode(ENC, "xmlcharrefreplace"))


def attr_value(m):
    return next(g for g in m.groups()[1:] if g is not None)


class Site:
    def __init__(self, raw):
        raw = Path(raw).expanduser()
        self.src = {}      # published path (lowercase) -> source file
        self.origin = {}   # published path -> "chandra" | "hotdir"
        for name, skip, rename in (("hotdir97", HOTDIR_SKIP, HOTDIR_RENAME), ("chandra_rebuts", (), RENAME)):
            root = raw / name
            for r, ds, fs in os.walk(root):
                ds.sort()
                for f in sorted(fs):
                    p = Path(r, f)
                    rel = p.relative_to(root).as_posix().lower()
                    if f == ".DS_Store" or rel in skip or rel.startswith("wired98/"):
                        continue
                    dest = rename.get(rel, rel)
                    assert dest not in self.src, dest  # no overlap once HotDIR's index.html is renamed
                    self.src[dest] = p
                    self.origin[dest] = "chandra" if name == "chandra_rebuts" else "hotdir"
        self.unresolved = {}
        self.reached = set()

    def resolve(self, page, href):
        """('url', published URL) | ('keep', href) | ('drop', None)."""
        href = href.strip()
        low = href.lower()
        if low.startswith("mailto:" + NICK + "@"):
            return "keep", href
        if low.startswith(("javascript:", "data:", "mailto:")):
            return "drop", None
        if low.startswith("#"):
            return "keep", href
        frag = ""
        if "#" in href:
            href, _, frag = href.partition("#")
            frag = "#" + frag
        if re.match(r"(?i)^([a-z][a-z0-9+.-]*:|//)", href):
            return "drop", None  # dead third-party hosts: plain text
        path = unquote(href.split("?", 1)[0]).replace("\\", "/")
        if path == "":
            return "drop", None
        if self.origin.get(page) == "hotdir" and path.lower() == "index.html":
            path = "hdir.htm"
        v = normpath(path.lstrip("/") if path.startswith("/") else pjoin(dirname(page), path)).lower()
        if v.startswith(".."):
            return "drop", None
        v = RENAME.get(v, v)
        if v in self.src:
            self.reached.add(v)
            return "url", ("/" if v == "index.html" else "/" + v) + frag
        self.unresolved.setdefault(v, set()).add(page)
        return "drop", None

    def rewrite(self, rel, text):
        out, pos, unwrap = [], 0, []
        for m in TAG_A.finditer(text):
            out.append(text[pos:m.start()])
            pos = m.end()
            tag = m.group(0)
            if tag.startswith("</"):
                out.append("" if unwrap and unwrap.pop() else "</a>")
                continue
            h = HREF.search(tag)
            if not h:
                out.append(tag)
                unwrap.append(False)
                continue
            kind, val = self.resolve(rel, attr_value(h))
            if kind in ("url", "keep"):
                out.append(HREF.sub(lambda mm: '%s"%s"' % (mm.group(1), val), tag, count=1))
                unwrap.append(False)
            else:
                out.append("")
                unwrap.append(True)
        out.append(text[pos:])
        text = "".join(out)

        def media(m):
            tag = re.sub(r"(?i)\s+ismap\b", "", m.group(0))
            h = SRCATTR.search(tag)
            if h:
                kind, val = self.resolve(rel, attr_value(h))
                if kind != "url":
                    return ""
                tag = SRCATTR.sub(lambda mm: '%s"%s"' % (mm.group(1), val), tag, count=1)
            return tag

        text = TAG_MEDIA.sub(media, text)

        def body_bg(m):
            tag = m.group(0)
            h = BACKGROUND.search(tag)
            if h:
                kind, val = self.resolve(rel, attr_value(h))
                tag = BACKGROUND.sub(lambda mm: '%s"%s"' % (mm.group(1), val) if kind == "url" else "", tag, count=1)
            return tag

        return re.sub(r"(?is)<body\b[^>]*>", body_bg, text)

    def sanitize(self, rel, text):
        text = SSI.sub("", text)
        text = COUNTER_LINE.sub("", text)
        if rel in EXTRA_LINKS:
            old, new = EXTRA_LINKS[rel]
            assert old in text, rel
            text = text.replace(old, new, 1)

        def mail(m):
            if m.group(1).split("@")[0].lower() == NICK:
                return m.group(0)  # the nick's own (defunct) address stays as it was
            local = m.group(1).split("@")[0]
            label = re.sub(r"(?:&nbsp;|\s)+$", "", m.group(2))
            return "%s (%s%s????)" % (label, local, FULLWIDTH_AT)

        text = MAILTO_A.sub(mail, text)
        text = EMAIL.sub(lambda m: m.group(0) if m.group(1).lower() == NICK else m.group(1) + FULLWIDTH_AT + "????", text)
        if not re.search(r"(?i)charset\s*=", text):
            text = re.sub(r"(?i)(<head[^>]*>)", r'\1<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">', text, count=1)
        return text

    @staticmethod
    def _append(text, note):
        m = re.search(r"(?is)</body\s*>(?!.*</body\s*>)", text)
        if m:
            return text[: m.start()] + note + "\n" + text[m.start():]
        return text + "\n" + note + "\n"

    def run(self, out):
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        queue, done, pages = ["index.html"], set(), {}
        while queue:  # crawl: pages reached from the home page
            rel = queue.pop(0)
            if rel in done:
                continue
            done.add(rel)
            if rel.endswith(HTML_EXT):
                text = self.rewrite(rel, self.sanitize(rel, rd(self.src[rel])))
                if FULLWIDTH_AT + "????" in text or rel in FOOTER_PAGES:
                    text = self._append(text, REMOVAL_NOTE)
                if rel == "main.htm":
                    text = self._append(text, HOME_NOTE)
                pages[rel] = text
            queue.extend(sorted(self.reached - done))
        for rel in sorted(done):
            d = out / rel
            if rel in pages:
                wr(d, pages[rel])
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.src[rel], d)
        wr(out / "404.html", NOT_FOUND)
        self.skipped = sorted(set(self.src) - done)
        return len(done) + 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raw", default=os.environ.get("CHANDRA97_RAW", "~/Code/id3x/raw"))
    ap.add_argument("--out", default=str(REPO / "site"))
    a = ap.parse_args(argv)
    s = Site(a.raw)
    n = s.run(Path(a.out))
    print("build: %d files in %s" % (n, a.out))
    print("not reached from the home page, not published: %d" % len(s.skipped))
    for k in s.skipped:
        print("   ", k)
    un = {k: sorted(v)[:2] for k, v in sorted(s.unresolved.items())}
    print("unresolved link targets (made plain text or dropped): %d" % len(un))
    for k, v in un.items():
        print("   ", k, "<-", v)


if __name__ == "__main__":
    sys.exit(main())
