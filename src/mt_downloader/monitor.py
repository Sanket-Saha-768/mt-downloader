import threading, logging
from mt_downloader.state import SharedState, ChunkSpec
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
    TaskID,
)
from rich.console import Console
from rich.logging import RichHandler

log = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> Console:
    """
    Wire the root logger through Rich so that log lines printed by worker
    threads appear above the progress bars without breaking the display.
    Returns the Console instance that monitor and logging both share.
    """
    console = Console(stderr=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[
            RichHandler(
                console=console,
                show_time=True,
                show_path=False,
                markup=False,
            )
        ],
    )
    return console


def progress_monitor(
    state: SharedState,
    total: int,
    stop: threading.Event,
    chunks: list[ChunkSpec],
    console: Console | None = None,
) -> None:
    """
    Rich-based progress display with one bar per thread plus an overall bar.
    """

    if console is None:
        console = Console(stderr=True)

    chunk_len = {c.index: c.length for c in chunks}

    columns = [
        TextColumn("[bold]{task.description:<12}"),
        BarColumn(bar_width=36),
        "[progress.percentage]{task.percentage:>5.1f}%",
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    ]

    with Progress(*columns, console=console, refresh_per_second=4) as progress:

        overall_id: TaskID = progress.add_task("Overall", total=total)
        thread_ids: dict[int, TaskID] = {
            c.index: progress.add_task(f"Thread {c.index}", total=c.length)
            for c in sorted(chunks, key=lambda c: c.index)
        }

        prev_done: dict[int, int] = {idx: 0 for idx in chunk_len}
        prev_total = 0

        while not stop.wait(0.25):
            with state.lock:
                snap = dict(state.progress)

            # Advance each thread bar by the delta since last tick
            for idx, task_id in thread_ids.items():
                current = snap.get(idx, 0)
                delta = current - prev_done[idx]
                if delta > 0:
                    progress.advance(task_id, delta)
                    prev_done[idx] = current

                # Mark errored chunks visibly
                if idx in state.errors:
                    progress.update(task_id, description=f"[red]Thread {idx}[/red]")

            # Advance overall bar
            total_done = sum(snap.values())
            overall_delta = total_done - prev_total
            if overall_delta > 0:
                progress.advance(overall_id, overall_delta)
                prev_total = total_done

        # Final sync — fill any remaining delta after stop is set
        with state.lock:
            snap = dict(state.progress)
        for idx, task_id in thread_ids.items():
            delta = snap.get(idx, 0) - prev_done[idx]
            if delta > 0:
                progress.advance(task_id, delta)
        total_done = sum(snap.values())
        final_delta = total_done - prev_total
        if final_delta > 0:
            progress.advance(overall_id, final_delta)
