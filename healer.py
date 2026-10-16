import os

import psutil

WINDOWS = os.name == "nt"


class Healer:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.throttled = False

    def act(self, pid, result):
        if not result.is_anomaly:
            return {"action": "none", "ok": True, "detail": "nothing to do"}

        if pid == os.getpid():
            return {"action": "none", "ok": False,
                    "detail": "that's my own pid, not touching it"}

        if result.severity == "severe":
            return self._kill(pid)
        return self._throttle(pid)

    def _throttle(self, pid):
        if self.throttled:
            return {"action": "throttle", "ok": True,
                    "detail": "already lowered it once, growth didn't stop"}
        if self.dry_run:
            return {"action": "throttle", "ok": True,
                    "detail": "dry run, would drop its priority"}
        try:
            p = psutil.Process(pid)
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if WINDOWS else psutil.NICE_HIGH)
        except psutil.NoSuchProcess:
            return {"action": "none", "ok": False, "detail": "process already gone"}
        except psutil.AccessDenied:
            return {"action": "throttle", "ok": False, "detail": "os said no"}

        self.throttled = True
        return {"action": "throttle", "ok": True,
                "detail": "priority dropped to below-normal" if WINDOWS
                else "priority dropped to nice 19"}

    def _kill(self, pid):
        if self.dry_run:
            return {"action": "terminate", "ok": True,
                    "detail": "dry run, would kill it"}
        try:
            p = psutil.Process(pid)
            p.kill()
            p.wait(timeout=5)
        except psutil.NoSuchProcess:
            return {"action": "none", "ok": False, "detail": "process already gone"}
        except psutil.TimeoutExpired:
            return {"action": "terminate", "ok": False,
                    "detail": "kill sent but it's still running"}
        except psutil.AccessDenied:
            return {"action": "terminate", "ok": False, "detail": "os said no"}
        return {"action": "terminate", "ok": True, "detail": "killed it"}
