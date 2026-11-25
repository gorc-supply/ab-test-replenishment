"""Run the experiment end to end and write results/results.json.

Usage:  python -m abrep.experiment            (about a minute)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .catalog import draw_demand, make_catalog
from .simulate import simulate
from . import stats as st

SEED = 20261125
N_SKUS = 600
PRE_DAYS = 90
EXP_DAYS = 182            # about six months of the test
NI_MARGIN = 0.10          # guardrail: capital may rise at most 10%
MDE = 0.03                # smallest fill-rate gain worth acting on: 3 pp
AA_RUNS = 200

ROOT = Path(__file__).resolve().parents[2]


def assign(cat, rng) -> np.ndarray:
    """Randomize SKUs to arms, stratified by ABC class (half per stratum)."""
    treated = np.zeros(cat.n, dtype=bool)
    for c in ("A", "B", "C"):
        idx = np.flatnonzero(cat.abc == c)
        rng.shuffle(idx)
        treated[idx[: len(idx) // 2]] = True
    return treated


def aa_false_positive_rate(cat, rng) -> float:
    """A/A test: both arms run the control policy. The share of runs with
    p < 0.05 should sit near 5% if the pipeline is honest."""
    hits = 0
    for _ in range(AA_RUNS):
        dem = draw_demand(cat, PRE_DAYS + EXP_DAYS, rng)
        fake = assign(cat, rng)
        _, exp = simulate(cat, dem, np.zeros(cat.n, dtype=bool), PRE_DAYS)
        fr = exp.fill_rate
        hits += st.welch(fr[fake], fr[~fake]).p_value < 0.05
    return hits / AA_RUNS


def main() -> dict:
    rng = np.random.default_rng(SEED)
    cat = make_catalog(N_SKUS, rng)
    demand = draw_demand(cat, PRE_DAYS + EXP_DAYS, rng)
    treated = assign(cat, rng)
    pre, exp = simulate(cat, demand, treated, PRE_DAYS)

    fr, fr_pre = exp.fill_rate, pre.fill_rate
    t, c = treated, ~treated

    # Primary metric: SKU-level fill rate
    welch = st.welch(fr[t], fr[c])
    boot = st.bootstrap_diff(fr[t], fr[c], rng)
    perm = st.permutation_p(fr[t], fr[c], rng, b=5_000)
    mw = st.mann_whitney_p(fr[t], fr[c])

    # CUPED with the pre-period fill rate (same policy for everyone then)
    adj, theta = st.cuped(fr, fr_pre)
    welch_cuped = st.welch(adj[t], adj[c])
    var_raw = np.nanvar(fr[t]) + np.nanvar(fr[c])
    var_adj = np.nanvar(adj[t]) + np.nanvar(adj[c])

    # Guardrail: average capital tied up in stock
    ratio, r_lo, r_hi = st.ratio_of_means_ci(exp.avg_capital[t], exp.avg_capital[c], rng)

    # Secondary metrics, Holm-corrected
    sec = {
        "orders": st.welch(exp.orders[t], exp.orders[c]),
        "stockout_days": st.welch(exp.stockout_days[t], exp.stockout_days[c]),
    }
    holm = st.holm({k: v.p_value for k, v in sec.items()})

    # Units-weighted fill rate (what the business feels)
    unit_fr = {
        "control": float(exp.served[c].sum() / exp.demand[c].sum()),
        "treatment": float(exp.served[t].sum() / exp.demand[t].sum()),
    }

    # Heterogeneity by demand pattern
    by_pattern = {}
    for p in ("smooth", "erratic", "intermittent", "lumpy"):
        m = cat.pattern == p
        if (m & t).sum() > 5 and (m & c).sum() > 5:
            e = st.welch(fr[m & t], fr[m & c])
            by_pattern[p] = {
                "n_t": int((m & t).sum()), "n_c": int((m & c).sum()),
                "fill_t": float(np.nanmean(fr[m & t])), "fill_c": float(np.nanmean(fr[m & c])),
                "diff": e.diff, "ci": [e.ci_low, e.ci_high], "p": e.p_value,
            }

    by_abc = {}
    for k in ("A", "B", "C"):
        m = cat.abc == k
        e = st.welch(fr[m & t], fr[m & c])
        by_abc[k] = {"n_t": int((m & t).sum()), "n_c": int((m & c).sum()),
                     "fill_t": float(np.nanmean(fr[m & t])), "fill_c": float(np.nanmean(fr[m & c])),
                     "diff": e.diff, "ci": [e.ci_low, e.ci_high], "p": e.p_value,
                     "capital_ratio": float(exp.avg_capital[m & t].mean() / exp.avg_capital[m & c].mean())}

    sd = float(np.sqrt((np.nanvar(fr[c], ddof=1) + np.nanvar(fr[t], ddof=1)) / 2))
    sd_cuped = float(np.sqrt((np.nanvar(adj[c], ddof=1) + np.nanvar(adj[t], ddof=1)) / 2))

    aa = aa_false_positive_rate(cat, np.random.default_rng(SEED + 1))

    hist_edges = np.linspace(0, 1, 21)
    out = {
        "setup": {
            "seed": SEED, "skus": N_SKUS, "pre_days": PRE_DAYS, "exp_days": EXP_DAYS,
            "treated": int(t.sum()), "control": int(c.sum()),
            "abc": {k: int((cat.abc == k).sum()) for k in "ABC"},
            "patterns": {p: int((cat.pattern == p).sum()) for p in ("smooth", "erratic", "intermittent", "lumpy")},
            "mde_pp": MDE * 100, "ni_margin_pct": NI_MARGIN * 100,
        },
        "primary_fill_rate": {
            "control_mean": float(np.nanmean(fr[c])), "treatment_mean": float(np.nanmean(fr[t])),
            "diff": welch.diff, "welch_ci": [welch.ci_low, welch.ci_high], "welch_p": welch.p_value,
            "bootstrap_ci": list(boot), "permutation_p": perm, "mann_whitney_p": mw,
            "hist_edges": hist_edges.tolist(),
            "hist_control": np.histogram(fr[c][~np.isnan(fr[c])], hist_edges)[0].tolist(),
            "hist_treatment": np.histogram(fr[t][~np.isnan(fr[t])], hist_edges)[0].tolist(),
        },
        "cuped": {
            "theta": theta, "diff": welch_cuped.diff,
            "ci": [welch_cuped.ci_low, welch_cuped.ci_high], "p": welch_cuped.p_value,
            "variance_reduction_pct": float(100 * (1 - var_adj / var_raw)),
        },
        "guardrail_capital": {
            "control_mean_brl": float(exp.avg_capital[c].mean()),
            "treatment_mean_brl": float(exp.avg_capital[t].mean()),
            "ratio": ratio, "ci": [r_lo, r_hi],
            "non_inferior": bool(r_hi <= 1 + NI_MARGIN),
        },
        "secondary": {
            k: {"control": float(np.mean(getattr(exp, k)[c])), "treatment": float(np.mean(getattr(exp, k)[t])),
                "diff": v.diff, "ci": [v.ci_low, v.ci_high], "p": v.p_value, "p_holm": holm[k]}
            for k, v in sec.items()
        },
        "units_fill_rate": unit_fr,
        "by_pattern": by_pattern,
        "by_abc": by_abc,
        "power": {
            "sd_fill": sd, "sd_fill_cuped": sd_cuped,
            "n_per_arm_raw": st.n_per_arm(sd, MDE), "n_per_arm_cuped": st.n_per_arm(sd_cuped, MDE),
        },
        "aa_test": {"runs": AA_RUNS, "false_positive_rate": aa},
    }
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "results.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    r = main()
    print(json.dumps({k: r[k] for k in ("primary_fill_rate", "cuped", "guardrail_capital", "secondary", "units_fill_rate", "power", "aa_test")}, indent=1)[:4000])
