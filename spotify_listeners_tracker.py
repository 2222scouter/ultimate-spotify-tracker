from datetime import datetime, timezone
import re
import pandas as pd
from playwright.sync_api import sync_playwright
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
ARTISTS = []
with open(“artists.txt”, “r”, encoding=“utf-8”) as f:
for line in f:
line = line.strip()
if not line or “open.spotify.com/artist” not in line:
continue
parts = line.split(”,”, 1)
if len(parts) == 2:
name = parts[0].strip()
url = parts[1].strip().split(”?”)[0]  # strip tracking params
ARTISTS.append({“name”: name, “url”: url})
print(f”Loaded {len(ARTISTS)} artists from artists.txt”)
except Exception as e:
print(f”Failed to load artists.txt ({e})”)
ARTISTS = []

def scrape_one(artist: dict, playwright) -> dict | None:
“”“Scrape monthly listeners for a single artist. Returns dict or None on failure.”””
browser = None
try:
browser = playwright.chromium.launch(headless=True)
context = browser.new_context(
user_agent=“Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36”
)
page = context.new_page()

```
    # domcontentloaded is much faster than networkidle
    page.goto(artist["url"], wait_until="domcontentloaded", timeout=30000)

    # Wait for the listener count element specifically, up to 10s
    try:
        page.wait_for_selector('[data-testid="monthly-listeners-label"]', timeout=10000)
        elem = page.query_selector('[data-testid="monthly-listeners-label"]')
        text = elem.inner_text().strip() if elem else ""
    except Exception:
        # Fallback: search by text if testid not present
        elem = page.get_by_text(re.compile(r"[\d,]+ monthly listeners", re.IGNORECASE)).first
        text = elem.inner_text().strip() if elem else ""

    match = re.search(r'([\d,]+)', text)
    if match:
        count = int(match.group(1).replace(',', ''))
        print(f"✅ {artist['name']}: {count:,} monthly listeners")
        return {"artist": artist["name"], "monthly_listeners": count}
    else:
        print(f"⚠️  {artist['name']}: listener count not found (page text snippet: {text[:100]!r})")
        return None
except Exception as e:
    print(f"❌ {artist['name']}: scrape failed — {e}")
    return None
finally:
    if browser:
        browser.close()
```

def scrape_all(artists: list) -> list:
“”“Scrape all artists concurrently using a thread pool.”””
results = []
# Playwright isn’t thread-safe for a single instance, so each thread gets its own
# We cap workers to avoid hammering Spotify / GitHub Actions RAM limits
max_workers = min(5, len(artists))

```
def scrape_worker(artist):
    with sync_playwright() as pw:
        return scrape_one(artist, pw)

with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(scrape_worker, a): a for a in artists}
    for future in as_completed(futures):
        result = future.result()
        if result:
            results.append(result)

return results
```

# — Main —

timestamp = datetime.now(timezone.utc).strftime(”%Y-%m-%d %H:%M UTC”)

print(f”Starting scrape of {len(ARTISTS)} artists at {timestamp} (up to 5 concurrent)…”)
raw_results = scrape_all(ARTISTS)

new_data = [{“timestamp”: timestamp, **r} for r in raw_results]

if new_data:
df_new = pd.DataFrame(new_data)
try:
df_old = pd.read_csv(“spotify_listeners_history.csv”)
df = pd.concat([df_old, df_new], ignore_index=True)
except FileNotFoundError:
df = df_new

```
df = df.drop_duplicates(subset=['timestamp', 'artist'], keep='last')
df.to_csv("spotify_listeners_history.csv", index=False)
print(f"✅ Saved {len(new_data)} listener entries ({len(ARTISTS) - len(new_data)} failed)")
```

else:
print(“❌ No new data found — all artists failed to scrape”)

print(“Scraper finished!”)
