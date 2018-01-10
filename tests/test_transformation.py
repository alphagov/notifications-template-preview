import pytest

from app.transformation import ColorMapping


@pytest.mark.parametrize('rgb_pdf_code, expected_cmyk_pdf_code', [
    (
        b'0.1 0.1 0.1 RG',
        b'0.0 0.0 0.0 1.0 K',
    ),
    (
        b'0.1 0.1 0.1 rg',
        b'0.0 0.0 0.0 1.0 k',
    ),
    (
        b'foo 0.1 0.1 0.1 RG bar',
        b'foo 0.0 0.0 0.0 1.0 K bar',
    ),
])
def test_colour_replacement(rgb_pdf_code, expected_cmyk_pdf_code):
    assert ColorMapping()(rgb_pdf_code) == expected_cmyk_pdf_code


@pytest.mark.parametrize('rgb, expected_cmyk', [
    # RGB black gets translated to 100% K
    (
        (0, 0, 0),
        [0, 0, 0, 1.00],
    ),
    # Dark gray also gets transformed to 100% K
    (
        (0.1, 0.1, 0.1),
        [0, 0, 0, 1.00],
    ),
    # Special case for ‘placeholder yellow’
    (
        (1.0, 0.7, 0.27),
        [0.0, 0.2, 1.0, 0.0],
    ),
    # Close to HMRC colour (but not exact) to exactly HMRC CMYK colour
    (
        (0.0, 0.6, 0.6),
        [0.83, 0.0, 0.4, 0.11],
    ),
])
def test_colour_mapping(rgb, expected_cmyk):
    assert ColorMapping().get_closest_cmyk_color(rgb) == expected_cmyk
