"""Uncle keeps his own time sheet: how long he has been awake, and what that cost.

A Sprite is billed only while it runs. When nobody talks to Uncle it goes to sleep
and the service stops; the next request wakes it and the service starts again.
Each start is a row in `boots`, and a heartbeat every few seconds marks the last
moment he was seen awake. CPU comes from /proc/stat and memory from /proc/meminfo,
so the cost is an estimate from Fly's published rates, not Fly's invoice.
"""
import os
import shutil
import threading
import time

# Fly's published Sprite rates (fly.io/sprites, Nov 2026)
CPU_HOUR = 0.0385
GB_HOUR = 0.021875
HOT_STORAGE_GB_HOUR = 0.000683

HEARTBEAT_S = 5


def cpu_seconds():
    """Busy CPU seconds for the whole machine since it started."""
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        vals = [int(x) for x in parts[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        return (sum(vals) - idle) / float(hz)
    except Exception:  # noqa: BLE001  (macOS has no /proc)
        return time.process_time()


def mem_gb():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0])
        used_kb = info["MemTotal"] - info.get("MemAvailable", info.get("MemFree", 0))
        return used_kb / 1024 / 1024
    except Exception:  # noqa: BLE001
        return 0.1


def disk_gb(path="/"):
    try:
        return shutil.disk_usage(path).used / 1024 ** 3
    except Exception:  # noqa: BLE001
        return 0.0


class Meter:
    def __init__(self, store, disk_path="/"):
        self.store = store
        self.disk_path = disk_path
        self.boot_id = None
        self.started_at = None
        self._stop = threading.Event()

    def _new_wake(self, now):
        self.started_at = now
        self._last_beat = now
        cpu = cpu_seconds()
        self.boot_id = self.store.run(
            "INSERT INTO boots(started_at, last_seen, cpu_start, cpu_last, disk_gb) VALUES(?,?,?,?,?)",
            (now, now, cpu, cpu, disk_gb(self.disk_path)))

    def start(self):
        self._new_wake(time.time())
        t = threading.Thread(target=self._beat, daemon=True, name="meter")
        t.start()
        return self

    def beat(self, now=None):
        now = now or time.time()
        # If the Sprite was suspended with this process still alive, the heartbeat
        # thread simply stops ticking. A long gap means he was asleep: start a new wake.
        if now - self._last_beat > 3 * HEARTBEAT_S:
            self._new_wake(now)
            return
        self._last_beat = now
        m = mem_gb()
        self.store.run(
            "UPDATE boots SET last_seen=?, cpu_last=?, mem_sum=mem_sum+?, mem_samples=mem_samples+1 WHERE id=?",
            (now, cpu_seconds(), m, self.boot_id))

    def touch(self):
        """Called on every request, so a wake is noticed at once, not at the next tick."""
        try:
            self.beat()
        except Exception:  # noqa: BLE001
            pass

    def _beat(self):
        while not self._stop.wait(HEARTBEAT_S):
            try:
                self.beat()
            except Exception:  # noqa: BLE001
                pass

    def stop(self):
        self._stop.set()


def summarize(rows, now=None):
    """Totals over boots rows. Pure function so it can be tested."""
    awake = cpu = gb_hours = storage = 0.0
    for r in rows:
        span = max(0.0, (r["last_seen"] or r["started_at"]) - r["started_at"])
        awake += span
        cpu += max(0.0, (r["cpu_last"] or 0) - (r["cpu_start"] or 0))
        avg_mem = (r["mem_sum"] / r["mem_samples"]) if r.get("mem_samples") else 0.0
        gb_hours += avg_mem * span / 3600
        storage += (r.get("disk_gb") or 0) * span / 3600
    cost = cpu / 3600 * CPU_HOUR + gb_hours * GB_HOUR + storage * HOT_STORAGE_GB_HOUR
    return {"wakes": len(rows), "awake_s": awake, "cpu_s": cpu, "cost_usd": cost}


def stats(store, current_boot_id=None, since=None):
    rows = store.q("SELECT * FROM boots" + (" WHERE started_at>=?" if since else ""), (since,) if since else ())
    s = summarize(rows)
    first = store.one("SELECT MIN(started_at) t FROM boots")
    s["since"] = (first or {}).get("t")
    if current_boot_id:
        cur = store.one("SELECT * FROM boots WHERE id=?", (current_boot_id,))
        if cur:
            s["this_wake_s"] = time.time() - cur["started_at"]
        prev = store.one("SELECT * FROM boots WHERE id<? ORDER BY id DESC LIMIT 1", (current_boot_id,))
        if prev and cur:
            s["slept_s"] = max(0.0, cur["started_at"] - (prev["last_seen"] or prev["started_at"]))
    if s["since"]:
        s["asleep_share"] = max(0.0, 1 - s["awake_s"] / max(1.0, time.time() - s["since"]))
    return s
