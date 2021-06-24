from io import BytesIO

import pytest
from PyPDF2 import PdfFileReader
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


@pytest.mark.parametrize(['pdf_file', 'has_unembedded_fonts'], [
    (BytesIO(blank_with_address), False),
    (BytesIO(example_dwp_pdf), False),
    (BytesIO(multi_page_pdf), True),
    (BytesIO(valid_letter), False)
], ids=['blank_with_address', 'example_dwp_pdf', 'multi_page_pdf', 'valid_letter'])
def test_contains_unembedded_fonts(client, pdf_file, has_unembedded_fonts):
    assert bool(contains_unembedded_fonts(pdf_file)) == has_unembedded_fonts


def test_embed_fonts():
    input_pdf = BytesIO(multi_page_pdf)
    assert contains_unembedded_fonts(input_pdf)

    new_pdf = embed_fonts(BytesIO(multi_page_pdf))

    assert not contains_unembedded_fonts(new_pdf)


def test_embed_fonts_does_not_rotate_pages():
    file_with_rotated_text = BytesIO(portrait_rotated_page)

    new_pdf = PdfFileReader(
        embed_fonts(file_with_rotated_text)
    )
    page = new_pdf.getPage(0)

    page_height = float(page.mediaBox.getHeight()) / mm
    page_width = float(page.mediaBox.getWidth()) / mm
    rotation = page.get('/Rotate')

    assert rotation is None
    assert _is_page_A4_portrait(page_height, page_width, rotation) is True
