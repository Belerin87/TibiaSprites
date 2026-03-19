import csv, json, os, re, time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

WIKI = "https://tibia.fandom.com"
API  = f"{WIKI}/api.php"

OUT_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "TibiaSprites" / "fandom_outfits_female_addons"
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

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def api_parse_html(session: requests.Session, title: str) -> str:
    params = {"action": "parse", "format": "json", "page": title, "prop": "text", "redirects": 1}
    r = session.get(API, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    html = ((r.json().get("parse", {}) or {}).get("text", {}) or {}).get("*")
    if not html:
        raise RuntimeError(f"parse returned no html for {title}")
    return html

def pick_image_url_from_cell(td) -> str | None:
    img = td.find("img")
    if not img:
        return None
    return img.get("data-src") or img.get("src")

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

def find_outfits_table_and_column_index(soup: BeautifulSoup, column_label: str):
    """
    Find the table that contains a header with column_label (case/spacing tolerant).
    Determine the column index by scanning the first row that contains THs.
    """
    target = norm(column_label)
    for table in soup.find_all("table"):
        header_rows = table.find_all("tr")
        for tr in header_rows:
            ths = tr.find_all("th")
            if not ths:
                continue
            headers = [norm(th.get_text(" ", strip=True)) for th in ths]
            if any(target in h for h in headers):
                cells = tr.find_all(["th", "td"])
                idx = None
                for i, cell in enumerate(cells):
                    h = norm(cell.get_text(" ", strip=True))
                    if target in h:
                        idx = i
                        break
                return table, idx
    return None, None

def main():
    s = requests.Session()
    html = api_parse_html(s, "Outfits")
    soup = BeautifulSoup(html, "html.parser")

    table, female_idx = find_outfits_table_and_column_index(soup, "Female addons")
    if not table or female_idx is None:
        raise RuntimeError("Could not find Outfits table with a 'Female Addons' column.")

    results = []
    seen = set()

    rows = table.find_all("tr")
    passed_header = False

    for tr in rows:
        if not passed_header:
            ths = tr.find_all("th")
            if ths:
                headers = [norm(th.get_text(' ', strip=True)) for th in ths]
                if any("female addons" in h for h in headers):
                    passed_header = True
            continue

        cells = tr.find_all(["td", "th"])
        if len(cells) <= female_idx:
            continue

        # Name is usually first cell
        name_cell = cells[0]
        a = name_cell.find("a")
        name = (a.get_text(strip=True) if a else name_cell.get_text(" ", strip=True)).strip()
        if not name:
            continue

        key = name.lower()
        if key in seen:
            continue

        female_cell = cells[female_idx]
        img_url = pick_image_url_from_cell(female_cell)
        if not img_url:
            continue

        seen.add(key)
        results.append({"name": name, "img_url": img_url})

    print(f"Found outfits with female addons image: {len(results)}")

    out_items = []
    for item in results:
        time.sleep(SLEEP)
        name = item["name"]
        img_url = item["img_url"]

        try:
            ext = Path(urlparse(img_url).path).suffix or ".png"
            filename = safe_filename(name) + ext
            out_path = OUT_DIR / filename

            download(s, img_url, out_path)
            out_items.append({"name": name, "file": filename, "sourceUrl": img_url})
            print("✓", name, "->", filename)
        except Exception as e:
            print("x", name, ":", e)

    with open(OUT_DIR / "index.json", "w", encoding="utf-8") as f:
        json.dump(out_items, f, ensure_ascii=False, indent=2)

    with open(OUT_DIR / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "file", "sourceUrl"])
        w.writeheader()
        w.writerows(out_items)

    print("Done:", OUT_DIR)

if __name__ == "__main__":
    main()