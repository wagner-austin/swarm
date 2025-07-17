"""
Test for filter_kwargs_for_method utility.
"""

from swarm.utils.dispatch import filter_kwargs_for_method


def dummy(a: int, b: int, c: int = 1, *, d: int | None = None) -> tuple[int, int, int, int | None]:
    return (a, b, c, d)


def test_filter_kwargs_for_method() -> None:
    kwargs = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
    filtered = filter_kwargs_for_method(dummy, kwargs)
    assert filtered == {"a": 1, "b": 2, "c": 3, "d": 4}
