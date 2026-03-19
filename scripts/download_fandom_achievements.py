import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

WIKI = "https://tibia.fandom.com"
API_URL = f"{WIKI}/api.php"

OUT_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "TibiaSprites" / "fandom_achievements"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TibiaSpritesBot/1.0",
    "Accept": "application/json,text/html,*/*",
}

def api_parse_html(session: requests.Session, page_title: str) -> str:
    params = {
        "action": "parse",
        "page": page_title,
        "prop": "text",
        "format": "json",
        "redirects": 1,
    }
    r = session.get(API_URL, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    html = ((data.get("parse", {}) or {}).get("text", {}) or {}).get("*")
    if not html:
        raise RuntimeError(f"No HTML returned for page '{page_title}'")
    return html

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def parse_int(s: str):
    m = re.search(r"-?\d+", s or "")
    return int(m.group(0)) if m else None

def cell_text(cell) -> str:
    # Remove footnotes/superscripts if present, keep readable text
    for sup in cell.find_all("sup"):
        sup.decompose()
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True))

def find_achievements_table(soup: BeautifulSoup):
    """
    Find the big table that has headers like:
    Name | ID | Secret? | Grade | Points | Implemented | Description | Spoiler
    """
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if not header_row:
            continue
        ths = header_row.find_all("th")
        if len(ths) < 5:
            continue
        headers = [norm(th.get_text(" ", strip=True)) for th in ths]
        # Must contain at least these core columns
        if "name" in headers and "grade" in headers and "points" in headers and "description" in headers:
            return table, headers
    return None, None

def main():
    s = requests.Session()
    html = api_parse_html(s, "Achievements")
    soup = BeautifulSoup(html, "html.parser")

    table, headers = find_achievements_table(soup)
    if not table:
        raise RuntimeError("Could not find the Achievements list table. The page structure may have changed.")

    # Map header -> column index
    idx = {h: i for i, h in enumerate(headers)}
    name_i = idx.get("name")
    grade_i = idx.get("grade")
    points_i = idx.get("points")
    desc_i = idx.get("description")

    # Optional useful columns (not required by you, but we’ll capture if present)
    id_i = idx.get("id")
    secret_i = idx.get("secret?")
    impl_i = idx.get("implemented")

    out = []
    rows = table.find_all("tr")

    for tr in rows[1:]:
        tds = tr.find_all(["td", "th"])
        if not tds or len(tds) <= max(name_i, grade_i, points_i, desc_i):
            continue

        # Name: prefer the first link text inside the cell (usually the achievement page)
        name_cell = tds[name_i]
        a = name_cell.find("a")
        name = (a.get_text(strip=True) if a else cell_text(name_cell)).strip()
        if not name:
            continue

        grade = parse_int(cell_text(tds[grade_i])) if grade_i is not None else None
        points = parse_int(cell_text(tds[points_i])) if points_i is not None else None
        description = cell_text(tds[desc_i]) if desc_i is not None else ""

        item = {
            "name": name,
            "grade": grade,
            "points": points,
            "description": description,
        }

        # Optional extras
        if id_i is not None and id_i < len(tds):
            item["id"] = parse_int(cell_text(tds[id_i]))
        if secret_i is not None and secret_i < len(tds):
            sec = cell_text(tds[secret_i])
            # often shows ✓ or ✗
            item["secret"] = True if "✓" in sec or "yes" in sec.lower() else False
        if impl_i is not None and impl_i < len(tds):
            item["implemented"] = cell_text(tds[impl_i])

        out.append(item)

    out_path = OUT_DIR / "achievements.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Found achievements: {len(out)}")
    print(f"Wrote: {out_path}")

if __name__ == "__main__":
    main()