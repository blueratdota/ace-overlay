"""Record what AC EVO publishes about the *other* cars, to find out whether a standings overlay is possible.

    .venv\\Scripts\\python tools\\probe_standings.py [seconds]

Run it during a race against AI (multi-class if possible) and drive a few laps across the line, then
press Ctrl+C (or pass a duration). It snapshots every shared-memory block it can find twice a second,
whole mapped regions included (not just the documented struct), into probe-output\\<time>\\, and
writes report.txt there:

1. text found anywhere in the blocks (driver names, car models, class names would show up here),
2. which bytes of the undocumented regions change, read as int32 / float, flagging lap-time-like values,
3. how the 60-entry car_ids / car_coordinates tables are filled,
4. text in the static block (track, session).
"""

import ctypes
import json
import re
import struct
import sys
import time
from collections import defaultdict
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ace_overlay.shm import GRAPHICS_TAG, PHYSICS_TAG, Graphics  # noqa: E402

STATIC_TAG = "Local\\acevo_pmf_static"
GUESSES = ["cars", "leaderboard", "session", "timing", "drivers", "broadcast", "extended", "static2",
           "standings", "entries", "entrylist", "carinfo", "ranking", "multiplayer"]
INTERVAL = 0.5
LAP_MS = (20_000, 900_000)  # int32 values in this range might be lap times

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.OpenFileMappingW.restype = wintypes.HANDLE
_k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
_k32.MapViewOfFile.restype = ctypes.c_void_p


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]


_k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
_k32.VirtualQuery.restype = ctypes.c_size_t


def attach(tag):
    """(address, mapped size) of a named mapping, or None. Read-only; never creates one."""
    handle = _k32.OpenFileMappingW(0x0004, False, tag)
    if not handle:
        return None
    view = _k32.MapViewOfFile(handle, 0x0004, 0, 0, 0)
    if not view:
        return None
    info = MBI()
    _k32.VirtualQuery(view, ctypes.byref(info), ctypes.sizeof(info))
    return view, info.RegionSize


def field_map(struct_type, base=0, prefix=""):
    """[(offset, size, name)] for every field, nested structs and struct arrays expanded."""
    out = []
    for name, ftype in struct_type._fields_:
        desc = getattr(struct_type, name)
        off = base + desc.offset
        elem = getattr(ftype, "_type_", None)
        if isinstance(ftype, type) and issubclass(ftype, ctypes.Structure):
            out += field_map(ftype, off, f"{prefix}{name}.")
        elif isinstance(elem, type) and issubclass(elem, ctypes.Structure):
            for i in range(ftype._length_):
                out += field_map(elem, off + i * ctypes.sizeof(elem), f"{prefix}{name}[{i}].")
        else:
            out.append((off, desc.size, prefix + name))
    return out


GRAPHICS_FIELDS = field_map(Graphics)


def where(offset):
    for off, size, name in GRAPHICS_FIELDS:
        if off <= offset < off + size:
            return f"{name}+{offset - off}"
    return f"past the Graphics struct (+{offset - ctypes.sizeof(Graphics)})"


def strings(data):
    """{(offset, encoding): text} for printable runs of 4+ characters."""
    found = {}
    for m in re.finditer(rb"[\x20-\x7e]{4,}", data):
        found[m.start(), "ascii"] = m.group().decode()
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){4,}", data):
        found[m.start(), "utf16"] = m.group().decode("utf-16-le")
    return found


def text(c_chars):
    return bytes(c_chars).split(b"\0")[0].decode(errors="replace")


def record(out_dir, duration):
    blocks = {}
    for name, tag in [("physics", PHYSICS_TAG), ("graphics", GRAPHICS_TAG), ("static", STATIC_TAG)] + \
            [(g, f"Local\\acevo_pmf_{g}") for g in GUESSES]:
        found = attach(tag)
        if found:
            blocks[name] = found
    if "graphics" not in blocks:
        sys.exit("The game isn't running (no graphics block). Start a session first.")
    print("Blocks found:", ", ".join(f"{n} ({size} bytes mapped)" for n, (_, size) in blocks.items()))
    print(f"Recording to {out_dir}. Drive a few laps, then press Ctrl+C.")

    files = {n: open(out_dir / f"{n}.bin", "wb") for n in blocks}
    index = open(out_dir / "index.jsonl", "w")
    sizes = {n: size for n, (_, size) in blocks.items()}
    (out_dir / "sizes.json").write_text(json.dumps(sizes))
    start = time.monotonic()
    count = 0
    try:
        while duration is None or time.monotonic() - start < duration:
            t = time.monotonic() - start
            for n, (addr, size) in blocks.items():
                files[n].write(ctypes.string_at(addr, size))
            g = Graphics.from_buffer_copy(ctypes.string_at(blocks["graphics"][0], ctypes.sizeof(Graphics)))
            row = dict(t=round(t, 2), car=text(g.car_model), status=g.status, pos=g.current_pos,
                       drivers=g.total_drivers, active=g.active_cars, gap_ahead=round(g.gap_ahead, 3),
                       gap_behind=round(g.gap_behind, 3), lap=g.total_lap_count, last=g.last_laptime_ms,
                       best=g.best_laptime_ms, npos=round(g.npos, 4))
            index.write(json.dumps(row) + "\n")
            count += 1
            if count % 20 == 0:
                print(f"  {t:6.0f} s  P{row['pos']}/{row['drivers']}  cars {row['active']}  lap {row['lap']}"
                      f"  {row['car']}", flush=True)
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        pass
    for f in files.values():
        f.close()
    index.close()
    print(f"Recorded {count} samples.")


def frames(out_dir, name, size):
    data = (out_dir / f"{name}.bin").read_bytes()
    return [data[i:i + size] for i in range(0, len(data) - size + 1, size)]


def report(out_dir):
    sizes = json.loads((out_dir / "sizes.json").read_text())
    rows = [json.loads(line) for line in (out_dir / "index.jsonl").read_text().splitlines()]
    lines = []
    say = lines.append
    gsize = ctypes.sizeof(Graphics)
    gframes = frames(out_dir, "graphics", sizes["graphics"])
    g0 = Graphics.from_buffer_copy(gframes[-1][:gsize])

    say(f"# Standings probe, {len(rows)} samples over {rows[-1]['t']:.0f} s")
    say(f"Cars seen: {sorted({r['car'] for r in rows})}")
    say(f"Player: {text(g0.driver_name)} {text(g0.driver_surname)}")
    say(f"Blocks: {sizes}  (Graphics struct = {gsize} bytes)")
    say(f"Positions seen: {sorted({(r['pos'], r['drivers']) for r in rows})}")
    say(f"active_cars seen: {sorted({r['active'] for r in rows})}")
    say(f"Laps completed: {rows[0]['lap']} -> {rows[-1]['lap']}; last/best lap ms: "
        f"{sorted({r['last'] for r in rows})[-5:]} / {sorted({r['best'] for r in rows})[-5:]}")

    say("\n## 1. Text in every block (union over all samples)")
    for name, size in sizes.items():
        found = {}
        for frame in frames(out_dir, name, size)[:: max(1, len(rows) // 50)]:
            found.update(strings(frame))
        say(f"\n### {name} ({len(found)} strings)")
        for (off, enc), s in sorted(found.items()):
            loc = where(off) if name == "graphics" else f"+{off}"
            say(f"  {off:6d} {enc:5s} {loc:40s} {s!r}")

    say("\n## 2. Changing bytes in undocumented graphics regions")
    regions = [(n, o, s) for o, s, n in GRAPHICS_FIELDS
               if n in ("timing_state", "pit_info", "assists_state", "car_damage")]
    if sizes["graphics"] > gsize:
        regions.append(("tail past struct", gsize, sizes["graphics"] - gsize))
    lap_times = {r["last"] for r in rows} | {r["best"] for r in rows}
    for name, off, size in regions:
        say(f"\n### {name} (offset {off}, {size} bytes)")
        changed = 0
        for o in range(off, off + size - 3, 4):
            ints = [struct.unpack_from("<i", f, o)[0] for f in gframes]
            if len(set(ints)) == 1:
                if ints[0]:
                    say(f"  +{o - off:4d} constant int {ints[0]}  float {struct.unpack_from('<f', gframes[0], o)[0]:.4g}")
                continue
            changed += 1
            floats = [struct.unpack_from("<f", f, o)[0] for f in gframes]
            flag = " LAP-TIME-LIKE" if any(LAP_MS[0] <= v <= LAP_MS[1] for v in ints) else ""
            flag += " MATCHES PLAYER LAP" if lap_times & set(ints) - {0} else ""
            say(f"  +{o - off:4d} {len(set(ints)):5d} values  int {min(ints)}..{max(ints)} (last {ints[-1]})"
                f"  float {min(floats):.4g}..{max(floats):.4g}{flag}")
        say(f"  ({changed} changing 4-byte words)")

    say("\n## 3. car_ids / car_coordinates")
    per_index = defaultdict(set)
    counts = set()
    for f in gframes:
        g = Graphics.from_buffer_copy(f[:gsize])
        ids = [(a, b) for a, b in g.car_ids]
        coords = [tuple(c) for c in g.car_coordinates]
        counts.add((g.active_cars, sum(1 for i in ids if any(i)), sum(1 for c in coords if any(c))))
        for k, i in enumerate(ids):
            if any(i):
                per_index[k].add(i)
    say(f"(active_cars, non-zero ids, non-zero coords) seen: {sorted(counts)}")
    say(f"Indices whose id changed during the recording: {[k for k, v in per_index.items() if len(v) > 1]}")
    player = tuple(g0.player_car_id)
    focused = tuple(g0.focused_car_id)
    for k in sorted(per_index):
        (a, b), = list(per_index[k])[:1]
        tag = " <- player" if (a, b) == player else " <- focused" if (a, b) == focused else ""
        say(f"  [{k:2d}] {a:016x} {b:016x}  coords {[round(v, 1) for v in g0.car_coordinates[k]]}{tag}")
    say(f"player_car_id {player[0]:016x} {player[1]:016x}; focused {focused[0]:016x} {focused[1]:016x}")

    (out_dir / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:12]))
    print(f"... full report: {out_dir / 'report.txt'}")


def main():
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():  # re-run the report on an old recording
        report(Path(sys.argv[1]))
        return
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else None
    out_dir = ROOT / "probe-output" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    record(out_dir, duration)
    report(out_dir)


if __name__ == "__main__":
    main()
