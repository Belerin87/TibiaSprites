import csv, json, os, re, time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

WIKI = "https://tibia.fandom.com"
API  = f"{WIKI}/api.php"

OUT_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "TibiaSprites" / "fandom_mounts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TibiaSpritesBot/2.0",
    "Accept": "application/json,text/html,*/*",
}

SLEEP = 0.05

def safe_filename(name: str) -> str:
    s = re.sub(r"[^\w\s\-\(\)\[\]\.]", "", name, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:160] if s else "unknown"

def api_get_category_members(session: requests.Session, category: str):
    # category should be like "Category:Mounts"
    members = []
    cont = None
    while True:
        params = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": category,
            "cmlimit": "500",
            "cmtype": "page",
        }
        if cont:
            params["cmcontinue"] = cont
        r = session.get(API, params=params, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()
        members.extend(data.get("query", {}).get("categorymembers", []) or [])
        cont = (data.get("continue", {}) or {}).get("cmcontinue")
        if not cont:
            break
        time.sleep(SLEEP)
    return members

def api_parse_html(session: requests.Session, title: str) -> str:
    params = {"action": "parse", "format": "json", "page": title, "prop": "text", "redirects": 1}
    r = session.get(API, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    html = ((r.json().get("parse", {}) or {}).get("text", {}) or {}).get("*")
    if not html:
        raise RuntimeError(f"parse returned no html for {title}")
    return html

def choose_best_image_from_page(html: str) -> str | None:
    """
    Fandom pages often have a portable infobox image:
      <figure class="pi-item pi-image"> <img ... data-src="...">
    We'll try that first, else fall back to the first content image.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1) portable infobox image
    fig = soup.select_one("figure.pi-item.pi-image img")
    if fig:
        for attr in ("data-src", "src"):
            u = fig.get(attr)
            if u:
                return u

    # 2) any image in the article body
    img = soup.select_one("img")
    if img:
        for attr in ("data-src", "src"):
            u = img.get(attr)
            if u:
                return u
    return None

def normalize_image_url(u: str) -> str:
    """
    Fandom image URLs can include /scale-to-width-down/ etc.
    We’ll just use whatever is provided (usually fine).
    """
    return u

def download(session: requests.Session, url: str, out_path: Path):
    with session.get(url, headers=HEADERS, stream=True, timeout=120) as r:
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()
        if "image/" not in ct:
            raise RuntimeError(f"Not an image: {ct} from {url}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1024 * 128):
                if chunk:
                    f.write(chunk)

def main():
    s = requests.Session()

    members = api_get_category_members(s, "Category:Mounts")
    # Titles are pages like "War Bear", "Racing Bird", etc.
    titles = [m["title"] for m in members if isinstance(m, dict) and m.get("title")]
    titles.sort(key=lambda x: x.lower())

    print(f"Found mounts in category: {len(titles)}")

    out_items = []
    for title in titles:
        time.sleep(SLEEP)
        try:
            html = api_parse_html(s, title)
            img_url = choose_best_image_from_page(html)
            if not img_url:
                continue
            img_url = normalize_image_url(img_url)

            ext = Path(urlparse(img_url).path).suffix or ".png"
            filename = safe_filename(title) + ext
            out_path = OUT_DIR / filename

            download(s, img_url, out_path)
            out_items.append({"name": title, "file": filename, "sourceUrl": img_url})
            print("✓", title, "->", filename)
        except Exception as e:
            print("x", title, ":", e)

    with open(OUT_DIR / "index.json", "w", encoding="utf-8") as f:
        json.dump(out_items, f, ensure_ascii=False, indent=2)

    with open(OUT_DIR / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "file", "sourceUrl"])
        w.writeheader()
        w.writerows(out_items)

    print("Done:", OUT_DIR)

if __name__ == "__main__":
    main()