import base64
from io import BytesIO

import dateutil.parser
import sentry_sdk
from flask import Blueprint, abort, current_app, jsonify, request, send_file
from flask_weasyprint import HTML
from notifications_utils.template import (
    LetterPreviewTemplate,
)
from wand.color import Color
from wand.exceptions import MissingDelegateError
from wand.image import Image

from app import auth
from app.letter_attachments import add_attachment_to_letter, get_attachment_pdf
from app.schemas import get_and_validate_json_from_request, letter_attachment_preview_schema, preview_schema
from app.utils import stitch_pdfs

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
    with Image(blob=data, resolution=150) as pdf:
        pdf_width, pdf_height = pdf.width, pdf.height
        try:
            page = pdf.sequence[page_number - 1]
        except IndexError:
            abort(400, "Letter does not have a page {}".format(page_number))
        pdf_colorspace = pdf.colorspace
    return _generate_png_page(page, pdf_width, pdf_height, pdf_colorspace, hide_notify)


def _generate_png_page(pdf_page, pdf_width, pdf_height, pdf_colorspace, hide_notify=False):
    output = BytesIO()
    with Image(width=pdf_width, height=pdf_height) as image:
        if pdf_colorspace == "cmyk":
            image.transform_colorspace("cmyk")

        image.composite(pdf_page, top=0, left=0)
        if hide_notify:
            hide_notify_tag(image)
        with image.convert("png") as converted:
            converted.save(file=output)
    output.seek(0)
    return output


@sentry_sdk.trace
def get_page_count_for_pdf(pdf_data):
    with Image(blob=pdf_data) as image:
        return len(image.sequence)


def _preview_and_get_page_count(letter_json, language="english"):
    pdf = _get_pdf_from_letter_json(letter_json, language=language)

    return get_page_count_for_pdf(pdf.read())


@preview_blueprint.route("/preview.json", methods=["POST"])
@auth.login_required
def page_count():
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


@preview_blueprint.route("/preview.<filetype>", methods=["POST"])
@auth.login_required
def view_letter_template(filetype):
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
    if filetype not in ("pdf", "png"):
        abort(404)

    if filetype == "pdf" and request.args.get("page") is not None:
        abort(400)

    json = get_and_validate_json_from_request(request, preview_schema)

    if json["template"].get("letter_languages", None) == "welsh_then_english":
        english_pdf = _get_pdf_from_letter_json(json)
        welsh_pdf = _get_pdf_from_letter_json(json, language="welsh")
        pdf = stitch_pdfs(
            first_pdf=BytesIO(welsh_pdf.read()),
            second_pdf=BytesIO(english_pdf.read()),
        )
    else:
        pdf = _get_pdf_from_letter_json(json)

    letter_attachment = json["template"].get("letter_attachment", {})
    if letter_attachment:
        pdf = add_attachment_to_letter(
            service_id=json["template"]["service"], templated_letter_pdf=pdf, attachment_object=letter_attachment
        )

    if filetype == "pdf":
        return send_file(
            path_or_file=pdf,
            mimetype="application/pdf",
        )

    elif filetype == "png":
        # get pdf that can be read multiple times - unlike StreamingBody from boto that can only be read once
        requested_page = int(request.args.get("page", 1))
        return get_png_preview_for_pdf(pdf, page_number=requested_page)


def get_png_preview_for_pdf(pdf, page_number):
    pdf_persist = BytesIO(pdf) if isinstance(pdf, bytes) else BytesIO(pdf.read())
    templated_letter_page_count = get_page_count_for_pdf(pdf_persist)
    if page_number <= templated_letter_page_count:
        pdf_persist.seek(0)  # pdf was read to get page count, so we have to rewind it
        png_preview = get_png(
            pdf_persist,
            page_number,
        )
    else:
        abort(400, f"Letter does not have a page {page_number}")
    return send_file(
        path_or_file=png_preview,
        mimetype="image/png",
    )


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
        encoded_string = base64.b64encode(attachment_pdf)
        png_preview = get_png_from_precompiled(
            encoded_string=encoded_string,
            page_number=requested_page,
            hide_notify=False,
        )
    else:
        abort(400, f"Letter attachment does not have a page {requested_page}")

    return send_file(
        path_or_file=png_preview,
        mimetype="image/png",
    )


def _get_pdf_from_letter_json(letter_json, language="english"):
    html = get_html(letter_json, language=language)
    return get_pdf(html)


def get_html(json, language="english"):
    branding_filename = f'{json["filename"]}.svg' if json["filename"] else None

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
        )
    )


@sentry_sdk.trace
def get_pdf(html):
    @current_app.cache(html, folder="templated", extension="pdf")
    def _get():
        # Span description is a bit inexact, it's not *strictly* _just_ that function, but close enough
        with sentry_sdk.start_span(op="function", description="weasyprint.HTML.write_pdf"):
            return BytesIO(HTML(string=html).write_pdf())

    return _get()


def get_png(pdf, page_number):
    @current_app.cache(pdf.read(), folder="templated", extension="page{0:02d}.png".format(page_number))
    def _get():
        pdf.seek(0)
        return png_from_pdf(
            pdf,
            page_number=page_number,
        )

    return _get()


def get_png_from_precompiled(encoded_string: bytes, page_number, hide_notify):
    @current_app.cache(
        encoded_string.decode("ascii"),
        hide_notify,
        folder="precompiled",
        extension="page{0:02d}.png".format(page_number),
    )
    def _get():
        return png_from_pdf(
            base64.decodebytes(encoded_string),
            page_number=page_number,
            hide_notify=hide_notify,
        )

    return _get()


@preview_blueprint.route("/precompiled-preview.png", methods=["POST"])
@auth.login_required
def view_precompiled_letter():
    try:
        encoded_string = request.get_data()

        if not encoded_string:
            abort(400)

        return send_file(
            path_or_file=get_png_from_precompiled(
                encoded_string,
                int(request.args.get("page", 1)),
                hide_notify=request.args.get("hide_notify", "") == "true",
            ),
            mimetype="image/png",
        )

    # catch invalid pdfs
    except MissingDelegateError as e:
        current_app.logger.warning("Failed to generate PDF: %s", e)
        abort(400)
