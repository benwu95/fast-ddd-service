import sys
from collections.abc import Callable, Iterator

import pytest

from fast_ddd_port.preconditions import parse_etag, parse_if_match
from fast_ddd_port.problems import HttpProblem


@pytest.fixture
def bounded_integer_strings() -> Iterator[int]:
    original = sys.get_int_max_str_digits()
    limit = sys.int_info.default_max_str_digits
    sys.set_int_max_str_digits(limit)
    try:
        yield limit
    finally:
        sys.set_int_max_str_digits(original)


@pytest.mark.parametrize("parser", [parse_if_match, parse_etag])
def test_etag_integer_conversion_limit_is_an_invalid_precondition(
    parser: Callable[[str], int], bounded_integer_strings: int
) -> None:
    etag = '"' + "9" * (bounded_integer_strings + 1) + '"'

    with pytest.raises(HttpProblem) as caught:
        parser(etag)

    assert (caught.value.status, caught.value.code) == (400, "concurrency.invalid_if_match")


@pytest.mark.parametrize("parser", [parse_if_match, parse_etag])
@pytest.mark.parametrize("version", [0, 1, 2**63, 10**1000])
def test_etag_preserves_convertible_integer_versions(
    parser: Callable[[str], int], version: int
) -> None:
    assert parser(f'"{version}"') == version


@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_if_match_keeps_precondition_required(value: str | None) -> None:
    with pytest.raises(HttpProblem) as caught:
        parse_if_match(value)

    assert (caught.value.status, caught.value.code) == (428, "concurrency.precondition_required")


@pytest.mark.parametrize("parser", [parse_if_match, parse_etag])
@pytest.mark.parametrize("value", ["*", 'W/"1"', '"1", "2"', '"-1"', "1"])
def test_unsupported_etags_keep_invalid_precondition(
    parser: Callable[[str], int], value: str
) -> None:
    with pytest.raises(HttpProblem) as caught:
        parser(value)

    assert (caught.value.status, caught.value.code) == (400, "concurrency.invalid_if_match")
