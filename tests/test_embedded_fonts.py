import logging
from io import BytesIO

import pytest
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from reportlab.lib.units import mm

from app.embedded_fonts import contains_unembedded_fonts, embed_fonts
from app.precompiled import _is_page_A4_portrait
from tests.pdf_consts import (
    blank_with_address,
    example_dwp_pdf,
    multi_page_pdf,
    portrait_rotated_page,
    valid_letter,
)


@pytest.mark.parametrize(
    ["pdf_file", "has_unembedded_fonts"],
    [
        (BytesIO(blank_with_address), False),
        (BytesIO(example_dwp_pdf), False),
        (BytesIO(multi_page_pdf), True),
        (BytesIO(valid_letter), False),
    ],
    ids=["blank_with_address", "example_dwp_pdf", "multi_page_pdf", "valid_letter"],
)
def test_contains_unembedded_fonts(client, pdf_file, has_unembedded_fonts):
    assert bool(contains_unembedded_fonts(pdf_file)) == has_unembedded_fonts


def test_embed_fonts():
    input_pdf = BytesIO(multi_page_pdf)
    assert contains_unembedded_fonts(input_pdf)

    new_pdf = embed_fonts(BytesIO(multi_page_pdf))

    assert not contains_unembedded_fonts(new_pdf)


def test_embed_fonts_does_not_rotate_pages():
    file_with_rotated_text = BytesIO(portrait_rotated_page)

    new_pdf = PdfReader(embed_fonts(file_with_rotated_text))
    page = new_pdf.pages[0]

    page_height = float(page.mediabox.height) / mm
    page_width = float(page.mediabox.width) / mm
    rotation = page.get("/Rotate")

    assert rotation is None
    assert _is_page_A4_portrait(page_height, page_width, rotation) is True


def test_contains_unembedded_fonts_logs_pdfreader_exception(app, mocker, caplog):
    mocker.patch("app.embedded_fonts.PdfReader", side_effect=PdfReadError("mock PdfReader exception"))

    dummy_pdf = BytesIO(b"fake-pdf-data")

    with caplog.at_level(logging.ERROR):
        with app.app_context():
            with pytest.raises(PdfReadError, match="mock PdfReader exception"):
                contains_unembedded_fonts(dummy_pdf, filename="corrupt.pdf")

    assert "PDF library error 'contains_unembedded_fonts': mock PdfReader exception" in caplog.text
