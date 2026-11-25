"""Statistics used to read the experiment. Plain numpy/scipy, no magic."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass
class Estimate:
    diff: float
    ci_low: float
    ci_high: float
    p_value: float


def welch(y_t: np.ndarray, y_c: np.ndarray) -> Estimate:
    """Difference in means with a Welch t interval (unequal variances)."""
    y_t, y_c = y_t[~np.isnan(y_t)], y_c[~np.isnan(y_c)]
    diff = y_t.mean() - y_c.mean()
    se = np.sqrt(y_t.var(ddof=1) / len(y_t) + y_c.var(ddof=1) / len(y_c))
    df = se**4 / (
        (y_t.var(ddof=1) / len(y_t)) ** 2 / (len(y_t) - 1)
        + (y_c.var(ddof=1) / len(y_c)) ** 2 / (len(y_c) - 1)
    )
    q = stats.t.ppf(0.975, df)
    p = 2 * stats.t.sf(abs(diff / se), df)
    return Estimate(diff, diff - q * se, diff + q * se, p)


def bootstrap_diff(y_t, y_c, rng, b=10_000) -> tuple[float, float]:
    """Percentile bootstrap CI for the difference in means."""
    y_t, y_c = y_t[~np.isnan(y_t)], y_c[~np.isnan(y_c)]
    it = rng.integers(0, len(y_t), (b, len(y_t)))
    ic = rng.integers(0, len(y_c), (b, len(y_c)))
    d = y_t[it].mean(1) - y_c[ic].mean(1)
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def permutation_p(y_t, y_c, rng, b=10_000) -> float:
    """Two-sided permutation test on the difference in means."""
    y_t, y_c = y_t[~np.isnan(y_t)], y_c[~np.isnan(y_c)]
    pooled = np.concatenate([y_t, y_c])
    obs = abs(y_t.mean() - y_c.mean())
    n = len(y_t)
    count = 0
    for _ in range(b):
        perm = rng.permutation(pooled)
        count += abs(perm[:n].mean() - perm[n:].mean()) >= obs
    return (count + 1) / (b + 1)


def mann_whitney_p(y_t, y_c) -> float:
    y_t, y_c = y_t[~np.isnan(y_t)], y_c[~np.isnan(y_c)]
    return float(stats.mannwhitneyu(y_t, y_c, alternative="two-sided").pvalue)


def cuped(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, float]:
    """CUPED adjustment: y - theta * (x - mean(x)), theta = cov(x, y) / var(x).

    x must be measured before treatment (here: the pre-period, when every SKU
    ran the control policy). Returns the adjusted values and theta.
    """
    ok = ~np.isnan(y) & ~np.isnan(x)
    theta = np.cov(x[ok], y[ok])[0, 1] / np.var(x[ok], ddof=1)
    adj = y - theta * (x - np.nanmean(x[ok]))
    return adj, float(theta)


def ratio_of_means_ci(v_t, v_c, rng, b=10_000) -> tuple[float, float, float]:
    """Treatment / control ratio of mean capital, with a bootstrap CI."""
    it = rng.integers(0, len(v_t), (b, len(v_t)))
    ic = rng.integers(0, len(v_c), (b, len(v_c)))
    r = v_t[it].mean(1) / v_c[ic].mean(1)
    return float(v_t.mean() / v_c.mean()), float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni adjusted p-values (controls the family-wise error)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def n_per_arm(sd: float, mde: float, alpha=0.05, power=0.8) -> int:
    """Two-sample normal approximation for the SKUs needed per arm."""
    za, zb = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    return int(np.ceil(2 * ((za + zb) * sd / mde) ** 2))
