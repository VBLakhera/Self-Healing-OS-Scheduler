import argparse
import os
import subprocess
import sys
import time

import psutil

import db
import detector
import healer
import monitor

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "demo_leaky_process.py")


def parse_args():
    ap = argparse.ArgumentParser(description="self-healing process monitor")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--pid", type=int, help="existing process to watch")
    g.add_argument("--demo", action="store_true", help="spawn the leaky demo process")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between samples")
    ap.add_argument("--window", type=int, default=8, help="snapshots per window")
    ap.add_argument("--baseline-windows", type=int, default=10,
                    help="windows of healthy data to learn from")
    ap.add_argument("--db", default=db.DEFAULT_DB, help="sqlite file")
    ap.add_argument("--dry-run", action="store_true", help="detect but never act")
    return ap.parse_args()


def find_worker(pid, timeout=2.0):
    parent = psutil.Process(pid)
    end = time.time() + timeout
    while time.time() < end:
        kids = parent.children()
        if kids:
            return kids[0].pid
        time.sleep(0.05)
    return pid


def mb(v):
    return "%.1fMB" % (v / (1024 * 1024))


def clock(sec):
    return "%02d:%02d" % (sec // 60, sec % 60)


def tag(result, det, filled):
    if result is None:
        return "warming up %d/%d" % (filled, det.window_size)
    if result.phase == "baseline":
        return "learning %d/%d" % (det.baseline_progress, det.baseline_windows)
    if result.is_anomaly:
        return "! %s" % result.severity.upper()
    return "ok"


def report(database, pid):
    s = database.stats(pid)
    print()
    print("----- done -----")
    if s["snapshots"]:
        print("pid %d   %d samples   %ds   memory %s -> %s"
              % (pid, s["snapshots"], s["last"] - s["first"], mb(s["lo"]), mb(s["hi"])))
    print("%d incidents (throttled %d, killed %d)"
          % (s["incidents"], s["throttled"], s["killed"]))


def run(a):
    if not a.demo and a.pid is None:
        print("need either --pid or --demo")
        return 2

    database = db.MonitorDB(a.db)
    det = detector.Detector(window_size=a.window, baseline_windows=a.baseline_windows)
    heal = healer.Healer(dry_run=a.dry_run)

    child = None
    warmup = 0.0
    if a.demo:
        warmup = a.interval * (a.window + a.baseline_windows + 3)
        child = subprocess.Popen([sys.executable, "-u", DEMO, "--warmup", str(warmup)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pid = find_worker(child.pid)
    else:
        pid = a.pid

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        print("no process with pid %d" % pid)
        if child:
            child.kill()
        return 2

    print("self-healing monitor   pid %d   every %gs" % (pid, a.interval))
    if heal.dry_run:
        print("dry run, will not touch anything")
    print()

    t0 = time.time()
    try:
        while True:
            tick = time.time()
            try:
                snap = monitor.snapshot(proc)
            except psutil.NoSuchProcess:
                print()
                print("pid %d is gone, stopping" % pid)
                break

            database.add_snapshot(snap)
            window = database.last_snapshots(pid, det.window_size)
            r = det.observe(window)

            print("[%s]  %-8s  %s"
                  % (clock(time.time() - t0), mb(snap["memory_rss"]),
                     tag(r, det, len(window))))

            if r and r.is_anomaly:
                act = heal.act(pid, r)
                database.add_incident(pid, snap["timestamp"], r.severity,
                                      act["action"],
                                      r.explanation + " | " + act["detail"])
                why = "; ".join(detector.MEANING[f] for f in r.drivers) or "unusual window"
                print("         %s: %s" % (act["action"], why))

            time.sleep(max(0.0, a.interval - (time.time() - tick)))
    except KeyboardInterrupt:
        print("stopped by user")
    finally:
        if child is not None:
            try:
                w = psutil.Process(pid)
                if w.is_running() and w.pid != os.getpid():
                    w.kill()
            except psutil.Error:
                pass
            if child.poll() is None:
                child.kill()
            child.wait()
        report(database, pid)
        database.close()
    return 0


if __name__ == "__main__":
    sys.exit(run(parse_args()))
