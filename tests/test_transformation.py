import os
from io import BytesIO

import fitz
import pytest
from PIL import Image, ImageChops
from pypdf import PdfReader
from reportlab.lib.units import mm
from weasyprint import HTML

from app.precompiled import _is_page_A4_portrait
from app.transformation import (
    convert_pdf_to_cmyk,
    does_pdf_contain_cmyk,
    does_pdf_contain_rgb,
)
from tests.pdf_consts import (
    cmyk_and_rgb_images_in_one_pdf,
    cmyk_image_pdf,
    file,
    multi_page_pdf,
    portrait_rotated_page,
    public_guardian_sample,
    rgb_black_pdf,
    rgb_image_pdf,
)


@pytest.mark.parametrize(
    "pdf",
    [HTML(string="<html></html>").write_pdf(), multi_page_pdf],
    ids=["templated", "precompiled"],
)
def test_convert_pdf_to_cmyk_outputs_valid_pdf(pdf):
    data = convert_pdf_to_cmyk(BytesIO(pdf))
    assert data.read(9) == b"%PDF-1.7\n"


def test_subprocess_fails(client, mocker):
    mock_popen = mocker.patch("subprocess.Popen")
    mock_popen.return_value.returncode = 1
    mock_popen.return_value.communicate.return_value = ("Failed", "There was an error")

    with pytest.raises(Exception) as excinfo:
        html = HTML(string="<html></html>")
        pdf = BytesIO(html.write_pdf())
        convert_pdf_to_cmyk(pdf)
        assert "ghostscript process failed with return code: 1" in str(excinfo.value)


def test_subprocess_includes_output_error(client, mocker):
    mock_popen = mocker.patch("subprocess.Popen")
    mock_popen.return_value.returncode = 0
    mock_popen.return_value.communicate.return_value = (
        b"some pdf bytes\n\n"
        b"**** Error reading a content stream. The page may be incomplete.\n"
        b"               Output may be incorrect.\n\n"
        b"some more pdf bytes",
        "",
    )

    with pytest.raises(Exception) as excinfo:
        html = HTML(string="<html></html>")
        pdf = BytesIO(html.write_pdf())
        convert_pdf_to_cmyk(pdf)
        assert "ghostscript cmyk transformation failed to read all content streams" in str(excinfo.value)


def test_convert_pdf_to_cmyk_does_not_rotate_pages():
    file_with_rotated_text = BytesIO(portrait_rotated_page)

    transformed_pdf = PdfReader(convert_pdf_to_cmyk(file_with_rotated_text))
    page = transformed_pdf.pages[0]

    page_height = float(page.mediabox.height) / mm
    page_width = float(page.mediabox.width) / mm
    rotation = page.get("/Rotate")

    assert rotation is None
    assert _is_page_A4_portrait(page_height, page_width, rotation) is True


@pytest.mark.parametrize(
    "data",
    [
        cmyk_image_pdf,
        rgb_image_pdf,
        cmyk_and_rgb_images_in_one_pdf,
    ],
    ids=["cmyk_image_pdf", "rgb_image_pdf", "cmyk_and_rgb_images_in_one_pdf"],
)
def test_convert_pdf_to_cmyk(client, data):
    result = convert_pdf_to_cmyk(BytesIO(data))
    assert not does_pdf_contain_rgb(result)
    assert does_pdf_contain_cmyk(result)


def test_convert_pdf_to_cmyk_preserves_black(client):
    data = BytesIO(rgb_black_pdf)
    assert does_pdf_contain_rgb(data)
    assert not does_pdf_contain_cmyk(data)

    result = convert_pdf_to_cmyk(data)
    doc = fitz.open(stream=result, filetype="pdf")
    first_image = doc.get_page_images(pno=0)[0]
    image_object_number = first_image[0]
    pixmap = fitz.Pixmap(doc, image_object_number)

    assert "CMYK" in str(pixmap.colorspace)
    assert pixmap.pixel(100, 100) == (0, 0, 0, 255)  # (C,M,Y,K), where 'K' is black


# This hapened with a buggy version of GhostScript (9.21). You may see
# the 'stripped' images, depending on the viewer software - they still
# exist in the PDF. Comparing with the output from a fixed GhostScript
# version (9.53) shows the 'Matte' attribute is different between them,
# so that's what we look for here - it's unclear if it's actually the
# cause of the fault. At the very least, a failure of this test should
# prompt you to go and manually check the output still looks OK.
def test_convert_pdf_to_cmyk_does_not_strip_images():
    result = convert_pdf_to_cmyk(BytesIO(public_guardian_sample))
    first_page = PdfReader(result).pages[0]

    image_refs = first_page["/Resources"]["/XObject"].values()
    images = [image_ref.get_object() for image_ref in image_refs]
    assert not any("/Matte" in image for image in images)


@pytest.mark.parametrize(
    "data,result",
    [
        (cmyk_image_pdf, True),
        (rgb_image_pdf, False),
        (cmyk_and_rgb_images_in_one_pdf, True),
    ],
    ids=["cmyk_image_pdf", "rgb_image_pdf", "cmyk_and_rgb_images_in_one_pdf"],
)
def test_does_pdf_contain_cmyk(client, data, result):
    assert does_pdf_contain_cmyk(BytesIO(data)) == result


@pytest.mark.parametrize(
    "data,result",
    [
        (rgb_image_pdf, True),
        (cmyk_image_pdf, False),
        (cmyk_and_rgb_images_in_one_pdf, True),
    ],
)
def test_does_pdf_contain_rgb(client, data, result):
    assert does_pdf_contain_rgb(BytesIO(data)) == result


def detect_color_space(page):
    if does_pdf_contain_cmyk(page):  # CMYK images have 4 color channels
        return "CMYK"
    return "RGB"


def are_images_different(page1, page2):
    pix_map1 = page1.get_pixmap()
    pix_map2 = page2.get_pixmap()

    img1 = Image.frombytes("RGB", [pix_map1.width, pix_map1.height], pix_map1.samples)
    img2 = Image.frombytes("RGB", [pix_map2.width, pix_map2.height], pix_map2.samples)

    diff = ImageChops.difference(img1, img2)
    return not diff.getbbox()  # If there's no difference, returns True


@pytest.mark.skipif(os.environ.get("SKIP_TEST_CMYK_PDF", True), reason="CMYK PDF test is not enabled.")
def test_cmyk_pdf_transformation():
    input_files = "tests/test_pdfs/input_pdfs/"
    expected_files = "tests/test_pdfs/expected_pdfs/"
    test_output_files = "tests/test_pdfs/test_output_pdfs/"

    for filename in os.listdir(input_files):
        if filename.endswith(".pdf"):
            input_pdf = file(os.path.join(input_files, filename))
            expected_pdf = file(os.path.join(expected_files, filename))

            test_output_pdf = convert_pdf_to_cmyk(BytesIO(input_pdf))

            test_pdf_value = fitz.open("pdf", test_output_pdf.getvalue())
            expected_pdf_value = fitz.open("pdf", BytesIO(expected_pdf).getvalue())

            # Write file for visual checks
            f = open(f"{test_output_files}{filename}", "wb")
            f.write(test_output_pdf.getvalue())
            f.close()

            output_pdf_size = len(test_output_pdf.getvalue())
            expected_pdf_size = len(BytesIO(expected_pdf).getvalue())

            # Check file size
            assert output_pdf_size > 0, "Output PDF is empty!"
            assert (abs(output_pdf_size - expected_pdf_size) / expected_pdf_size) < float(
                os.environ.get("PROCESSED_PDF_SIZE_DIFFERENCE", 0.01)
            )

            for page1, page2 in zip(test_pdf_value, expected_pdf_value, strict=False):
                assert page1.get_text("text") == page2.get_text("text")

                # Compare images
                assert are_images_different(page1, page2)

                # Compare color spaces
            assert detect_color_space(test_output_pdf) == detect_color_space(BytesIO(expected_pdf))
