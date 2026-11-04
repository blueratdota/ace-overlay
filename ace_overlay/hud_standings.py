"""Read snapshots written to the AC EVO log by the optional in-game bridge."""

import json
import time
from dataclasses import dataclass
from pathlib import Path

MARKER = b"ACE_OVERLAY_GRID_V1 "
MAX_AGE = 5
TAIL_BYTES = 128 * 1024


@dataclass(frozen=True)
class HudRow:
    position: int
    name: str
    model: str
    is_player: bool
    gap: str
    best: str
    last: str


def parse_snapshot(payload, now):
    try:
        timestamp, rows = json.loads(payload)
        if not 0 <= now - timestamp / 1000 <= MAX_AGE or not isinstance(rows, list):
            return []
    except (ValueError, TypeError):
        return []
    result = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 7:
            return []
        position, name, model, focused, gap, best, last = row
        if (type(position) is not int or position < 0 or type(focused) is not bool
                or not all(isinstance(value, str) for value in (name, model, gap, best, last))):
            return []
        result.append(HudRow(position, name, model, focused, gap, best, last))
    return sorted(result, key=lambda row: row.position)


class HudStandings:
    def __init__(self):
        self.logs = Path.home() / "Saved Games" / "ACE" / "Logs"
        self.rows = []
        self.next_read = 0

    def read(self):
        now = time.monotonic()
        if now < self.next_read:
            return self.rows
        self.next_read = now + 0.5
        self.rows = []
        try:
            latest = max(self.logs.glob("log-*.txt"), default=None)
            if latest is None:
                return self.rows
            with latest.open("rb") as log:
                size = log.seek(0, 2)
                log.seek(max(0, size - TAIL_BYTES))
                lines = log.read(TAIL_BYTES).split(b"\n")[:-1]
        except OSError:
            return self.rows
        for line in reversed(lines):
            if MARKER in line:
                self.rows = parse_snapshot(line.split(MARKER, 1)[1], time.time())
                break
        return self.rows
