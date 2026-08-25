from __future__ import annotations

import pytest

from django_fast_multipart._core import parse_options_header


def test_parses_value_and_parameters() -> None:
    value, parameters = parse_options_header(
        'form-data; name="upload"; filename="a\\"b.bin"; CHARSET=utf-8'
    )

    assert value == "form-data"
    assert parameters == {"name": "upload", "filename": 'a"b.bin', "charset": "utf-8"}


def test_parses_bare_value() -> None:
    assert parse_options_header("text/plain") == ("text/plain", {})


@pytest.mark.parametrize(
    ("header", "message"),
    [
        ("; charset=utf-8", "Missing header name"),
        ("text/plain; charset", "Missing parameter value"),
        ("text/plain; =utf-8", "Missing parameter key"),
        ('text/plain; charset="utf-8"junk', "Malformed quoted parameter"),
        ('text/plain; charset="utf-8\\', "Malformed quoted parameter"),
        ('text/plain; charset="utf-8', "Malformed quoted parameter"),
    ],
)
def test_rejects_malformed_headers(header: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_options_header(header)
