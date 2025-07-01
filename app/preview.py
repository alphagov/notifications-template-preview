import base64
import pickle
from io import BytesIO

import dateutil.parser
import sentry_sdk
from flask import Blueprint, abort, current_app, jsonify, request, send_file
from flask_weasyprint import HTML
from notifications_utils.template import (
    LetterPreviewTemplate,
)
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from wand.color import Color
from wand.exceptions import MissingDelegateError
from wand.image import Image

from app import auth
from app.letter_attachments import get_attachment_pdf
from app.schemas import get_and_validate_json_from_request, letter_attachment_preview_schema, preview_schema
from app.templated import generate_templated_pdf
from app.utils import PDFPurpose

preview_blueprint = Blueprint("preview_blueprint", __name__)


# When the background is set to white traces of the Notify tag are visible in the preview png
# As modifying the pdf text is complicated, a quick solution is to place a white block over it
def hide_notify_tag(image):
    with Image(width=130, height=50, background=Color("white")) as cover:
        if image.colorspace == "cmyk":
            cover.transform_colorspace("cmyk")
        image.composite(cover, left=0, top=0)


@sentry_sdk.trace
def png_from_pdf(data, page_number, hide_notify=False):
    try:
        page = PdfReader(data).pages[page_number - 1]
    except IndexError:
        abort(400, f"Letter does not have a page {page_number}")
    except PdfReadError:
        abort(400, "Could not read PDF")

    serialised_page = pickle.dumps(page)

    @current_app.cache(serialised_page, hide_notify, folder="pngs", extension="png")
    def _generate():
        output = BytesIO()
        new_pdf = BytesIO()
        writer = PdfWriter()
        writer.add_page(pickle.loads(serialised_page))
        writer.write(new_pdf)
        new_pdf.seek(0)

        with Image(blob=new_pdf, resolution=150) as rasterized_pdf:
            if hide_notify:
                hide_notify_tag(rasterized_pdf)
            with rasterized_pdf.convert("png") as converted:
                converted.save(file=output)
        output.seek(0)
        return output

    return _generate()


@sentry_sdk.trace
def get_page_count_for_pdf(pdf_data):
    reader = PdfReader(BytesIO(pdf_data))
    return len(reader.pages)


def _preview_and_get_page_count(letter_json, language="english"):
    pdf = _get_pdf_from_letter_json(letter_json, language=language)

    return get_page_count_for_pdf(pdf.read())


@preview_blueprint.route("/preview.json", methods=["POST"])
@preview_blueprint.route("/get-page-count", methods=["POST"])
@auth.login_required
def page_count():
    # This endpoint is called from all_page_counts in admin and is cached there.
    json = get_and_validate_json_from_request(request, preview_schema)

    counts = {
        "count": 0,
        "welsh_page_count": 0,
        "attachment_page_count": 0,
    }

    if json["template"].get("letter_attachment"):
        counts["attachment_page_count"] = json["template"]["letter_attachment"]["page_count"]

    if json["template"].get("letter_languages", None) == "welsh_then_english":
        counts["welsh_page_count"] = _preview_and_get_page_count(json, language="welsh")

    english_pages_count = _preview_and_get_page_count(json)
    counts["count"] = english_pages_count + counts["welsh_page_count"] + counts["attachment_page_count"]

    return jsonify(counts)


@preview_blueprint.route("/preview.png", methods=["POST"])
@auth.login_required
def view_letter_template_png():
    json = get_and_validate_json_from_request(request, preview_schema)
    pdf = prepare_pdf(json)
    # get pdf that can be read multiple times - unlike StreamingBody from boto that can only be read once
    requested_page = int(request.args.get("page", 1))
    pdf_persist = BytesIO(pdf) if isinstance(pdf, bytes) else BytesIO(pdf.read())
    png_preview = png_from_pdf(
        pdf_persist,
        requested_page,
    )
    return send_file(
        path_or_file=png_preview,
        mimetype="image/png",
    )


@preview_blueprint.route("/preview.pdf", methods=["POST"])
@auth.login_required
def view_letter_template_pdf():
    """
    POST /preview.pdf with the following json blob
    {
        "letter_contact_block": "contact block for service, if any",
        "template": {
            "template data, as it comes out of the database"
        },
        "values": {"dict of placeholder values"},
        "filename": {"type": "string"}  # letter branding file name
    }

    the data returned is a preview pdf/png, including fake MDI/QR code/barcode (and with no NOTIFY tag)
    """
    if request.args.get("page") is not None:
        abort(400)

    json = get_and_validate_json_from_request(request, preview_schema)

    pdf = prepare_pdf(json)

    return send_file(
        path_or_file=pdf,
        mimetype="application/pdf",
    )


def prepare_pdf(letter_details):
    def create_pdf_for_letter(letter_details, language, includes_first_page=True) -> BytesIO:
        return _get_pdf_from_letter_json(letter_details, language=language, includes_first_page=includes_first_page)

    purpose = PDFPurpose.PREVIEW

    return generate_templated_pdf(letter_details, create_pdf_for_letter, purpose)


@preview_blueprint.route("/letter_attachment_preview.png", methods=["POST"])
@auth.login_required
def view_letter_attachment_preview():
    """
    POST /letter_attachment_preview.png?page=X with the following json blob
    {
        "letter_attachment_id": "attachment id",
        "service_id": "service id",
    }
    """

    if request.args.get("page") is None:
        abort(400)

    json = get_and_validate_json_from_request(request, letter_attachment_preview_schema)
    requested_page = int(request.args.get("page", 1))
    attachment_pdf = get_attachment_pdf(json["service_id"], json["letter_attachment_id"])
    attachment_page_count = get_page_count_for_pdf(attachment_pdf)

    if requested_page <= attachment_page_count:
        png_preview = png_from_pdf(
            BytesIO(attachment_pdf),
            page_number=requested_page,
            hide_notify=False,
        )
    else:
        abort(400, f"Letter attachment does not have a page {requested_page}")

    return send_file(
        path_or_file=png_preview,
        mimetype="image/png",
    )


def _get_pdf_from_letter_json(letter_json, language="english", includes_first_page=True) -> BytesIO:
    html = get_html(letter_json, language=language, includes_first_page=includes_first_page)
    return get_pdf(html)


def get_html(json, language="english", includes_first_page=True):
    branding_filename = f"{json['filename']}.svg" if json["filename"] else None

    return str(
        LetterPreviewTemplate(
            json["template"],
            values=json["values"] or None,
            contact_block=json["letter_contact_block"],
            # letter assets are hosted on s3
            admin_base_url=current_app.config["LETTER_LOGO_URL"],
            logo_file_name=branding_filename,
            date=dateutil.parser.parse(json["date"]) if json.get("date") else None,
            language=language,
            includes_first_page=includes_first_page,
        )
    )


@sentry_sdk.trace
def get_pdf(html) -> BytesIO:
    @current_app.cache(html, folder="templated", extension="pdf")
    def _get():
        # Span description is a bit inexact, it's not *strictly* _just_ that function, but close enough
        with sentry_sdk.start_span(op="function", description="weasyprint.HTML.write_pdf"):
            return BytesIO(HTML(string=html).write_pdf())

    return _get()


@preview_blueprint.route("/precompiled-preview.png", methods=["POST"])
@auth.login_required
def view_precompiled_letter():
    try:
        encoded_string = request.get_data()

        if not encoded_string:
            abort(400)

        return send_file(
            path_or_file=png_from_pdf(
                BytesIO(base64.decodebytes(encoded_string)),
                page_number=int(request.args.get("page", 1)),
                hide_notify=request.args.get("hide_notify", "") == "true",
            ),
            mimetype="image/png",
        )

    # catch invalid pdfs
    except MissingDelegateError as e:
        current_app.logger.warning("Failed to generate PDF: %s", e)
        abort(400)
