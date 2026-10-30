"""Check local links, anchors and excluded routes in a completed Hugo output."""

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
import xml.etree.ElementTree as ET


class HTMLInfo(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.ids = set()
        self.links = []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("name"):
            self.ids.add(attrs["name"])
        key = {"a": "href", "img": "src", "script": "src", "link": "href"}.get(tag)
        if key and key in attrs:
            self.links.append(attrs[key] or "")


def check(root, base_url, excluded):
    root = root.resolve()
    base = urlsplit(base_url)
    prefix = base.path.rstrip("/")
    pages = {path: HTMLInfo(path) for path in root.rglob("*.html")}
    errors = []
    checked = 0

    def resolve(url, source):
        nonlocal checked
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or parts.netloc != base.netloc:
            return None
        checked += 1
        path = unquote(parts.path)
        if prefix and not (path == prefix or path.startswith(prefix + "/")):
            errors.append({"source": source, "url": url, "reason": "lost site subpath"})
            return None
        local = path[len(prefix):].lstrip("/")
        if "/" + local in excluded:
            errors.append({"source": source, "url": url, "reason": "excluded route is referenced"})
        dest = (root / local).resolve()
        if not dest.is_relative_to(root):
            errors.append({"source": source, "url": url, "reason": "path leaves output directory"})
            return None
        if dest.is_dir():
            dest = dest / "index.html"
        if not dest.is_file():
            errors.append({"source": source, "url": url, "reason": "target file missing"})
            return None
        return dest, unquote(parts.fragment)

    for page, info in pages.items():
        relative = page.relative_to(root).as_posix()
        route = relative.removesuffix("index.html") if relative.endswith("index.html") else relative
        page_url = urljoin(base_url.rstrip("/") + "/", route)
        for href in info.links:
            if not href:
                errors.append({"source": relative, "url": href, "reason": "empty link or asset URL"})
                continue
            target = resolve(urljoin(page_url, href), relative)
            if target and target[1] and target[0].suffix == ".html":
                destination = pages.get(target[0])
                if destination is None:
                    destination = HTMLInfo(target[0])
                if target[1] not in destination.ids:
                    errors.append({"source": relative, "url": href, "reason": "anchor missing"})

    sitemap = root / "sitemap.xml"
    if sitemap.exists():
        for loc in ET.parse(sitemap).iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
            resolve(loc.text or "", "sitemap.xml")
    for route in excluded:
        target = root / route.lstrip("/")
        if target.is_dir():
            target = target / "index.html"
        if target.is_file():
            errors.append({"source": "output", "url": route, "reason": "excluded route was rendered"})
    return {"html_files": len(pages), "local_references_checked": checked, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=["production", "drafts"], required=True,
                        help="Output label; excluded routes must be provided explicitly for each mode.")
    parser.add_argument("--base-url", default="https://dshilin.github.io/")
    parser.add_argument("--exclude-url", action="append", default=[])
    args = parser.parse_args()
    if not args.root.is_dir() or not (args.root / "index.html").is_file():
        parser.error("root must contain a completed site with index.html")
    result = check(args.root, args.base_url, set(args.exclude_url))
    result["mode"] = args.mode
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(result["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
