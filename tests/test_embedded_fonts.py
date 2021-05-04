from io import BytesIO

import pytest
from PyPDF2 import PdfFileReader
from reportlab.lib.units import mm

from app.embedded_fonts import contains_unembedded_fonts, remove_embedded_fonts
from app.precompiled import _is_page_A4_portrait
from tests.pdf_consts import (
    blank_with_address,
    duplicate_embedded_fonts,
    example_dwp_pdf,
    multi_page_pdf,
    portrait_rotated_page,
    valid_letter,
)


@pytest.mark.parametrize(['pdf_file', 'has_unembedded_fonts'], [
    (BytesIO(blank_with_address), True),  # false positive, I think, or maybe because created through Google sheets?
    (BytesIO(example_dwp_pdf), False),
    (BytesIO(multi_page_pdf), True),
    (BytesIO(valid_letter), True),   # false positive, I think, or maybe because created through Google sheets?
], ids=['blank_with_address', 'example_dwp_pdf', 'multi_page_pdf', 'valid_letter'])
def test_contains_unembedded_fonts(pdf_file, has_unembedded_fonts):
    assert bool(contains_unembedded_fonts(pdf_file)) == has_unembedded_fonts


def test_remove_embedded_fonts():
    input_pdf = BytesIO(multi_page_pdf)
    assert contains_unembedded_fonts(input_pdf)

    new_pdf = remove_embedded_fonts(BytesIO(multi_page_pdf))

    assert not contains_unembedded_fonts(new_pdf)


def list_embedded_fonts(pdf_file):
    def walk(pdf_file, embedded_fonts):
        if hasattr(pdf_file, 'keys'):
            fontkeys = {'/FontFile', '/FontFile2', '/FontFile3'}
            if '/FontName' in pdf_file:
                if any(x in pdf_file for x in fontkeys):
                    embedded_fonts.add(pdf_file['/FontName'])

            for key in pdf_file.keys():
                walk(pdf_file[key], embedded_fonts)

    pdf = PdfFileReader(pdf_file)
    embedded = set()
    for page in pdf.pages:
        obj = page.getObject()
        walk(obj['/Resources'], embedded)

    pdf_file.seek(0)
    return list(embedded)


def test_remove_embedded_fonts_removes_font_subsets_to_avoid_duplicate_fonts():
    input_pdf = BytesIO(duplicate_embedded_fonts)
    list_of_fonts_without_subsets = ['/Arial-BoldMT', '/ArialMT']
    assert len(list_embedded_fonts(input_pdf)) > 2

    new_pdf = remove_embedded_fonts(BytesIO(duplicate_embedded_fonts))
    assert list_embedded_fonts(new_pdf) == list_of_fonts_without_subsets


def test_remove_embedded_fonts_does_not_rotate_pages():
    file_with_rotated_text = BytesIO(portrait_rotated_page)

    new_pdf = PdfFileReader(
        remove_embedded_fonts(file_with_rotated_text)
    )
    page = new_pdf.getPage(0)

    page_height = float(page.mediaBox.getHeight()) / mm
    page_width = float(page.mediaBox.getWidth()) / mm
    rotation = page.get('/Rotate')

    assert rotation is None
    assert _is_page_A4_portrait(page_height, page_width, rotation) is True
