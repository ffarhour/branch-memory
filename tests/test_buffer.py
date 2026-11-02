import math

import pytest

from branch_memory.buffer import Buffer, context_cap, decayed_weight


def test_weight_is_one_when_added_and_exp_after():
    assert decayed_weight(0, 3.0) == 1.0
    assert decayed_weight(3, 3.0) == pytest.approx(math.exp(-1))


def test_b_decays_and_drops_below_floor():
    buffer = Buffer("B", tau=1.0, k=2)
    buffer.update(1, ["old"])
    buffer.update(3, ["new"])
    weights = {m.text: m.weight for m in buffer.moves}
    assert weights["old"] == pytest.approx(math.exp(-2))
    assert weights["new"] == 1.0
    buffer.update(4, [])  # age 3: exp(-3) = 0.0498, just under the floor
    assert [m.text for m in buffer.moves] == ["new"]


def test_c_keeps_weight_and_evicts_oldest_at_cap():
    buffer = Buffer("C", tau=1.0, k=2)
    assert buffer.cap == 3
    for scene in range(1, 6):
        buffer.update(scene, [f"move{scene}"])
    assert [m.text for m in buffer.moves] == ["move3", "move4", "move5"]
    assert all(m.weight == 1.0 for m in buffer.moves)


def test_a_has_no_buffer():
    with pytest.raises(ValueError):
        Buffer("A", tau=1.0, k=2)


@pytest.mark.parametrize(
    "k,tau,expected", [(4, 3.0, 27), (4, 1.0, 9), (4, 0.5, 6), (2, 1.0, 3), (5, 2.0, 24)]
)
def test_context_cap_formula(k, tau, expected):
    assert context_cap(k, tau) == expected


@pytest.mark.parametrize("tau", [0.5, 1.0, 2.0, 3.0, 5.5])
def test_cap_matches_longest_size_b_reaches(tau):
    k = 4
    buffer = Buffer("B", tau=tau, k=k)
    sizes = []
    for scene in range(1, 80):
        buffer.update(scene, [f"{scene}-{i}" for i in range(k - 1)])
        sizes.append(len(buffer.moves))
    assert max(sizes) <= context_cap(k, tau)
    assert max(sizes) >= context_cap(k, tau) - (k - 1)


def test_render_lists_weights_strongest_first():
    buffer = Buffer("B", tau=1.0, k=2)
    buffer.update(1, ["the bridge is down"])
    buffer.update(2, ["the courier lied"])
    assert buffer.render().splitlines() == [
        "Unused directions still in the air (weight):",
        "- [1.00] the courier lied",
        "- [0.37] the bridge is down",
    ]


def test_snapshot_does_not_change_when_buffer_decays():
    buffer = Buffer("B", tau=1.0, k=2)
    buffer.update(1, ["x"])
    snapshot = buffer.snapshot()
    buffer.update(2, [])
    assert snapshot[0].weight == 1.0
