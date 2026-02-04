import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import cloudscraper
from bs4 import BeautifulSoup

WIKI_BASE = "https://www.tibiawiki.com.br"
API_URL = f"{WIKI_BASE}/api.php"
REQUEST_DELAY_SECONDS = 0.08

BOSSES_PAGE = f"{WIKI_BASE}/wiki/Bosses"

CREATURE_PAGES = [
    f"{WIKI_BASE}/wiki/Anf%C3%ADbios",
    f"{WIKI_BASE}/wiki/Aqu%C3%A1ticos",
    f"{WIKI_BASE}/wiki/Aves",
    f"{WIKI_BASE}/wiki/Constructos",
    f"{WIKI_BASE}/wiki/Criaturas_M%C3%A1gicas",
    f"{WIKI_BASE}/wiki/Dem%C3%B4nios",
    f"{WIKI_BASE}/wiki/Drag%C3%B5es",
    f"{WIKI_BASE}/wiki/Elementais",
    f"{WIKI_BASE}/wiki/Extra_Dimensionais",
    f"{WIKI_BASE}/wiki/Fadas",
    f"{WIKI_BASE}/wiki/Gigantes",
    f"{WIKI_BASE}/wiki/Humanos",
    f"{WIKI_BASE}/wiki/Human%C3%B3ides",
    f"{WIKI_BASE}/wiki/Imortais",
    f"{WIKI_BASE}/wiki/Inkborn",
    f"{WIKI_BASE}/wiki/Licantropos",
    f"{WIKI_BASE}/wiki/Mam%C3%ADferos",
    f"{WIKI_BASE}/wiki/Mortos-Vivos",
    f"{WIKI_BASE}/wiki/Plantas_(Criatura)",
    f"{WIKI_BASE}/wiki/R%C3%A9pteis",
    f"{WIKI_BASE}/wiki/Slimes",
    f"{WIKI_BASE}/wiki/Vermes",
]


def desktop_path() -> Path:
    if os.name == "nt" and os.environ.get("USERPROFILE"):
        p = Path(os.environ["USERPROFILE"]) / "Desktop"
        if p.exists():
            return p
    return Path.home() / "Desktop"


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def build_fandom_gif_file(name: str) -> str | None:
    """
    Python port of your Node buildWikiGifFile().
    Produces "The_Voice_of_Ruin.gif" style names.
    """
    if not name:
        return None

    # normalize whitespace
    s = " ".join(str(name).strip().split())

    LOWER = {"a", "an", "the", "of", "in", "on", "to", "and", "with", "from"}

    words = s.split(" ")
    out_words = []
    for i, w in enumerate(words):
        segs = w.split("-")
        segs2 = []
        for seg in segs:
            if not seg:
                segs2.append(seg)
                continue
            segs2.append(seg[:1].upper() + seg[1:].lower())
        out = "-".join(segs2)
        if i > 0 and out.lower() in LOWER:
            out = out.lower()
        out_words.append(out)

    s2 = " ".join(out_words).replace(" ", "_")
    return f"{s2}.gif"


def fetch_html(scraper, url: str) -> str:
    """
    Try direct page; if blocked, fall back to API parse.
    """
    r = scraper.get(url, timeout=60)
    if r.status_code != 403:
        r.raise_for_status()
        return r.text

    # Fallback via parse API using the page title from /wiki/<Title>
    path = urlparse(url).path
    title = unquote(path.split("/wiki/")[-1])

    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json",
        "redirects": "1",
        "origin": "*",
    }
    api_r = scraper.get(API_URL, params=params, timeout=60)
    api_r.raise_for_status()
    data = api_r.json()
    html = (data.get("parse", {}).get("text", {}) or {}).get("*")
    if not html:
        raise RuntimeError(f"Could not parse HTML for page '{title}'.")
    return html


def mw_original_image_url(scraper, filename: str) -> str | None:
    """
    MediaWiki API lookup to get original file URL.
    Tries Portuguese namespace 'Arquivo:' then 'File:' fallback.
    """
    for ns in ("Arquivo:", "File:"):
        params = {
            "action": "query",
            "titles": f"{ns}{filename}",
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
            "origin": "*",
        }
        r = scraper.get(API_URL, params=params, timeout=60)
        if r.status_code == 403:
            return None
        r.raise_for_status()
        data = r.json()

        pages = data.get("query", {}).get("pages", {})
        for _, page in pages.items():
            ii = page.get("imageinfo")
            if ii and isinstance(ii, list) and ii[0].get("url"):
                return ii[0]["url"]

        time.sleep(REQUEST_DELAY_SECONDS)

    return None


def download(scraper, url: str, out_path: Path) -> None:
    with scraper.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 128):
                if chunk:
                    f.write(chunk)


def extract_name_and_wiki_file(html: str) -> list[tuple[str, str]]:
    """
    Extract (entity_name, wiki_filename) by scanning rows with an <img alt="X.gif/png">
    and a sensible first wiki link in the row.
    """
    soup = BeautifulSoup(html, "html.parser")
    pairs: list[tuple[str, str]] = []

    for tr in soup.find_all("tr"):
        img = tr.find("img", alt=True)
        if not img:
            continue

        wiki_file = (img.get("alt") or "").strip()
        if not re.search(r"\.(gif|png)$", wiki_file, re.IGNORECASE):
            continue

        chosen = None
        for a in tr.find_all("a", href=True):
            title = (a.get("title") or "").strip()
            href = a["href"]
            text = a.get_text(strip=True)

            if not text:
                continue
            if title.startswith(("Arquivo:", "Image:", "Especial:", "Special:")):
                continue
            if "/wiki/" not in href:
                continue

            chosen = text
            break

        if not chosen:
            continue

        pairs.append((chosen, wiki_file))

    return pairs


def run_group(scraper, group_name: str, page_urls: list[str], out_base: Path) -> None:
    group_dir = out_base / group_name
    sprites_dir = group_dir
    ensure_dir(sprites_dir)

    # name -> { name, file, sourceWikiFile, sourceUrl }
    # file is the Fandom-style .gif filename you will host in GitHub
    index: dict[str, dict] = {}

    print(f"\n=== {group_name.upper()} ===")
    for url in page_urls:
        print(f"Fetching: {url}")
        html = fetch_html(scraper, url)
        pairs = extract_name_and_wiki_file(html)
        print(f"  Found {len(pairs)} rows")

        for name, wiki_file in pairs:
            if name in index:
                continue

            fandom_file = build_fandom_gif_file(name)
            if not fandom_file:
                continue

            index[name] = {
                "name": name,
                "file": fandom_file,
                "sourceWikiFile": wiki_file,
                "sourceUrl": "",
            }

        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Total unique {group_name}: {len(index)}")

    downloaded = 0
    skipped = 0

    # Download each sprite using TibiaWiki file, but SAVE AS your Fandom-style filename.
    for name, row in sorted(index.items(), key=lambda x: x[0].lower()):
        time.sleep(REQUEST_DELAY_SECONDS)

        src_url = mw_original_image_url(scraper, row["sourceWikiFile"])
        row["sourceUrl"] = src_url or ""

        out_path = sprites_dir / row["file"]
        if out_path.exists() and out_path.stat().st_size > 0:
            continue

        if not src_url:
            skipped += 1
            continue

        try:
            download(scraper, src_url, out_path)
            downloaded += 1
        except Exception:
            skipped += 1

    # Write index.json (array is easier for JS)
    out_index = group_dir / "index.json"
    with open(out_index, "w", encoding="utf-8") as f:
        json.dump(list(index.values()), f, ensure_ascii=False, indent=2)

    print(f"Saved: {group_dir}")
    print(f"Downloaded: {downloaded} | Skipped: {skipped}")
    print(f"Index: {out_index}")


def main():
    out_base = desktop_path() / "TibiaSprites"
    ensure_dir(out_base)

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )
    scraper.get(WIKI_BASE + "/", timeout=60)

    run_group(scraper, "bosses", [BOSSES_PAGE], out_base)
    run_group(scraper, "creatures", CREATURE_PAGES, out_base)

    print("\nAll done.")
    print(f"Output root: {out_base}")


if __name__ == "__main__":
    # pip install cloudscraper beautifulsoup4
    main()