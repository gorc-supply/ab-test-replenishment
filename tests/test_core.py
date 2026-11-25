import numpy as np

from abrep.catalog import draw_demand, make_catalog
from abrep.simulate import simulate
from abrep import stats as st


def _run(treated_share=0.5, seed=1, n=120):
    rng = np.random.default_rng(seed)
    cat = make_catalog(n, rng)
    dem = draw_demand(cat, 150, rng)
    treated = rng.random(n) < treated_share
    return cat, dem, treated, *simulate(cat, dem, treated, pre_days=60)


def test_served_never_exceeds_demand():
    _, dem, _, pre, exp = _run()
    assert (exp.served <= exp.demand + 1e-9).all()
    assert (exp.served >= 0).all()
    fr = exp.fill_rate[~np.isnan(exp.fill_rate)]
    assert ((fr >= 0) & (fr <= 1)).all()


def test_simulation_is_deterministic_for_a_seed():
    a = _run(seed=7)[4].served
    b = _run(seed=7)[4].served
    assert np.array_equal(a, b)


def test_no_treatment_means_same_policy_everywhere():
    cat, dem, _, _, _ = _run()
    none = np.zeros(cat.n, dtype=bool)
    _, e1 = simulate(cat, dem, none, 60)
    _, e2 = simulate(cat, dem, none, 60)
    assert np.array_equal(e1.orders, e2.orders)


def test_holm_matches_hand_calculation():
    adj = st.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert np.isclose(adj["a"], 0.03)
    assert np.isclose(adj["c"], 0.06)
    assert np.isclose(adj["b"], 0.06)


def test_cuped_reduces_variance_with_correlated_covariate():
    rng = np.random.default_rng(3)
    x = rng.normal(0, 1, 2000)
    y = 0.8 * x + rng.normal(0, 0.5, 2000)
    adj, theta = st.cuped(y, x)
    assert 0.7 < theta < 0.9
    assert adj.var() < 0.5 * y.var()


def test_sample_size_formula():
    assert st.n_per_arm(sd=0.1, mde=0.03) == 175


def test_welch_finds_no_difference_on_identical_data():
    rng = np.random.default_rng(5)
    a = rng.normal(0.9, 0.05, 400)
    e = st.welch(a, a.copy())
    assert abs(e.diff) < 1e-12 and e.p_value > 0.99
