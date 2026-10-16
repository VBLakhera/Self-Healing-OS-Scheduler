import time

import psutil


def fd_count(proc):
    try:
        return int(proc.num_fds())
    except (AttributeError, NotImplementedError, psutil.Error):
        pass
    try:
        return int(proc.num_handles())
    except (AttributeError, NotImplementedError, psutil.Error):
        return 0


def snapshot(proc, ts=None):
    if ts is None:
        ts = time.time()

    if not proc.is_running():
        raise psutil.NoSuchProcess(proc.pid)

    try:
        rss = int(proc.memory_info().rss)
    except psutil.Error:
        rss = 0

    try:
        threads = int(proc.num_threads())
    except psutil.Error:
        threads = 0

    return {
        "pid": proc.pid,
        "timestamp": ts,
        "memory_rss": rss,
        "num_fds": fd_count(proc),
        "num_threads": threads,
    }
