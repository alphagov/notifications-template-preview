from io import BytesIO
from unittest.mock import MagicMock

import fitz
import pytest
from pypdf.errors import PdfStreamError
from weasyprint import HTML

from app import InvalidRequest
from app.precompiled import does_pdf_contain_cmyk
from app.utils import stitch_pdfs
from app.weasyprint_hack import WeasyprintError


class TestPDFLibraryErrors:

    def test_stitch_pdfs_raises_pypdf_error_on_corrupted_file(self):
        corrupted_pdf_1 = BytesIO(b"Invalid PDF Data 1")
        corrupted_pdf_2 = BytesIO(b"Invalid PDF Data 2")

        with pytest.raises(PdfStreamError) as exc_info:
            stitch_pdfs(corrupted_pdf_1, corrupted_pdf_2)

        assert "Stream has ended unexpectedly" in str(exc_info.value)

    def test_pymupdf_raises_file_data_error_on_invalid_bytes(self):
        bad_pdf_bytes = b"<html>This is an HTML string, not a PDF</html>"

        with pytest.raises(fitz.FileDataError) as exc_info:
            fitz.open("pdf", bad_pdf_bytes)

        assert "failed to open stream" in str(exc_info.value).lower()

    def test_weasyprint_hack_raises_error_on_missing_assets(self):
        broken_html = "<!DOCTYPE html><html><body><img src='http://invalid.com/img.png'></body></html>"

        with pytest.raises(WeasyprintError) as exc_info:
            HTML(string=broken_html).write_pdf()

        assert "Failed to load image" in str(exc_info.value)

    def test_does_pdf_contain_cmyk_raises_invalid_request_on_corrupt_page(self, mocker, app):
        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 3

        def mock_get_page_images(page_index):
            if page_index == 1:
                raise RuntimeError("cannot load page")
            return []

        mock_doc.get_page_images.side_effect = mock_get_page_images

        mocker.patch("pymupdf.open", return_value=mock_doc)
        mock_logger = mocker.patch.object(app.logger, "warning")

        dummy_pdf_bytes = BytesIO(b"fake pdf content")

        with app.app_context():
            with pytest.raises(InvalidRequest) as exc_info:
                does_pdf_contain_cmyk(dummy_pdf_bytes)

        assert str(exc_info.value) == "Invalid PDF on page 2"

        mock_logger.assert_called_once_with(
            "PyMuPDF couldn't read page info for page %s",
            2,
            extra={"page_number": 2},
        )
