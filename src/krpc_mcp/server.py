from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP


ROOT_URL = "https://krpc.github.io/krpc/python.html"
ALLOWED_PREFIX = "https://krpc.github.io/krpc/python"
REQUEST_TIMEOUT = 15
MAX_PAGES = 300
MAX_PAGE_CHARS = 20000

CACHE_DIR = Path.home() / ".cache" / "krpc-mcp"
PAGES_FILE = CACHE_DIR / "pages.json"
MEMBERS_FILE = CACHE_DIR / "members.json"
META_FILE = CACHE_DIR / "meta.json"

mcp = FastMCP("krpc-python-docs")


@dataclass
class DocPage:
    url: str
    slug: str
    title: str
    text: str


class DocIndex:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.pages: Dict[str, DocPage] = {}
        self.members: Dict[str, Dict[str, str]] = {}
        self.indexed_at: datetime | None = None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        with self._lock:
            if PAGES_FILE.exists():
                raw_pages = json.loads(PAGES_FILE.read_text(encoding="utf-8"))
                self.pages = {
                    p["slug"]: DocPage(
                        url=p["url"], slug=p["slug"], title=p["title"], text=p["text"]
                    )
                    for p in raw_pages
                }
            if MEMBERS_FILE.exists():
                self.members = json.loads(MEMBERS_FILE.read_text(encoding="utf-8"))
            if META_FILE.exists():
                raw_meta = json.loads(META_FILE.read_text(encoding="utf-8"))
                ts = raw_meta.get("indexed_at")
                if ts:
                    self.indexed_at = datetime.fromisoformat(ts)

    def _save_to_disk(self) -> None:
        with self._lock:
            PAGES_FILE.write_text(
                json.dumps(
                    [
                        {
                            "url": p.url,
                            "slug": p.slug,
                            "title": p.title,
                            "text": p.text,
                        }
                        for p in self.pages.values()
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            MEMBERS_FILE.write_text(
                json.dumps(self.members, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            META_FILE.write_text(
                json.dumps(
                    {
                        "indexed_at": (self.indexed_at or datetime.now(timezone.utc)).isoformat(),
                        "root_url": ROOT_URL,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    def is_stale(self) -> bool:
        with self._lock:
            if self.indexed_at is None:
                return True
            return datetime.now(timezone.utc) - self.indexed_at > timedelta(hours=24)

    def ensure_fresh(self) -> Dict[str, str]:
        if self.pages and not self.is_stale():
            return {
                "status": "ok",
                "message": "Index is fresh.",
                "indexed_at": self.indexed_at.isoformat() if self.indexed_at else "unknown",
            }
        return self.reindex(force=True)

    def reindex(self, force: bool = False) -> Dict[str, str]:
        with self._lock:
            if self.pages and not force and not self.is_stale():
                return {
                    "status": "ok",
                    "message": "Index already fresh.",
                    "indexed_at": self.indexed_at.isoformat() if self.indexed_at else "unknown",
                }

            pages, members = crawl_docs()
            self.pages = {p.slug: p for p in pages}
            self.members = members
            self.indexed_at = datetime.now(timezone.utc)
            self._save_to_disk()
            return {
                "status": "ok",
                "message": f"Indexed {len(self.pages)} pages and {len(self.members)} API members.",
                "indexed_at": self.indexed_at.isoformat(),
            }

    def search(self, query: str, limit: int = 5) -> Dict[str, object]:
        self.ensure_fresh()
        q = query.strip().lower()
        if not q:
            return {"query": query, "results": []}

        scored: List[Tuple[int, DocPage]] = []
        for page in self.pages.values():
            score = 0
            title_l = page.title.lower()
            text_l = page.text.lower()
            slug_l = page.slug.lower()

            if q in title_l:
                score += 5
            if q in slug_l:
                score += 4
            if q in text_l:
                score += 1

            if score > 0:
                scored.append((score, page))

        scored.sort(key=lambda item: (-item[0], item[1].slug))

        out = []
        for score, page in scored[: max(1, min(limit, 20))]:
            idx = page.text.lower().find(q)
            if idx < 0:
                snippet = page.text[:240]
            else:
                start = max(0, idx - 80)
                end = min(len(page.text), idx + 160)
                snippet = page.text[start:end]

            out.append(
                {
                    "score": score,
                    "title": page.title,
                    "slug": page.slug,
                    "url": page.url,
                    "snippet": " ".join(snippet.split()),
                }
            )

        return {"query": query, "results": out}

    def get_page(self, slug_or_url: str) -> Dict[str, object]:
        self.ensure_fresh()
        key = normalize_slug_or_url(slug_or_url)
        page = self.pages.get(key)
        if page is None:
            return {
                "error": "not_found",
                "message": f"No page found for '{slug_or_url}'.",
            }
        return {
            "title": page.title,
            "slug": page.slug,
            "url": page.url,
            "content": page.text,
            "indexed_at": self.indexed_at.isoformat() if self.indexed_at else None,
        }

    def get_member(self, service: str, class_name: str, member: str) -> Dict[str, object]:
        self.ensure_fresh()

        target = f"{service}.{class_name}.{member}".lower()
        candidates = []
        for mid, entry in self.members.items():
            key = mid.lower()
            score = 0
            if target == key:
                score = 100
            elif target in key:
                score = 80
            elif member.lower() in key and class_name.lower() in key:
                score = 50
            elif member.lower() in key:
                score = 20
            if score:
                candidates.append((score, mid, entry))

        candidates.sort(key=lambda x: -x[0])
        if not candidates:
            return {
                "error": "not_found",
                "message": f"No API member matched {service}.{class_name}.{member}",
            }

        best = candidates[0]
        return {
            "query": {
                "service": service,
                "class_name": class_name,
                "member": member,
            },
            "best_match": {
                "id": best[1],
                "title": best[2].get("title", ""),
                "url": best[2].get("url", ""),
                "signature": best[2].get("signature", ""),
                "description": best[2].get("description", ""),
            },
            "alternatives": [
                {
                    "id": mid,
                    "title": entry.get("title", ""),
                    "url": entry.get("url", ""),
                }
                for _, mid, entry in candidates[1:6]
            ],
        }


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    clean = parsed._replace(query="", fragment="")
    return clean.geturl()


def normalize_slug_or_url(value: str) -> str:
    v = value.strip()
    if v.startswith("http://") or v.startswith("https://"):
        url = normalize_url(v)
        path = urlparse(url).path
        return path.split("/krpc/")[-1]
    v = v.lstrip("/")
    return v


def allowed(url: str) -> bool:
    n = normalize_url(url)
    if not n.startswith(ALLOWED_PREFIX):
        return False
    return n.endswith(".html")


def page_to_slug(url: str) -> str:
    path = urlparse(url).path
    return path.split("/krpc/")[-1]


def extract_text(soup: BeautifulSoup) -> str:
    main = soup.find("div", class_="document") or soup
    text = main.get_text("\n", strip=True)
    text = "\n".join(line for line in (x.strip() for x in text.splitlines()) if line)
    return text[:MAX_PAGE_CHARS]


def crawl_docs() -> Tuple[List[DocPage], Dict[str, Dict[str, str]]]:
    session = requests.Session()
    to_visit = [ROOT_URL]
    seen = set()
    pages: List[DocPage] = []
    members: Dict[str, Dict[str, str]] = {}

    while to_visit and len(seen) < MAX_PAGES:
        url = normalize_url(to_visit.pop(0))
        if url in seen:
            continue
        seen.add(url)

        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        title = (soup.title.text.strip() if soup.title and soup.title.text else page_to_slug(url))
        text = extract_text(soup)
        slug = page_to_slug(url)
        pages.append(DocPage(url=url, slug=slug, title=title, text=text))

        for dt in soup.select("dt[id]"):
            mid = dt.get("id", "").strip()
            if not mid:
                continue
            dd = dt.find_next_sibling("dd")
            signature = " ".join(dt.get_text(" ", strip=True).split())
            description = ""
            if dd:
                description = " ".join(dd.get_text(" ", strip=True).split())[:1200]
            members[mid] = {
                "id": mid,
                "title": title,
                "url": f"{url}#{mid}",
                "signature": signature,
                "description": description,
            }

        for a in soup.select("a[href]"):
            raw = a.get("href", "")
            if not raw:
                continue
            linked = normalize_url(urljoin(url, raw))
            if allowed(linked) and linked not in seen and linked not in to_visit:
                to_visit.append(linked)

    return pages, members


index = DocIndex()


@mcp.tool()
def search_docs(query: str, limit: int = 5) -> Dict[str, object]:
    """Search indexed kRPC Python docs pages by free-text query."""
    return index.search(query=query, limit=limit)


@mcp.tool()
def get_doc_page(slug_or_url: str) -> Dict[str, object]:
    """Get a full indexed docs page by slug (e.g. python/api/space-center/vessel.html) or URL."""
    return index.get_page(slug_or_url=slug_or_url)


@mcp.tool()
def get_api_member(service: str, class_name: str, member: str) -> Dict[str, object]:
    """Get a specific API member from the indexed kRPC Python docs."""
    return index.get_member(service=service, class_name=class_name, member=member)


@mcp.tool()
def reindex_docs(force: bool = False) -> Dict[str, str]:
    """Refresh docs index now. Use force=True to refresh immediately."""
    return index.reindex(force=force)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
