"""Rebuild knowledge.md from the school site: python update_knowledge.py

Crawls rtsosh-khujand.tj, strips HTML, drops the Tajik mirror and the
navigation lines repeated on every page. Standard library only.
"""
import re
import ssl
import urllib.parse
import urllib.request
from collections import Counter, deque
from html.parser import HTMLParser

BASE = "https://rtsosh-khujand.tj"
MAX_PAGES = 150  # news pagination is skipped, so this only bounds runaway crawls
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".pdf", ".doc", ".docx", ".xls",
            ".xlsx", ".css", ".js", ".ico", ".svg", ".zip", ".webp", ".mp4")
# ponytail: certificate check off because the site's chain fails on some machines
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.links, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag == "a":
            self.links += [v for k, v in attrs if k == "href" and v]
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=CTX) as response:
        return response.read().decode("utf-8", "replace")


def clean(text):
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def crawl():
    seen, queue, pages = set(), deque(["/"]), []
    while queue and len(pages) < MAX_PAGES:
        path = queue.popleft()
        if path in seen or path.startswith("/tg/"):  # Tajik mirror of the same pages
            continue
        seen.add(path)
        url = urllib.parse.urljoin(BASE, path)
        try:
            html = fetch(url)
        except Exception as error:
            print("skip", path, error)
            continue
        parser = Text()
        parser.feed(html)
        title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        pages.append((path, title.group(1).strip() if title else path, clean("".join(parser.out))))
        print("ok", path)
        for href in parser.links:
            href = urllib.parse.urljoin(url, href.split("#")[0].split("?")[0])
            if not href.startswith(BASE):
                continue
            rel = href[len(BASE):] or "/"
            if rel.lower().endswith(SKIP_EXT) or rel.startswith(("/bitrix", "/local", "/tg/")):
                continue
            if rel not in seen:
                queue.append(rel)
    return pages


def drop_boilerplate(pages):
    counts = Counter()
    for _, _, text in pages:
        counts.update({line for line in text.splitlines() if line})
    repeated = {line for line, n in counts.items() if n > len(pages) * 0.5}
    return [(path, title, "\n".join(l for l in text.splitlines() if l not in repeated))
            for path, title, text in pages]


if __name__ == "__main__":
    pages = drop_boilerplate(crawl())
    with open("knowledge.md", "w", encoding="utf-8") as f:
        f.write("# База знаний: сайт школы rtsosh-khujand.tj\n")
        for path, title, text in pages:
            f.write(f"\n\n## {title}\nURL: {BASE}{path}\n\n{clean(text)}\n")
    print("pages:", len(pages))
