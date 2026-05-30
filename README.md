# Coop Games Tracker

A simple single-page app for tracking a shared co-op games watchlist.

## Features

- Watchlist with Steam status, prices and review scores
- Play history (Coop Weekly)
- Gaming weekend log (Coop Weekends)
- Search, filter, sort
- JSON export / import
- Responsive (desktop + mobile)

## Setup

1. Create a **private GitHub Gist** containing a file named `coop_games_data.json` with the following content:
   ```json
   { "watchlist": [], "weekly": [], "weekends": [] }
   ```

2. Create a **Personal Access Token** (PAT) at [github.com/settings/tokens](https://github.com/settings/tokens) with `gist` scope.

3. Open the app, click ⚙️ and enter your Gist ID and PAT.

## Data & Privacy

All game data is stored in a private GitHub Gist — not in this repository. The app itself contains no personal data. Without a valid PAT and Gist ID the app shows an empty state.

## Steam data refresh

Steam data (prices, reviews, release status) can be refreshed via `steam_refresh.py`:

```bash
pip install requests
python steam_refresh.py --gist-id <GIST_ID> --pat <GITHUB_PAT>
```

Or using environment variables:

```bash
export GIST_ID=your_gist_id
export GITHUB_PAT=ghp_yourtoken
python steam_refresh.py
```

The script fetches the Gist, queries the Steam API for each game with a known AppID, updates `steam_status`, `price`, `review_pct`, `review_count` and `steam_updated`, then writes the result back to the Gist. The app reflects the new data on the next page load.

Options:
- `--dry-run` — fetch and print without writing back to the Gist
- `--skip-xgp` — skip the PC Game Pass availability check
- `--delay` — seconds between Steam API requests (default: 1.2)

The script also checks PC Game Pass availability via the Microsoft catalog API (name matching). Games found in the catalog have their `xgp` field set to `true` in the Gist, which shows a Game Pass badge in the app.
