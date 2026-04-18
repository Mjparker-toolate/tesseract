from __future__ import annotations

import json
from pathlib import Path

from .storage import Storage


def import_extended_history(path: Path, store: Storage) -> int:
    """Import Spotify's 'Extended Streaming History' JSON export.

    The export contains files like `Streaming_History_Audio_*.json`. Each
    entry has `spotify_track_uri` (e.g. `spotify:track:<id>`) and `ts`
    (ISO-8601 timestamp).
    """
    files = sorted(path.glob("Streaming_History_Audio_*.json"))
    if not files:
        # Fall back to any JSON file in the dir (older export format).
        files = sorted(path.glob("*.json"))
    n = 0
    with store.conn() as c:
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for entry in data:
                uri = entry.get("spotify_track_uri") or entry.get(
                    "spotify_track_id"
                )
                ts = entry.get("ts") or entry.get("endTime")
                if not uri or not ts:
                    continue
                track_id = uri.split(":")[-1] if ":" in uri else uri
                store.add_play(c, track_id, ts)
                n += 1
    return n
