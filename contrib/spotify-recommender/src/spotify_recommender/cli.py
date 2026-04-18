from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .auth import force_auth, get_client
from .config import load_config
from .features import build_feature_matrix
from .history import import_extended_history
from .ingest import (
    hydrate_artists,
    ingest_liked,
    ingest_playlists,
    ingest_recent,
    ingest_top,
)
from .lastfm import enrich_all_artists
from .mood import MoodModel, fit_mood_model, resolve_mood_vector
from .recommend import recommend
from .storage import Storage

console = Console()


@click.group()
def cli() -> None:
    """Mood-aware Spotify recommender trained on your own library."""


@cli.command()
def auth() -> None:
    """Run the Spotify OAuth flow. Opens a browser."""
    cfg = load_config()
    user = force_auth(cfg)
    console.print(f"[green]Authenticated as[/green] {user}")
    console.print(f"Token cached at {cfg.token_cache_path}")


@cli.command()
def ingest() -> None:
    """Pull liked songs, playlists, recent plays, top tracks into the cache."""
    cfg = load_config()
    sp = get_client(cfg)
    store = Storage(cfg.db_path)

    console.print("[cyan]Fetching liked songs...[/cyan]")
    n_liked = ingest_liked(sp, store)
    console.print(f"  {n_liked} liked tracks")

    console.print("[cyan]Fetching playlists...[/cyan]")
    n_pl, n_pl_tracks = ingest_playlists(sp, store)
    console.print(f"  {n_pl} playlists, {n_pl_tracks} playlist tracks")

    console.print("[cyan]Fetching recently played (last 50)...[/cyan]")
    n_recent = ingest_recent(sp, store)
    console.print(f"  {n_recent} recent plays")

    console.print("[cyan]Fetching top tracks (short/medium/long)...[/cyan]")
    counts = ingest_top(sp, store)
    for k, v in counts.items():
        console.print(f"  {k}: {v}")

    console.print("[cyan]Hydrating artist genres + popularity...[/cyan]")
    n_art = hydrate_artists(sp, store)
    console.print(f"  {n_art} artists hydrated")

    console.print(f"[green]Cache written to[/green] {cfg.db_path}")


@cli.command("enrich-tags")
def enrich_tags() -> None:
    """Enrich cached artists with Last.fm top tags (needs LASTFM_API_KEY)."""
    cfg = load_config()
    if not cfg.lastfm_api_key:
        console.print(
            "[yellow]LASTFM_API_KEY not set. Skipping tag enrichment.[/yellow]"
        )
        sys.exit(1)
    store = Storage(cfg.db_path)
    console.print("[cyan]Fetching Last.fm tags for known artists...[/cyan]")
    n = enrich_all_artists(cfg.lastfm_api_key, store)
    console.print(f"[green]Tagged {n} artists[/green]")


@cli.command("import-history")
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
def import_history_cmd(directory: str) -> None:
    """Import Spotify 'Extended Streaming History' JSON export directory."""
    cfg = load_config()
    store = Storage(cfg.db_path)
    n = import_extended_history(Path(directory), store)
    console.print(f"[green]Imported {n} plays[/green]")


@cli.command()
@click.option("--k", default=8, show_default=True, help="Number of mood clusters.")
def train(k: int) -> None:
    """Fit the mood-clustering model over the cached library."""
    cfg = load_config()
    store = Storage(cfg.db_path)
    console.print("[cyan]Building feature matrix...[/cyan]")
    fm = build_feature_matrix(store)
    console.print(
        f"  {fm.matrix.shape[0]} tracks × {fm.matrix.shape[1]} features"
    )
    console.print(f"[cyan]Fitting KMeans (k={k})...[/cyan]")
    model = fit_mood_model(fm, k=k)
    model.save(cfg.model_path)
    # Cache the feature matrix alongside so `recommend` doesn't rebuild.
    import pickle

    with (cfg.home / "features.pkl").open("wb") as fh:
        pickle.dump(fm, fh)
    console.print(f"[green]Saved model[/green] to {cfg.model_path}")


@cli.command()
def moods() -> None:
    """List learned vibe clusters and their top terms."""
    cfg = load_config()
    if not cfg.model_path.exists():
        console.print(
            "[red]No model. Run `spotify-recommender train` first.[/red]"
        )
        sys.exit(1)
    model = MoodModel.load(cfg.model_path)
    table = Table(title="Learned vibes")
    table.add_column("#", justify="right")
    table.add_column("Name", style="cyan")
    table.add_column("Tracks", justify="right")
    table.add_column("Top terms")
    import numpy as np

    for i, name in enumerate(model.cluster_names):
        count = int(np.sum(model.labels == i))
        terms = ", ".join(model.cluster_top_terms[i][:8])
        table.add_row(str(i), name, str(count), terms)
    console.print(table)


@cli.command()
@click.option("--mood", default=None, help="Mood name or tag (e.g. chill).")
@click.option(
    "--auto-mood",
    is_flag=True,
    default=False,
    help="Infer mood from your last plays.",
)
@click.option("--n", default=20, show_default=True, help="Number of tracks.")
@click.option(
    "--exploration",
    default=0.15,
    show_default=True,
    help="Fraction of recommendations reserved for unheard tracks (0..1).",
)
@click.option(
    "--recent-window",
    default=15,
    show_default=True,
    help="How many recent plays to average for --auto-mood.",
)
def recommend_cmd(
    mood: str | None,
    auto_mood: bool,
    n: int,
    exploration: float,
    recent_window: int,
) -> None:
    """Produce ranked recommendations for a given mood."""
    cfg = load_config()
    if not cfg.model_path.exists():
        console.print(
            "[red]No model. Run `spotify-recommender train` first.[/red]"
        )
        sys.exit(1)

    import pickle

    with (cfg.home / "features.pkl").open("rb") as fh:
        fm = pickle.load(fh)
    model = MoodModel.load(cfg.model_path)
    store = Storage(cfg.db_path)

    recent_ids: list[str] | None = None
    if auto_mood:
        with store.conn() as c:
            recent_ids = store.recent_plays(c, recent_window)
        if not recent_ids:
            console.print(
                "[yellow]No recent plays cached. Falling back to --mood.[/yellow]"
            )
            if not mood:
                console.print(
                    "[red]Provide --mood or ingest more data.[/red]"
                )
                sys.exit(1)

    try:
        query_vec, resolved = resolve_mood_vector(
            mood, model, fm, recent_track_ids=recent_ids
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    sp = None
    if exploration > 0:
        try:
            sp = get_client(cfg)
        except Exception as e:  # noqa: BLE001 — auth path can raise many things
            console.print(
                f"[yellow]Skipping novel tracks (Spotify unavailable): {e}[/yellow]"
            )

    recs = recommend(
        fm=fm,
        model=model,
        store=store,
        query_vec=query_vec,
        n=n,
        exploration=exploration,
        sp=sp,
    )

    table = Table(title=f"Mood: {resolved}")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Artists")
    table.add_column("Score", justify="right")
    table.add_column("Source", style="magenta")
    for i, r in enumerate(recs, 1):
        table.add_row(
            str(i), r.title, r.artists, f"{r.score:.3f}", r.reason
        )
    console.print(table)


def main() -> None:
    cli.main(standalone_mode=True)


# Allow `python -m spotify_recommender` as an alternate entry point.
if __name__ == "__main__":
    main()
