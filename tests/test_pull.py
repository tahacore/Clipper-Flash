from pathlib import Path

import pytest

from clipper_flash.pull import fmt_time, parse_time


def test_parse_plain_seconds() -> None:
    assert parse_time("90") == 90.0
    assert parse_time(125.5) == 125.5


def test_parse_mm_ss() -> None:
    assert parse_time("1:30") == 90.0
    assert parse_time("10:00") == 600.0


def test_parse_hh_mm_ss_with_fraction() -> None:
    assert parse_time("1:23:00.5") == pytest.approx(4980.5)


def test_parse_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_time("abc")
    with pytest.raises(ValueError):
        parse_time("1:2:3:4")


def test_fmt_time_roundtrip() -> None:
    assert fmt_time(4980.5) == "1:23:00.500"
    assert fmt_time(0) == "0:00:00.000"


def test_fmt_then_parse(tmp_path: Path) -> None:
    for t in (0.0, 61.5, 3661.25, 25200.0):
        assert parse_time(fmt_time(t)) == pytest.approx(t)
