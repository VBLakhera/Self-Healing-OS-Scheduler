from dataclasses import dataclass, field

import numpy as np
from sklearn.ensemble import IsolationForest

FEATURES = ("memory_rss", "num_fds", "num_threads")

MEANING = {
    "memory_rss": "memory growing and never being freed",
    "num_fds": "files opened and never closed",
    "num_threads": "threads piling up",
}

FLOOR = {"memory_rss": 4096.0, "num_fds": 0.01, "num_threads": 0.01}

Z_BIG = 10.0
Z_BIG_RUNS = 2
SCORE_SD_FLOOR = 0.01


def slope(snaps, feat):
    t = np.array([s["timestamp"] for s in snaps], dtype=float)
    y = np.array([float(s[feat]) for s in snaps], dtype=float)
    t = t - t.mean()
    d = (t * t).sum()
    if d == 0:
        return 0.0
    return float((t * (y - y.mean())).sum() / d)


@dataclass
class Result:
    window_index: int
    phase: str
    features: dict = field(default_factory=dict)
    score: float = 0.0
    z_scores: dict = field(default_factory=dict)
    is_anomaly: bool = False
    severity: str = "none"
    consecutive: int = 0
    drivers: list = field(default_factory=list)
    explanation: str = ""


class Detector:
    def __init__(self, window_size=8, baseline_windows=10, isolation_sigma=1.0,
                 n_estimators=50, z_driver=3.0, escalate_after=3, random_state=42):
        self.window_size = window_size
        self.baseline_windows = baseline_windows
        self.isolation_sigma = isolation_sigma
        self.n_estimators = n_estimators
        self.z_driver = z_driver
        self.escalate_after = escalate_after
        self.random_state = random_state
        self.model = None
        self.windows_seen = 0
        self.consecutive_anomalies = 0
        self.baseline_envelope = 0.0
        self._fitted = False
        self._base = []
        self._mean = None
        self._std = None
        self._floor = np.array([FLOOR[f] for f in FEATURES])

    @property
    def ready(self):
        return self._fitted

    @property
    def boundary(self):
        return max(self.isolation_sigma, self.baseline_envelope)

    @property
    def baseline_progress(self):
        return min(len(self._base), self.baseline_windows)

    def observe(self, snaps):
        if len(snaps) < self.window_size:
            return None
        w = snaps[-self.window_size:]
        feats = {f: slope(w, f) for f in FEATURES}
        x = np.array([feats[f] for f in FEATURES], dtype=float)
        self.windows_seen += 1

        if not self._fitted:
            return self._learn(x, feats)

        z = self._zscores(x)
        drivers = self._drivers(z)
        score = self._isolation(x)
        zmax = max(abs(v) for v in z.values())
        by_score = score >= self.boundary
        if not by_score and zmax < Z_BIG:
            self.consecutive_anomalies = 0
            return Result(self.windows_seen, "monitoring", feats, score, z,
                          explanation="normal for this process")
        self.consecutive_anomalies += 1
        sev = self._severity(z)
        return Result(self.windows_seen, "monitoring", feats, score, z, True, sev,
                      self.consecutive_anomalies, drivers,
                      self._explain(drivers, self.consecutive_anomalies))

    def _learn(self, x, feats):
        self._base.append(x)
        n = len(self._base)
        if n >= self.baseline_windows:
            self._fit()
            msg = "baseline done after %d windows, scoring with isolation forest" % n
        else:
            msg = "learning baseline %d/%d" % (n, self.baseline_windows)
        return Result(self.windows_seen, "baseline", feats, explanation=msg)

    def _fit(self):
        X = np.vstack(self._base)
        self._mean = X.mean(axis=0)
        sd = X.std(axis=0, ddof=1) if len(X) > 1 else np.zeros(len(FEATURES))
        self._std = np.maximum(sd, self._floor)
        self._fitted = True

    def _isolation(self, x):
        X = np.vstack([self._base, x])
        model = IsolationForest(n_estimators=self.n_estimators,
                                random_state=self.random_state)
        model.fit(X)
        self.model = model
        scores = model.score_samples(X)
        base = scores[:-1]
        mu = float(base.mean())
        sd = max(float(base.std(ddof=1)), SCORE_SD_FLOOR)
        self.baseline_envelope = float(((mu - base) / sd).max())
        return (mu - float(scores[-1])) / sd

    def _zscores(self, x):
        z = (x - self._mean) / self._std
        return {f: float(z[i]) for i, f in enumerate(FEATURES)}

    def _drivers(self, z):
        return sorted([f for f, v in z.items() if abs(v) >= self.z_driver],
                      key=lambda f: abs(z[f]), reverse=True)

    def _severity(self, z):
        extreme = (max(abs(v) for v in z.values()) >= Z_BIG
                   and self.consecutive_anomalies >= Z_BIG_RUNS)
        if extreme or self.consecutive_anomalies >= self.escalate_after:
            return "severe"
        return "mild"

    def _explain(self, drivers, runs):
        if drivers:
            why = "; ".join(MEANING[f] for f in drivers)
        else:
            why = "something looks off, but nothing stands out on its own"
        return "%s (seen %d time%s in a row)" % (why, runs, "" if runs == 1 else "s")


def slopes(snaps):
    return {f: slope(snaps, f) for f in FEATURES}
