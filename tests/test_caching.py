from unittest.mock import call

import pytest
from notifications_utils.s3 import S3ObjectNotFound

from app.utils import caching_s3download
from tests.conftest import s3_response_body


def test_cache_only_makes_1_call_to_s3(mocker):
    mock_s3download = mocker.patch("app.utils.s3download", return_value=s3_response_body())

    for _ in range(3):
        assert caching_s3download("foo", "bar").read() == b"\x00"  # Same bytes exactly

    assert mock_s3download.call_args_list == [
        call("foo", "bar"),
    ]


def test_cache_respects_different_keys(mocker):
    mock_s3download = mocker.patch(
        "app.utils.s3download",
        side_effect=[
            s3_response_body(b"a"),
            s3_response_body(b"b"),
            s3_response_body(b"c"),
        ],
    )

    for i, a in enumerate((b"a", b"b", b"c")):
        assert caching_s3download("foo", i).read() == a

    assert mock_s3download.call_args_list == [
        call("foo", 0),
        call("foo", 1),
        call("foo", 2),
    ]


def test_cache_respects_different_buckets(mocker):
    mock_s3download = mocker.patch(
        "app.utils.s3download",
        side_effect=[
            s3_response_body(b"foo"),
            s3_response_body(b"bar"),
            s3_response_body(b"baz"),
        ],
    )

    for bucket in ("foo", "bar", "baz"):
        assert caching_s3download(bucket, "same").read().decode() == bucket

    assert mock_s3download.call_args_list == [
        call("foo", "same"),
        call("bar", "same"),
        call("baz", "same"),
    ]


def test_cache_doesnt_cache_exceptions(mocker):
    mock_s3download = mocker.patch(
        "app.utils.s3download",
        side_effect=[
            S3ObjectNotFound({}, ""),
            S3ObjectNotFound({}, ""),
        ],
    )

    for _ in range(2):
        with pytest.raises(S3ObjectNotFound):
            caching_s3download("nope", "nope")

    assert mock_s3download.call_args_list == [
        call("nope", "nope"),
        call("nope", "nope"),
    ]
