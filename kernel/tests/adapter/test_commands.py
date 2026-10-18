from fast_ddd_adapter.commands import UNSET, Unset, merge


def test_unset_is_a_falsy_singleton() -> None:
    assert Unset() is UNSET
    assert not UNSET
    assert repr(UNSET) == "UNSET"


def test_merge_keeps_current_value_only_when_unset() -> None:
    assert merge(UNSET, "current") == "current"
    assert merge("patched", "current") == "patched"
    assert merge(None, "current") is None
