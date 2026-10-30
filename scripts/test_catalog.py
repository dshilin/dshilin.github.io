"""Integration checks against real Hugo builds; fixtures stay outside author content."""

import json
import os
from pathlib import Path
import struct
import subprocess
import unittest
import zlib
from html.parser import HTMLParser
from urllib.parse import urlsplit
from uuid import uuid4
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[1]
def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


# A synthetic one-pixel fixture with explicit, valid PNG checksums.
PNG = (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
       + png_chunk(b"IDAT", zlib.compress(b"\x00\x80\x80\x80\xff")) + png_chunk(b"IEND", b""))


class Element:
    def __init__(self, tag="root", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def find(self, predicate):
        return [n for n in self.walk() if predicate(n)]

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()

    def text(self):
        return "".join(c.text() if isinstance(c, Element) else c for c in self.children)


class Document(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, path):
        super().__init__()
        self.root = Element()
        self.stack = [self.root]
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def by_id(self, value):
        nodes = self.root.find(lambda n: n.attrs.get("id") == value)
        return nodes[0] if nodes else None

    def posts(self):
        return self.root.find(lambda n: n.tag == "article" and "journal-post" in n.attrs.get("class", "").split())

    def post_links(self):
        result = []
        for article in self.posts():
            headings = article.find(lambda n: n.tag == "h3")
            result.extend(n.attrs["href"] for heading in headings for n in heading.find(lambda n: n.tag == "a"))
        return result


def write_page(content, path, **fields):
    target = content / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\n" + json.dumps(fields, ensure_ascii=False) + "\n---\n\nFixture body.\n", encoding="utf-8")
    return target


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = REPO / ".superpowers/site-review" / ("catalog-" + uuid4().hex[:8])
        cls.work.mkdir(parents=True)
        (cls.work.parent / ".gitignore").write_text("*\n", encoding="utf-8")
        content = cls.work / "content"
        content.mkdir()
        write_page(content, "_index.md", title="Fixture home", tagline="Fixture home")
        write_page(content, "about.md", title="Fixture author")
        write_page(content, "blog/_index.md", title="Статьи")
        # Published children must work even when the redundant parent hub is hidden.
        hidden = dict(draft=True, build=dict(render="never", list="never"), cascade=dict(sidebar=dict(hide=True)))
        write_page(content, "docs/_index.md", title="Hidden docs", **hidden)
        write_page(content, "docs/python/_index.md", title="Hidden Python hub", **hidden)
        published = [
            ("blog/review-blog.md", "2026-10-29", ["Alpha", "Beta", "pytest"], "Tech", True),
            ("docs/python/review-python.md", "2026-10-28", ["Alpha"], "Tech", True),
            ("blog/review-photo-a/index.md", "2026-10-27", ["Alpha"], "Life", False),
            ("blog/review-photo-b/index.md", "2026-10-26", ["Beta"], "Life", False),
            ("docs/python/review-photo-c/index.md", "2026-10-25", ["Alpha"], "Tech", True),
            ("blog/review-ai/index.md", "2026-10-24", ["Alpha"], "Tech", False),
        ]
        cls.expected = []
        for path, date, tags, category, python in published:
            slug = Path(path).parent.name if path.endswith("/index.md") else Path(path).stem
            fields = dict(title=slug, date=date, tags=tags, categories=[category], description=slug + " description")
            if python:
                fields.update(career_track="python", type="docs")
            if "photo-" in slug:
                fields["photos"] = [dict(src="photo.png", alt=slug + " photo", kind="photo")]
                if slug.endswith("-c"):
                    fields["photos"].append(dict(src="second.png", alt="Another photo from same post", kind="photo"))
            elif slug == "review-ai":
                fields["photos"] = [dict(src="ai.png", alt="AI image excluded from photographs", kind="illustration", ai_generated=True)]
            page = write_page(content, path, **fields)
            for photo in fields.get("photos", []):
                (page.parent / photo["src"]).write_bytes(PNG)
            url = "/" + (str(Path(path).parent).replace("\\", "/") if path.endswith("/index.md") else str(Path(path).with_suffix("")).replace("\\", "/")) + "/"
            cls.expected.append(url)
        for name, options in [("draft-secret", dict(date="2026-10-23", draft=True)), ("future-secret", dict(date="2099-01-01"))]:
            page = write_page(content, f"blog/{name}/index.md", title=name, tags=[name], categories=[name],
                              photos=[dict(src="secret.png", alt=name, kind="photo")], **options)
            (page.parent / "secret.png").write_bytes(PNG)
        write_page(content, "landing.md", title="Unrelated landing", tags=["Alpha", "NotAnArticle"], categories=["Other"])
        cls.outputs = {}
        env = os.environ.copy()
        env["HUGO_PAGINATION_PAGERSIZE"] = "2"
        for mode, base, flags in [("production", "https://example.test/", []),
                                  ("drafts", "https://example.test/", ["--buildDrafts"]),
                                  ("subpath", "https://example.test/notes/", [])]:
            dest = cls.work / mode
            run = subprocess.run(["hugo", "--minify", "--contentDir", str(content), "--destination", str(dest),
                                  "--baseURL", base, *flags], cwd=REPO, env=env, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace")
            (cls.work / (mode + ".log")).write_text(run.stdout + "\n" + run.stderr, encoding="utf-8")
            if run.returncode:
                raise RuntimeError(run.stdout[-1200:] + run.stderr[-1600:])
            cls.outputs[mode] = dest
        print("\nHugo fixture outputs:", cls.work, flush=True)

    def doc(self, mode="production", page="blog/index.html"):
        return Document(self.outputs[mode] / page)

    def test_all_articles_across_sections_in_html_and_rss_without_duplicates(self):
        found = []
        for page in ["blog/index.html", "blog/page/2/index.html", "blog/page/3/index.html"]:
            self.assertTrue((self.outputs["production"] / page).is_file(), page)
            found.extend(self.doc(page=page).post_links())
        self.assertEqual(found, self.expected)
        rss = ET.parse(self.outputs["production"] / "blog/index.xml")
        self.assertEqual([urlsplit(n.text).path for n in rss.findall("./channel/item/link")], self.expected)
        home = self.doc(page="index.html").post_links()
        self.assertEqual(home, self.expected[:3])

    def test_cloud_counts_whole_catalog_not_landing_or_current_pagination_page(self):
        for page in ["blog/index.html", "blog/page/2/index.html", "blog/page/3/index.html"]:
            cloud = self.doc(page=page).by_id("journal-topic-cloud")
            self.assertIsNotNone(cloud, "Topic cloud must exist below the list")
            counts = {n.attrs["data-topic"]: int(n.attrs["data-count"]) for n in cloud.find(lambda n: n.tag == "a")}
            self.assertEqual(counts, {"Alpha": 5, "Beta": 2, "pytest": 1})

    def test_category_navigation_and_topic_pages_use_same_article_collection(self):
        nav = self.doc().by_id("journal-categories")
        self.assertIsNotNone(nav)
        counts = {n.attrs["data-category"]: int(n.attrs["data-count"]) for n in nav.find(lambda n: n.tag == "a" and "data-category" in n.attrs)}
        self.assertEqual(counts, {"Tech": 4, "Life": 2})
        alpha = []
        for page in ["tags/alpha/index.html", "tags/alpha/page/2/index.html", "tags/alpha/page/3/index.html"]:
            alpha.extend(self.doc(page=page).post_links())
        self.assertEqual(alpha, [p for p in self.expected if "photo-b" not in p])

    def test_draft_and_future_data_never_reaches_production_outputs(self):
        for file in self.outputs["production"].rglob("*"):
            if file.suffix in {".html", ".json", ".xml", ".js"}:
                text = file.read_text(encoding="utf-8")
                self.assertNotIn("draft-secret", text, str(file))
                self.assertNotIn("future-secret", text, str(file))
        self.assertTrue((self.outputs["drafts"] / "blog/draft-secret/index.html").is_file())
        self.assertFalse((self.outputs["drafts"] / "blog/future-secret/index.html").exists())

    def test_photo_pool_has_only_explicit_photographs_from_published_posts(self):
        scripts = self.doc().root.find(lambda n: "data-journal-photo-data" in n.attrs)
        self.assertEqual(len(scripts), 1)
        photos = json.loads(scripts[0].text())
        self.assertEqual(len(photos), 4)
        self.assertEqual(len({p["post_url"] for p in photos}), 3)
        grid = self.doc().by_id("journal-photo-grid")
        self.assertIsNotNone(grid)
        links = grid.find(lambda n: n.tag == "a")
        self.assertEqual(len(links), 3)
        self.assertEqual(len({n.attrs["href"] for n in links}), 3)
        for photo in photos:
            self.assertNotIn("review-ai", photo["post_url"])
            self.assertTrue(photo["alt"])
            self.assertTrue((self.outputs["production"] / urlsplit(photo["src"]).path.lstrip("/")).is_file())

    def test_subpath_links_and_photo_sources_keep_the_site_prefix(self):
        doc = self.doc("subpath")
        main = doc.by_id("content")
        for node in main.find(lambda n: n.tag in {"a", "img"}):
            value = node.attrs.get("href", node.attrs.get("src", "")) or ""
            self.assertTrue(value, "Catalog links and images must have a destination")
            if value.startswith("/"):
                self.assertTrue(value.startswith("/notes/"), value)
        scripts = doc.root.find(lambda n: "data-journal-photo-data" in n.attrs)
        self.assertEqual(len(scripts), 1)
        for photo in json.loads(scripts[0].text()):
            self.assertTrue(photo["post_url"].startswith("/notes/"))
            self.assertTrue(photo["src"].startswith("/notes/"))

    def test_post_cards_link_to_both_taxonomies(self):
        first = self.doc().posts()[0]
        hrefs = {n.attrs["href"] for n in first.find(lambda n: n.tag == "a")}
        self.assertIn("/categories/tech/", hrefs)
        self.assertIn("/tags/alpha/", hrefs)
        self.assertIn("/tags/beta/", hrefs)

    def test_hidden_hubs_have_no_pages_or_dead_article_navigation(self):
        for mode, prefix in [("production", ""), ("drafts", ""), ("subpath", "/notes")]:
            output = self.outputs[mode]
            self.assertFalse((output / "docs/index.html").exists())
            self.assertFalse((output / "docs/python/index.html").exists())
            article = self.doc(mode, "docs/python/review-python/index.html")
            main = article.by_id("content")
            links = [n.attrs.get("href") for n in main.find(lambda n: n.tag == "a")]
            self.assertIn(prefix + "/blog/", links, "Article must have a working route back to the catalog")
            for href in links:
                self.assertTrue(href, "Hidden ancestors must not create empty breadcrumb links")
                self.assertNotIn(href, [prefix + "/docs/", prefix + "/docs/python/"])

    def test_photo_block_with_zero_one_and_two_posts_and_literal_markup(self):
        for count in (0, 1, 2):
            with self.subTest(photo_posts=count):
                content = self.work / f"small-content-{count}"
                write_page(content, "_index.md", title="Home", tagline="Home")
                write_page(content, "blog/_index.md", title="Статьи")
                for index in range(count):
                    page = write_page(content, f"blog/photo-{index}/index.md", title=f"Photo {index}", date="2026-10-29",
                                      photos=[dict(src="photo.png", alt="Literal </script><script>window.bad=1</script>", kind="photo")])
                    (page.parent / "photo.png").write_bytes(PNG)
                # Explicitly generated images and non-local/missing images are not documentary photographs.
                page = write_page(content, "blog/ignored/index.md", title="Ignored", date="2026-10-28", photos=[
                    dict(src="ai.png", alt="Generated photo", kind="photo", ai_generated=True),
                    dict(src="https://example.test/external.png", alt="External image", kind="photo"),
                    dict(src="missing.png", alt="Missing image", kind="photo"),
                ])
                (page.parent / "ai.png").write_bytes(PNG)
                output = self.work / f"small-output-{count}"
                run = subprocess.run(["hugo", "--contentDir", str(content), "--destination", str(output), "--baseURL", "https://example.test/"],
                                     cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
                self.assertEqual(run.returncode, 0, run.stderr[-1500:])
                doc = Document(output / "blog/index.html")
                grid = doc.by_id("journal-photo-grid")
                scripts = doc.root.find(lambda n: "data-journal-photo-data" in n.attrs)
                self.assertEqual(grid is not None, count > 0)
                self.assertEqual(len(scripts), int(count > 0))
                if count:
                    self.assertEqual(len(grid.find(lambda n: n.tag == "a")), count)
                    pool = json.loads(scripts[0].text())
                    self.assertEqual(len(pool), count)
                    self.assertEqual(pool[0]["alt"], "Literal </script><script>window.bad=1</script>")
                    self.assertFalse(doc.root.find(lambda n: n.tag == "script" and n.text() == "window.bad=1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
