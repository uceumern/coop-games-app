#!/usr/bin/env python3
"""
steam_refresh.py – Updates Steam data and XGP availability in a Coop Games Tracker Gist
-----------------------------------------------------------------------------------------
Fetches the Gist, iterates over all watchlist games with a Steam AppID,
pulls current price / review score / release status from Steam, checks
PC Game Pass availability by name, and writes the updated data back to the Gist.

Requirements: Python 3.10+, requests
  pip install requests

Usage:
  python steam_refresh.py --gist-id <GIST_ID> --pat <GITHUB_PAT>

  Or via environment variables:
  GIST_ID=... GITHUB_PAT=... python steam_refresh.py

  Dry run (fetch + print, no write):
  python steam_refresh.py --dry-run

  Skip XGP check:
  python steam_refresh.py --skip-xgp
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("requests not installed. Run: pip install requests")
    sys.exit(1)


GIST_API      = "https://api.github.com/gists/{gist_id}"
DETAILS_URL   = "https://store.steampowered.com/api/appdetails"
REVIEWS_URL   = "https://store.steampowered.com/appreviews/{appid}"
GIST_FILE     = "coop_games_data.json"
REQUEST_DELAY = 1.2  # seconds between Steam requests

# PC Game Pass catalog (unofficial but stable Microsoft endpoints)
XGP_SIGL_URL    = "https://catalog.gamepass.com/sigls/v2"
XGP_CATALOG_URL = "https://displaycatalog.mp.microsoft.com/v7.0/products"
XGP_SIGL_ID     = "fdd9e2a7-0fee-49f6-ad69-4354098401ff"  # PC Game Pass
XGP_BATCH_SIZE  = 20


# ---------------------------------------------------------------------------
# GitHub Gist
# ---------------------------------------------------------------------------

def gist_get(gist_id: str, pat: str) -> dict:
    resp = requests.get(
        GIST_API.format(gist_id=gist_id),
        headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def gist_patch(gist_id: str, pat: str, content: str):
    payload = {"files": {GIST_FILE: {"content": content}}}
    resp = requests.patch(
        GIST_API.format(gist_id=gist_id),
        headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Steam API
# ---------------------------------------------------------------------------

def steam_details(appid: int) -> dict | None:
    try:
        resp = requests.get(
            DETAILS_URL,
            params={"appids": appid, "cc": "DE", "l": "english"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        entry = data.get(str(appid), {})
        return entry.get("data") if entry.get("success") else None
    except Exception as e:
        print(f"    ⚠ Steam details failed: {e}", file=sys.stderr)
        return None


def steam_reviews(appid: int) -> dict | None:
    try:
        resp = requests.get(
            REVIEWS_URL.format(appid=appid),
            params={"json": 1, "language": "all", "purchase_type": "all", "num_per_page": 0},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("query_summary") if data.get("success") == 1 else None
    except Exception as e:
        print(f"    ⚠ Steam reviews failed: {e}", file=sys.stderr)
        return None


def fetch_steam_data(appid: int) -> dict:
    """Returns dict with steam_status, price, review_pct, review_count."""
    result = {"steam_status": "unknown", "price": None, "review_pct": None, "review_count": None}

    details = steam_details(appid)
    time.sleep(REQUEST_DELAY)

    if not details:
        return result

    genres = details.get("genres", [])
    is_ea = any(g["description"] == "Early Access" for g in genres)
    rd = details.get("release_date", {})
    coming_soon = rd.get("coming_soon", True)

    if coming_soon:
        result["steam_status"] = "unreleased"
    elif is_ea:
        result["steam_status"] = "ea"
    else:
        result["steam_status"] = "released"

    price_info = details.get("price_overview")
    if price_info:
        result["price"] = price_info.get("final_formatted", "")
    elif details.get("is_free"):
        result["price"] = "Free to Play"

    reviews = steam_reviews(appid)
    time.sleep(REQUEST_DELAY)

    if reviews:
        total = reviews.get("total_positive", 0) + reviews.get("total_negative", 0)
        result["review_count"] = total
        if total > 0:
            result["review_pct"] = round(reviews["total_positive"] / total * 100)

    return result


# ---------------------------------------------------------------------------
# PC Game Pass catalog
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation and extra whitespace for name matching."""
    return re.sub(r'[^a-z0-9 ]', '', name.lower()).strip()


def fetch_xgp_catalog() -> set[str]:
    """
    Returns a set of normalized game titles currently in PC Game Pass.
    Uses two Microsoft endpoints:
      1. catalog.gamepass.com/sigls — list of product IDs
      2. displaycatalog.mp.microsoft.com — product titles for those IDs
    """
    # Step 1: fetch product IDs
    resp = requests.get(
        XGP_SIGL_URL,
        params={"id": XGP_SIGL_ID, "language": "en-us", "market": "US"},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json()
    ids = [item["id"] for item in items if isinstance(item, dict) and "id" in item]
    print(f"  {len(ids)} product IDs fetched from Game Pass catalog.")

    # Step 2: batch-fetch product titles
    titles: set[str] = set()
    total_batches = (len(ids) + XGP_BATCH_SIZE - 1) // XGP_BATCH_SIZE
    for i in range(0, len(ids), XGP_BATCH_SIZE):
        batch = ids[i:i + XGP_BATCH_SIZE]
        batch_num = i // XGP_BATCH_SIZE + 1
        try:
            r = requests.get(
                XGP_CATALOG_URL,
                params={
                    "bigIds": ",".join(batch),
                    "market": "US",
                    "languages": "en-us",
                    "MS-CV": "DGU1mcuYo0WMMp.1",
                },
                timeout=15,
            )
            r.raise_for_status()
            for product in r.json().get("Products", []):
                for lp in product.get("LocalizedProperties", []):
                    title = lp.get("ProductTitle", "").strip()
                    if title:
                        titles.add(normalize_name(title))
                        break
        except Exception as e:
            print(f"  ⚠ Batch {batch_num}/{total_batches} failed: {e}", file=sys.stderr)
        time.sleep(0.3)

    return titles


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global REQUEST_DELAY

    parser = argparse.ArgumentParser(description="Update Steam data and XGP availability in Coop Games Gist")
    parser.add_argument("--gist-id",  default=os.environ.get("GIST_ID"),     help="GitHub Gist ID")
    parser.add_argument("--pat",      default=os.environ.get("GITHUB_PAT"),  help="GitHub Personal Access Token (gist scope)")
    parser.add_argument("--dry-run",  action="store_true", help="Fetch and print, do not write back to Gist")
    parser.add_argument("--skip-xgp", action="store_true", help="Skip PC Game Pass availability check")
    parser.add_argument("--delay",    type=float, default=REQUEST_DELAY,     help="Seconds between Steam API requests (default: 1.2)")
    args = parser.parse_args()

    REQUEST_DELAY = args.delay

    if not args.gist_id or not args.pat:
        print("Error: --gist-id and --pat (or GIST_ID / GITHUB_PAT env vars) are required.")
        sys.exit(1)

    # --- Fetch Gist ---
    print(f"Fetching Gist {args.gist_id}...")
    gist = gist_get(args.gist_id, args.pat)
    raw = gist.get("files", {}).get(GIST_FILE, {}).get("content")
    if not raw:
        print(f"Error: '{GIST_FILE}' not found in Gist.")
        sys.exit(1)

    data = json.loads(raw)
    watchlist = data.get("watchlist", [])
    games_with_appid = [g for g in watchlist if g.get("appid")]
    print(f"{len(watchlist)} games in Gist, {len(games_with_appid)} with Steam AppID.\n")

    # --- Fetch PC Game Pass catalog ---
    xgp_titles: set[str] = set()
    if not args.skip_xgp:
        print("Fetching PC Game Pass catalog...")
        try:
            xgp_titles = fetch_xgp_catalog()
            print(f"  {len(xgp_titles)} titles in PC Game Pass.\n")
        except Exception as e:
            print(f"⚠ Could not load XGP catalog: {e} — skipping XGP check.\n", file=sys.stderr)

    # --- Fetch Steam data and check XGP ---
    updated = 0
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for i, game in enumerate(watchlist, 1):
        appid = game.get("appid")
        name  = game.get("name", "?")
        changes = []

        if appid:
            print(f"[{i}/{len(watchlist)}] {name} (AppID {appid})...", end=" ", flush=True)

            steam = fetch_steam_data(int(appid))

            for key in ("steam_status", "price", "review_pct", "review_count"):
                if steam[key] is not None and game.get(key) != steam[key]:
                    game[key] = steam[key]
                    changes.append(key)

            game["steam_updated"] = timestamp
            updated += 1

            status_str = steam["steam_status"]
            review_str = f"{steam['review_pct']}%" if steam["review_pct"] else "—"
            price_str  = steam["price"] or "—"
            suffix     = f"{status_str} | {price_str} | {review_str}"
        else:
            print(f"[{i}/{len(watchlist)}] {name} (no AppID)...", end=" ", flush=True)
            suffix = "no Steam data"

        # XGP check — works for all games regardless of AppID
        if xgp_titles:
            is_xgp = normalize_name(name) in xgp_titles
            if game.get("xgp") != is_xgp:
                game["xgp"] = is_xgp
                changes.append("xgp+" if is_xgp else "xgp-")

        xgp_str = " [XGP]" if game.get("xgp") else ""
        print(f"{suffix}{xgp_str}" + (f" ({', '.join(changes)} changed)" if changes else ""))

    print(f"\n{updated} games processed.")

    if args.dry_run:
        print("Dry-run: Gist not updated.")
        return

    # --- Update metadata ---
    data["lastModified"]   = timestamp
    data["lastModifiedBy"] = "steam_refresh"

    # --- Write Gist ---
    print("Writing Gist...")
    gist_patch(args.gist_id, args.pat, json.dumps(data, ensure_ascii=False, indent=2))
    print(f"✅ Gist updated ({timestamp})")


if __name__ == "__main__":
    main()
