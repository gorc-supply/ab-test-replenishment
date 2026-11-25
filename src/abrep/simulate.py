"""Day-by-day inventory simulation with two replenishment policies.

Control   (A): min-max rule, continuous review. When the inventory position
               falls to the minimum, order up to twice the minimum. The
               minimum is set once from the pre-period, the way many
               distributors still do it.
Treatment (B): forecast-based order-up-to, weekly review. Croston-SBA rate
               and an exponentially weighted demand variance are updated
               every day; at each review the order brings the inventory
               position to mu * (L + R) + z * sigma * sqrt(L + R), with the
               service level set by ABC class.

Unmet demand is lost (no backorders). Orders arrive after the SKU lead time.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .catalog import Catalog

Z = {"A": 1.6449, "B": 1.6449, "C": 1.2816}  # 95%, 95%, 90%
REVIEW_DAYS = 7
SBA_ALPHA = 0.1
VAR_ALPHA = 0.05


@dataclass
class Metrics:
    demand: np.ndarray
    served: np.ndarray
    avg_capital: np.ndarray
    orders: np.ndarray
    stockout_days: np.ndarray

    @property
    def fill_rate(self) -> np.ndarray:
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(self.demand > 0, self.served / self.demand, np.nan)


def _window(on_hand_value, demand, served, orders, stockout, lo, hi) -> Metrics:
    return Metrics(
        demand=demand[lo:hi].sum(0).astype(float),
        served=served[lo:hi].sum(0).astype(float),
        avg_capital=on_hand_value[lo:hi].mean(0),
        orders=orders[lo:hi].sum(0).astype(float),
        stockout_days=stockout[lo:hi].sum(0).astype(float),
    )


def simulate(cat: Catalog, demand: np.ndarray, treated: np.ndarray, pre_days: int, burn_in: int = 30):
    """Run the whole horizon. Returns (pre-period metrics, experiment metrics).

    During the pre-period every SKU runs the control policy, so pre-period
    metrics are a clean covariate for CUPED. The first `burn_in` days are
    left out of the pre-period metrics because every SKU starts full.
    """
    days, n = demand.shape
    lt = cat.lead_time
    z = np.array([Z[c] for c in cat.abc])

    # Control parameters from the pre-period average (rule of thumb: 1.5x
    # lead-time demand, at least one unit).
    pre_rate = demand[:pre_days].mean(0)
    min_q = np.maximum(1, np.ceil(pre_rate * lt * 1.5))
    max_q = 2 * min_q

    on_hand = max_q.astype(float).copy()
    pipeline = np.zeros((days + lt.max() + 1, n))
    on_order = np.zeros(n)
    # Croston-SBA state
    z_size = np.where(pre_rate > 0, cat.size_mean, 1.0)
    p_int = 1 / np.maximum(cat.p_demand, 1e-3)
    since = np.ones(n)
    mean_d = pre_rate.copy()
    var_d = demand[:pre_days].var(0) + 1e-6

    served = np.zeros((days, n))
    orders = np.zeros((days, n))
    stockout = np.zeros((days, n))
    value = np.zeros((days, n))
    cols = np.arange(n)

    for t in range(days):
        on_hand += pipeline[t]
        on_order -= pipeline[t]
        d = demand[t]
        s = np.minimum(on_hand, d)
        on_hand -= s
        served[t] = s
        stockout[t] = d > s

        # Update the forecast state with today's demand (used only by B, but
        # kept for every SKU so the arms are symmetric).
        occ = d > 0
        z_size = np.where(occ, z_size + SBA_ALPHA * (d - z_size), z_size)
        p_int = np.where(occ, p_int + SBA_ALPHA * (since - p_int), p_int)
        since = np.where(occ, 1, since + 1)
        rate = (1 - SBA_ALPHA / 2) * z_size / np.maximum(p_int, 1.0)
        err = d - mean_d
        var_d = (1 - VAR_ALPHA) * var_d + VAR_ALPHA * err**2
        mean_d = rate

        position = on_hand + on_order
        use_b = treated & (t >= pre_days)

        # A: continuous review min-max
        need_a = (~use_b) & (position <= min_q)
        qty_a = np.where(need_a, max_q - position, 0.0)

        # B: weekly review order-up-to
        review = use_b & ((t - pre_days) % REVIEW_DAYS == 0)
        prot = lt + REVIEW_DAYS
        target = mean_d * prot + z * np.sqrt(var_d * prot)
        qty_b = np.where(review, np.maximum(0.0, np.ceil(target - position)), 0.0)

        qty = np.ceil(qty_a + qty_b)
        placed = qty > 0
        orders[t] = placed
        pipeline[t + lt[placed], cols[placed]] += qty[placed]
        on_order += qty
        value[t] = on_hand * cat.price

    pre = _window(value, demand, served, orders, stockout, burn_in, pre_days)
    exp = _window(value, demand, served, orders, stockout, pre_days, days)
    return pre, exp
