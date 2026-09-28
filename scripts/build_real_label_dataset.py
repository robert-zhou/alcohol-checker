import json
import re
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "real_labels"
DATA_DIR.mkdir(parents=True, exist_ok=True)
MANIFEST_PATH = DATA_DIR / "manifest.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}

SEARCH_QUERIES = [
    "vodka label",
    "whiskey label",
    "whisky label",
    "gin label",
    "rum label",
    "tequila label",
    "brandy label",
    "bourbon label",
    "liqueur label",
    "spirits label",
]


def safe_name(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text.strip())
    return cleaned.strip("_")[:80] or "label"


def query_commons_images(search_term: str, limit: int = 20) -> list[dict]:
    url = (
        "https://commons.wikimedia.org/w/api.php"
        "?action=query"
        "&generator=search"
        f"&gsrsearch={search_term.replace(' ', '%20')}"
        "&gsrnamespace=6"
        f"&gsrlimit={limit}"
        "&format=json"
        "&prop=imageinfo"
        "&iiprop=url|size|mime|mediatype"
        "&iiurlwidth=800"
    )
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    items = []
    for page in data.get("query", {}).get("pages", {}).values():
        title = page.get("title", "")
        info = (page.get("imageinfo") or [{}])[0]
        image_url = info.get("thumburl") or info.get("url")
        if image_url:
            items.append({"title": title, "image_url": image_url, "query": search_term})
    return items


def download_image(url: str, destination: Path) -> bool:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        destination.write_bytes(resp.content)
        return True
    except Exception:
        return False


def main() -> None:
    seen: set[str] = set()
    records: list[dict] = []

    for query in SEARCH_QUERIES:
        for item in query_commons_images(query, limit=12):
            image_url = item["image_url"]
            if image_url in seen:
                continue
            seen.add(image_url)

            filename = safe_name(item["title"]) + ".jpg"
            path = DATA_DIR / filename
            download_image(image_url, path)

            records.append({
                "title": item["title"],
                "query": item["query"],
                "image_url": image_url,
                "image_path": str(path.relative_to(ROOT)),
            })

            if len(records) >= 50:
                break
        if len(records) >= 50:
            break

    MANIFEST_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Saved {len(records)} labels to {DATA_DIR}")
    for record in records[:10]:
        print(ascii(record["title"]), "->", record["image_path"])


if __name__ == "__main__":
    main()
