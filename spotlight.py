"""
Letterboxd Spotlight
Every 14 days: takes the top trending Letterboxd lists, copies their films into
your fixed MDBList lists, and draws a new "Marquee" cover for each slot.

Run modes:
  python spotlight.py rotate          normal run (skips if it's been less than ROTATE_EVERY_DAYS)
  python spotlight.py force           rotate right now, ignoring the timer
  python spotlight.py show-my-lists   print your MDBList lists and their ID numbers
"""
import datetime as dt
import io
import json
import os
import re
import sys
import time

import requests
from curl_cffi import requests as browser_requests
from PIL import Image, ImageDraw, ImageFont

# ---------- settings (set these in GitHub > Settings > Secrets and variables > Actions) ----------
MDBLIST_KEY = os.environ.get("MDBLIST_API_KEY", "").strip()
TMDB_KEY = os.environ.get("TMDB_API_KEY", "").strip()
LIST_IDS = [x.strip() for x in os.environ.get("MDBLIST_LIST_IDS", "").split(",") if x.strip()]
ROTATE_EVERY_DAYS = int(os.environ.get("ROTATE_EVERY_DAYS", "14") or 14)
EXCLUDE_WORDS = [w.strip().lower() for w in os.environ.get("EXCLUDE_WORDS", "").split(",") if w.strip()]
MIN_FILMS, MAX_FILMS, FILMS_PER_SLOT = 10, 500, 100   # skip tiny or giant lists; keep the first 100 films

ROOT = os.path.dirname(os.path.abspath(__file__))
COVERS = os.path.join(ROOT, "covers")
STATE_FILE = os.path.join(ROOT, "state.json")
FONTS = os.path.join(ROOT, "fonts")
MDB_API = "https://api.mdblist.com"
STREMTHRU = "https://stremthru.13377001.xyz/v0/meta/letterboxd/lists/"
POPULAR_URL = "https://letterboxd.com/lists/popular/this/week/"

lb = browser_requests.Session(impersonate="chrome")


def fail(msg):
    print(f"\n*** STOPPED: {msg}\n")
    sys.exit(1)


# ---------------- Letterboxd ----------------
def popular_list_urls():
    r = lb.get(POPULAR_URL, timeout=60)
    if r.status_code != 200:
        fail(f"Letterboxd blocked or failed the trending-lists page (HTTP {r.status_code}). "
             "Nothing was changed; your rows keep their current lists.")
    seen, urls = set(), []
    for owner, slug in re.findall(r'href="/([A-Za-z0-9_]+)/list/([a-z0-9-]+)/"', r.text):
        url = f"https://letterboxd.com/{owner}/list/{slug}/"
        if url not in seen:
            seen.add(url)
            urls.append((owner, url))
    if not urls:
        fail("Couldn't find any lists on Letterboxd's trending page (the page layout may have changed).")
    return urls


def list_identifier(url):
    r = lb.get(url, timeout=60)
    return r.headers.get("x-letterboxd-identifier")


def list_contents(identifier):
    for attempt in range(3):
        try:
            r = requests.get(STREMTHRU + identifier, timeout=90)
            data = (r.json() or {}).get("data") or {}
            if data.get("items"):
                return data
        except Exception as e:
            print(f"   list lookup error: {e}")
        time.sleep(20)
    return None


def pick_trending(n):
    picks = []
    for owner, url in popular_list_urls():
        if len(picks) == n:
            break
        ident = list_identifier(url)
        if not ident:
            print(f" - skipped (no ID): {url}")
            continue
        data = list_contents(ident)
        if not data:
            print(f" - skipped (couldn't read films): {url}")
            continue
        title = (data.get("title") or "").strip()
        items = [i for i in data["items"] if (i.get("id_map") or {}).get("imdb") or (i.get("id_map") or {}).get("tmdb")]
        if any(w in title.lower() for w in EXCLUDE_WORDS):
            print(f" - skipped (excluded word): {title}")
            continue
        if not (MIN_FILMS <= len(items) <= MAX_FILMS):
            print(f" - skipped ({len(items)} films): {title}")
            continue
        print(f" + picked: {title} ({len(items)} films) by {owner}")
        picks.append({"title": title, "owner": owner, "url": url, "count": len(items),
                      "items": items[:FILMS_PER_SLOT]})
        time.sleep(2)
    if len(picks) < n:
        fail(f"Only found {len(picks)} usable trending lists, needed {n}. Nothing was changed.")
    return picks


# ---------------- MDBList ----------------
def mdb(method, path, **kw):
    kw.setdefault("params", {})["apikey"] = MDBLIST_KEY
    r = requests.request(method, MDB_API + path, timeout=60, **kw)
    if r.status_code >= 400:
        fail(f"MDBList error {r.status_code} on {path}: {r.text[:200]}")
    return r.json() if r.text else {}


def to_ref(imdb, tmdb):
    return {"imdb": imdb} if imdb else {"tmdb": int(tmdb)}


def chunks(seq, size=100):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def replace_list(list_id, items):
    current = mdb("GET", f"/lists/{list_id}/items", params={"limit": 2000})
    old = {"movies": [], "shows": []}
    for kind in ("movies", "shows"):
        for it in current.get(kind, []) or []:
            if it.get("imdb_id") or it.get("id"):
                old[kind].append(to_ref(it.get("imdb_id"), it.get("id")))
    for kind in ("movies", "shows"):
        for part in chunks(old[kind]):
            mdb("POST", f"/lists/{list_id}/items/remove", json={kind: part})
    new = {"movies": [], "shows": []}
    for it in items:
        ids = it.get("id_map") or {}
        kind = "shows" if it.get("type") == "show" else "movies"
        new[kind].append(to_ref(ids.get("imdb"), ids.get("tmdb")))
    for kind in ("movies", "shows"):
        for part in chunks(new[kind]):
            mdb("POST", f"/lists/{list_id}/items/add", json={kind: part})


# ---------------- TMDB backdrop ----------------
def tmdb_get(path):
    headers, params = {}, {}
    if len(TMDB_KEY) > 40:
        headers["Authorization"] = f"Bearer {TMDB_KEY}"
    else:
        params["api_key"] = TMDB_KEY
    r = requests.get("https://api.themoviedb.org/3" + path, headers=headers, params=params, timeout=30)
    return r.json() if r.status_code == 200 else {}


def find_backdrop(items):
    for it in items[:10]:
        tmdb_id = (it.get("id_map") or {}).get("tmdb")
        if not tmdb_id:
            continue
        kind = "tv" if it.get("type") == "show" else "movie"
        path = tmdb_get(f"/{kind}/{tmdb_id}").get("backdrop_path")
        if path:
            r = requests.get(f"https://image.tmdb.org/t/p/w1280{path}", timeout=60)
            if r.status_code == 200:
                return Image.open(io.BytesIO(r.content)).convert("RGB")
    return None


# ---------------- Marquee cover ----------------
W, H = 1280, 720
ACCENT = (255, 138, 40)


def font(name, size, weight=None):
    f = ImageFont.truetype(os.path.join(FONTS, name), size)
    if weight:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def fill_frame(img):
    scale = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((left, top, left + W, top + H))


def left_fade():
    mask = Image.new("L", (W, H))
    row = [int(250 * min(1, (1 - x / W) * 1.35) ** 1.4) for x in range(W)]
    mask.putdata(row * H)
    return mask


def wrap(draw, text, f, max_w):
    lines = [""]
    for word in text.split():
        trial = (lines[-1] + " " + word).strip()
        if draw.textlength(trial, font=f) <= max_w or not lines[-1]:
            lines[-1] = trial
        else:
            lines.append(word)
    return lines


def draw_cover(slot, pick, backdrop, path):
    base = fill_frame(backdrop) if backdrop else Image.new("RGB", (W, H), (30, 24, 20))
    img = Image.composite(Image.new("RGB", (W, H), (8, 8, 10)), base, left_fade())
    d = ImageDraw.Draw(img)

    size = 118
    while True:
        tf = font("BebasNeue-Regular.ttf", size)
        lines = wrap(d, pick["title"].upper(), tf, 720)
        if len(lines) <= 3 or size <= 64:
            break
        size -= 8
    if len(lines) > 3:
        lines = lines[:3]
        lines[2] = lines[2].rstrip(".,:;- ") + "…"
    line_h = int(size * 0.92)
    label_h, gap, meta_h = 40, 26, 34
    block = label_h + len(lines) * line_h + gap + meta_h
    y = (H - block) // 2

    d.rectangle([80, y, 86, y + label_h + len(lines) * line_h + 4], fill=ACCENT)
    d.text((112, y), f"TRENDING ON LETTERBOXD  ·  #{slot}", font=font("Montserrat.ttf", 24, 700), fill=ACCENT)
    ty = y + label_h
    for line in lines:
        d.text((110, ty), line, font=tf, fill=(245, 242, 236))
        ty += line_h
    meta = f"by {pick['owner']}  ·  {pick['count']} films"
    d.text((112, ty + gap), meta, font=font("Montserrat.ttf", 26, 500), fill=(190, 190, 195))
    img.save(path, optimize=True)


# ---------------- main ----------------
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "rotate"
    if not MDBLIST_KEY:
        fail("MDBLIST_API_KEY secret is missing.")

    if mode == "show-my-lists":
        for l in mdb("GET", "/lists/user"):
            print(f"ID {l.get('id')}: {l.get('name')}  ({l.get('items')} items, {l.get('type', '')})")
        return

    if not LIST_IDS:
        fail("MDBLIST_LIST_IDS variable is missing (your list ID numbers, separated by commas).")
    if not TMDB_KEY:
        fail("TMDB_API_KEY secret is missing.")

    state = load_state()
    last = state.get("last_rotation")
    if mode == "rotate" and last:
        days = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last)).days
        if days < ROTATE_EVERY_DAYS - 1:
            print(f"Last rotation was {days} days ago; next one after {ROTATE_EVERY_DAYS} days. Skipping.")
            return

    print("Finding trending Letterboxd lists...")
    picks = pick_trending(len(LIST_IDS))

    os.makedirs(COVERS, exist_ok=True)
    slots = []
    for n, (list_id, pick) in enumerate(zip(LIST_IDS, picks), start=1):
        print(f"Slot {n}: {pick['title']}")
        replace_list(list_id, pick["items"])
        draw_cover(n, pick, find_backdrop(pick["items"]), os.path.join(COVERS, f"trending-{n}.png"))
        slots.append({k: pick[k] for k in ("title", "owner", "url", "count")} | {"mdblist_id": list_id})

    state = {"last_rotation": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "slots": slots}
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print("Done.")


if __name__ == "__main__":
    main()
