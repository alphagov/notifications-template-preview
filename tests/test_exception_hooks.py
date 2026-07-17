import logging
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from pypdf.errors import PdfStreamError
from weasyprint import HTML

from app import InvalidRequest, configure_global_logging
from app.precompiled import does_pdf_contain_cmyk
from app.weasyprint_hack import WeasyprintError


class TestPDFLibraryErrors:
    def test_stitch_pdfs_error_is_caught_and_logged(self, mocker, client, auth_header, app):
        mock_logger = mocker.patch.object(app.logger, "warning")

        mocker.patch("app.utils.stitch_pdfs", side_effect=PdfStreamError("Stream has ended unexpectedly"))

        response = client.post(
            "/precompiled/sanitise",
            json={"file": "ZHVtbXk="},
            headers={"Content-type": "application/json", **auth_header},
        )
        assert response.status_code == 400

        assert mock_logger.call_count == 1
        assert "Validation failed for precompiled pdf" in str(mock_logger.call_args)
        assert "Stream has ended unexpectedly" in str(mock_logger.call_args)

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

    def test_configure_global_logging_attaches_handlers_and_sets_level(self, mocker, app):
        mock_root_logger = MagicMock()
        mock_root_logger.handlers = []
        mocker.patch("logging.getLogger", return_value=mock_root_logger)

        fake_kibana_handler = logging.NullHandler()
        app.logger.handlers = [fake_kibana_handler]

        configure_global_logging(app)
        mock_root_logger.addHandler.assert_called_once_with(fake_kibana_handler)
        mock_root_logger.setLevel.assert_called_once_with(logging.WARNING)

    def test_configure_global_logging_prevents_duplicate_handlers(self, mocker, app):
        fake_kibana_handler = logging.NullHandler()

        mock_root_logger = MagicMock()
        mock_root_logger.handlers = [fake_kibana_handler]
        mocker.patch("logging.getLogger", return_value=mock_root_logger)

        app.logger.handlers = [fake_kibana_handler]

        configure_global_logging(app)
        mock_root_logger.addHandler.assert_not_called()

    def test_weasyprint_svg_warning_is_routed_to_kibana(self, mocker, app):
        fake_kibana_handler = MagicMock()
        fake_kibana_handler.level = logging.NOTSET

        mocker.patch.object(app.logger, "handlers", [fake_kibana_handler])

        configure_global_logging(app)

        weasyprint_logger = logging.getLogger("weasyprint")
        weasyprint_logger.warning("Failed to render SVG image https://static-logos.../qr1.svg")

        assert fake_kibana_handler.handle.called

        log_record = fake_kibana_handler.handle.call_args[0][0]
        assert "Failed to render SVG image" in log_record.getMessage()
        assert log_record.levelno == logging.WARNING
