"""Synthetic SKU catalog for an OPME-like distributor.

Every number here is synthetic. The goal is a portfolio that behaves like
medical-device inventory: many slow, intermittent items, a few fast ones,
expensive units and lead times measured in days.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Catalog:
    p_demand: np.ndarray      # daily probability that the SKU has any demand
    size_mean: np.ndarray     # mean units per demand event
    size_cv: np.ndarray       # coefficient of variation of event size
    price: np.ndarray         # unit cost in BRL
    lead_time: np.ndarray     # supplier lead time in days (integer)
    abc: np.ndarray           # "A", "B" or "C" by annual consumption value
    pattern: np.ndarray       # Syntetos-Boylan class

    @property
    def n(self) -> int:
        return len(self.price)


def _syntetos_boylan(adi: np.ndarray, cv2: np.ndarray) -> np.ndarray:
    """Classify demand with the usual cut-offs ADI 1.32 and CV² 0.49."""
    out = np.empty(len(adi), dtype=object)
    out[(adi < 1.32) & (cv2 < 0.49)] = "smooth"
    out[(adi < 1.32) & (cv2 >= 0.49)] = "erratic"
    out[(adi >= 1.32) & (cv2 < 0.49)] = "intermittent"
    out[(adi >= 1.32) & (cv2 >= 0.49)] = "lumpy"
    return out


def make_catalog(n: int, rng: np.random.Generator) -> Catalog:
    # Demand frequency: most OPME items sell on a minority of days.
    p_demand = np.clip(rng.beta(1.2, 3.0, n), 0.03, 0.95)
    size_mean = 1 + rng.gamma(1.5, 1.2, n)
    size_cv = rng.uniform(0.2, 1.2, n)
    price = np.round(np.exp(rng.normal(np.log(1500), 1.0, n)), 2)
    lead_time = rng.integers(5, 21, n)

    # ABC on expected annual consumption value (80% / 95% cut-offs).
    value = p_demand * size_mean * price * 365
    order = np.argsort(-value)
    cum = np.cumsum(value[order]) / value.sum()
    abc_sorted = np.where(cum <= 0.80, "A", np.where(cum <= 0.95, "B", "C"))
    abc = np.empty(n, dtype=object)
    abc[order] = abc_sorted

    # Pattern from the generating parameters (ADI in days between demands).
    adi = 1 / p_demand
    cv2 = size_cv**2
    pattern = _syntetos_boylan(adi, cv2)
    return Catalog(p_demand, size_mean, size_cv, price, lead_time, abc, pattern)


def draw_demand(cat: Catalog, days: int, rng: np.random.Generator) -> np.ndarray:
    """Daily demand matrix (days × SKUs), integer units."""
    occurs = rng.random((days, cat.n)) < cat.p_demand
    shape = 1 / np.maximum(cat.size_cv**2, 1e-6)
    scale = cat.size_mean / shape
    size = rng.gamma(shape, scale, (days, cat.n))
    return np.where(occurs, np.maximum(1, np.round(size)), 0).astype(np.int64)
