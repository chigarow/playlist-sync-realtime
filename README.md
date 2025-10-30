# Playlist Sync Service

A lightweight playlist synchronization service designed for low-resource Android devices running [Termux](https://termux.dev/). The service keeps selected playlists in sync across Spotify, Apple Music, and YouTube Music while exposing a minimal local-only web interface for configuration and OAuth flows.

## Features
- FastAPI-based web UI bound to `127.0.0.1` only (default port `8080`).
- OAuth authentication helpers for Spotify and YouTube Music, plus Apple Music MusicKit login.
- Background worker that periodically mirrors changes from a primary playlist to linked playlists on the other services.
- JSON-backed storage for tokens and sync group definitions (no external database required).
- Designed for continuous operation on constrained devices (single background task, async HTTP clients, minimal dependencies).

## Project Layout
```
playlist-sync/
├── app.py                # CLI entrypoint (`python app.py`)
├── pyproject.toml        # Project metadata (Poetry)
├── requirements.txt      # Runtime dependency pinning
├── playlist_sync/
│   ├── app.py            # ASGI app factory
│   ├── config.py         # Configuration models & helpers
│   ├── storage.py        # Lightweight async JSON store
│   ├── models.py         # Core dataclasses (tracks, playlists)
│   ├── connectors/       # Service-specific API integrations
│   ├── sync.py           # Sync manager and background worker
│   └── web/              # FastAPI routes + Jinja templates
└── README.md
```

## Termux Setup

1. **Install base packages**
   ```bash
   pkg update
   pkg install python git openssl clang rust
   ```
   Rust is only required if a dependency needs compilation; you may remove it after installation.

2. **Clone the project**
   ```bash
   git clone https://github.com/your-user/playlist-sync.git
   cd playlist-sync
   ```

3. **Create a virtual environment (recommended)**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   ```

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   (Alternatively, `pip install .` uses `pyproject.toml`.)

## Configuration

Set the following environment variables before launching the service (e.g., add them to `~/.termux/profile` or export in the shell):

| Variable | Purpose |
| --- | --- |
| `SPOTIFY_CLIENT_ID` | Spotify app client ID |
| `SPOTIFY_CLIENT_SECRET` | Spotify app client secret |
| `SPOTIFY_REDIRECT_URI` (optional) | Override callback URL (defaults to `http://127.0.0.1:8080/auth/spotify/callback`) |
| `YOUTUBE_CLIENT_ID` | OAuth client ID from Google Cloud Console |
| `YOUTUBE_CLIENT_SECRET` | OAuth client secret |
| `APPLE_DEVELOPER_TOKEN` (optional) | Pre-generated developer token; otherwise paste into the UI |
| `PLAYLIST_SYNC_POLL_INTERVAL` (optional) | Poll interval in seconds (default `60`) |
| `PLAYLIST_SYNC_PORT` (optional) | Web UI port (default `8080`) |
| `PLAYLIST_SYNC_DATA` (optional) | Custom state directory (default `~/.local/share/playlist-sync`) |

### Apple Music specifics
Apple Music requires a **Developer Token** (valid up to 6 months) and a **Music User Token** (issued after MusicKit authorization):

1. Generate a developer token on a trusted machine using your Apple Music private key:
   ```python
   import jwt, datetime
   from pathlib import Path

   key_id = "YOUR_KEY_ID"
   team_id = "YOUR_TEAM_ID"
   private_key = Path("AuthKey_XXXXXXXXXX.p8").read_text()

   token = jwt.encode(
       {
           "iss": team_id,
           "iat": datetime.datetime.utcnow(),
           "exp": datetime.datetime.utcnow() + datetime.timedelta(days=120),
           "aud": "https://music.apple.com",
       },
       private_key,
       algorithm="ES256",
       headers={"kid": key_id},
   )
   print(token)
   ```
2. Copy the token string and paste it into the Apple Music card on the web UI (`Developer Token` box).
3. Click **Save Developer Token**, then **Authorize with Apple Music** to trigger the MusicKit login (this produces the Music User Token automatically and stores it server-side).

## Running the Service

```bash
source .venv/bin/activate   # if using a venv
python app.py
```

Open a browser on the device and visit `http://127.0.0.1:8080/`. The dashboard lets you:
1. Run the OAuth flows for Spotify and YouTube Music (buttons redirect to official login pages).
2. Paste the Apple Music developer token and authorize via MusicKit.
3. Review playlists fetched from each service.
4. Create “sync groups” that define a primary playlist and corresponding target playlists on the other services.

The background worker polls for changes every `PLAYLIST_SYNC_POLL_INTERVAL` seconds. When a primary playlist changes, the service searches each track on the target services and replaces the target playlist with the mapped tracks. Empty playlists are mirrored as empty.

## Testing

Run the automated test suite (with coverage) after installing development dependencies:

```bash
pytest --cov=playlist_sync --cov-report=term-missing
```

## Sync Strategy

- Each sync group has a **primary service**. Changes only flow **from primary to the linked targets** to avoid ambiguous reconciliation.
- Track matching is metadata-based (title, artist, album). If a track cannot be matched on a target service it is skipped.
- Apple Music syncing relies on the MusicKit web API. Library-only tracks without catalog IDs may be skipped due to API limitations.

## Data Files

State is stored in `${PLAYLIST_SYNC_DATA}/state.json`, containing:
- OAuth tokens for each provider.
- Defined sync groups.
- Hash snapshots of primary playlists to detect changes efficiently.

Back up this file if you reinstall Termux or migrate devices.

## Limitations & Notes

- The service binds to `127.0.0.1` and should be reverse-proxied if remote access is required. Exposing the UI publicly is **not recommended**.
- Apple Music MusicKit requires network access to Apple endpoints; ensure the Termux environment has outbound connectivity when linking accounts.
- YouTube API quotas apply. Avoid very short poll intervals.
- The matching strategy is conservative and may miss mixes/variants that differ significantly in metadata.

## Development

Optional tooling is defined under `[tool.poetry.group.dev.dependencies]` (Black, Ruff, Pytest). To set up a full development environment:

```bash
pip install -r dev-requirements.txt
black playlist_sync
ruff check playlist_sync
pytest --cov=playlist_sync
```

Pull requests and contributions are welcome—focus areas include smarter diffing, per-track change propagation, and richer status reporting in the UI.
