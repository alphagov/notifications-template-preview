from io import BytesIO
import pytest

from app.embedded_fonts import contains_unembedded_fonts, remove_embedded_fonts

from tests.pdf_consts import blank_with_address, valid_letter, multi_page_pdf, example_dwp_pdf


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
