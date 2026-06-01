"""OrderedEventList-1b: shared event-date parser regression tests.

The dataset uses `YYYY/MM/DD (Dow) HH:MM`; the old list_ordering parser
silently failed on that shape and made the registered skill dead on its
intended cohort. event_interval carried the same copied parser.
"""
from __future__ import annotations

from datetime import datetime

from radiomind.skills.date_utils import parse_event_date
from radiomind.skills import event_interval, list_ordering


def test_parse_longmemeval_slash_weekday_time():
    assert parse_event_date("2022/10/20 (Thu) 00:52") == datetime(2022, 10, 20)


def test_parse_common_shapes():
    assert parse_event_date("2022/12/19") == datetime(2022, 12, 19)
    assert parse_event_date("2022-12-19") == datetime(2022, 12, 19)
    assert parse_event_date("March 5, 2023") == datetime(2023, 3, 5)
    assert parse_event_date("Mar 5, 2023") == datetime(2023, 3, 5)


def test_invalid_dates_return_none():
    assert parse_event_date("2022/99/19 (Mon) 19:53") is None
    assert parse_event_date("not a date") is None


def test_list_ordering_parser_uses_shared_fix():
    assert list_ordering._parse_date("2022/12/19 (Mon) 19:53") == (
        datetime(2022, 12, 19)
    )


def test_event_interval_parser_uses_shared_fix():
    assert event_interval._parse_date("2022/12/19 (Mon) 19:53") == (
        datetime(2022, 12, 19)
    )
