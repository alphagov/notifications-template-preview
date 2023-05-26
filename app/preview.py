import base64
from io import BytesIO

import dateutil.parser
from flask import Blueprint, abort, current_app, jsonify, request, send_file
from flask_weasyprint import HTML
from notifications_utils.s3 import s3download
from notifications_utils.template import (
    LetterPreviewTemplate,
    LetterPrintTemplate,
)
from wand.color import Color
from wand.exceptions import MissingDelegateError
from wand.image import Image

from app import auth
from app.schemas import get_and_validate_json_from_request, preview_schema
from app.transformation import convert_pdf_to_cmyk

preview_blueprint = Blueprint("preview_blueprint", __name__)


# When the background is set to white traces of the Notify tag are visible in the preview png
# As modifying the pdf text is complicated, a quick solution is to place a white block over it
def hide_notify_tag(image):
    with Image(width=130, height=50, background=Color("white")) as cover:
        if image.colorspace == "cmyk":
            cover.transform_colorspace("cmyk")
        image.composite(cover, left=0, top=0)


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


def get_page_count(pdf_data):
    with Image(blob=pdf_data) as image:
        return len(image.sequence)


@preview_blueprint.route("/preview.json", methods=["POST"])
@auth.login_required
def page_count():
    json = get_and_validate_json_from_request(request, preview_schema)
    if json["template"].get("letter_attachment"):
        attachment_page_count = json["template"]["letter_attachment"]["page_count"]
    else:
        attachment_page_count = 0
    template_page_count = get_page_count(get_pdf(get_html(json)).read())
    total_page_count = template_page_count + attachment_page_count
    return jsonify({"count": total_page_count, "attachment_page_count": attachment_page_count})


def get_attachment_pdf(service_id, attachment_id) -> bytes:
    return s3download(
        current_app.config["LETTER_ATTACHMENT_BUCKET_NAME"],
        f"service-{service_id}/{attachment_id}.pdf",
    ).read()


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
        "filename": {"type": "string"}
    }
    """
    if filetype not in ("pdf", "png"):
        abort(404)

    if filetype == "pdf" and request.args.get("page") is not None:
        abort(400)

    json = get_and_validate_json_from_request(request, preview_schema)
    html = get_html(json)
    pdf = get_pdf(html)

    if filetype == "pdf":
        # TODO: handle attachments
        return send_file(
            path_or_file=pdf,
            mimetype="application/pdf",
        )
    elif filetype == "png":
        templated_letter_page_count = get_page_count(pdf)
        requested_page = int(request.args.get("page", 1))

        letter_attachment = json["template"].get("letter_attachment", {})

        if requested_page <= templated_letter_page_count:
            png_preview = get_png(
                html,
                requested_page,
            )
        elif letter_attachment and requested_page <= templated_letter_page_count + letter_attachment.get(
            "page_count", 0
        ):
            # get attachment page instead
            requested_attachment_page = requested_page - templated_letter_page_count
            attachment_pdf = get_attachment_pdf(json["template"]["service"], letter_attachment["id"])
            encoded_string = base64.b64encode(attachment_pdf)
            png_preview = get_png_from_precompiled(
                encoded_string=encoded_string,
                page_number=requested_attachment_page,
                hide_notify=False,
            )
        else:
            abort(400, f"Letter does not have a page {requested_page}")

        return send_file(
            path_or_file=png_preview,
            mimetype="image/png",
        )


def get_html(json):
    filename = f'{json["filename"]}.svg' if json["filename"] else None

    return str(
        LetterPreviewTemplate(
            json["template"],
            values=json["values"] or None,
            contact_block=json["letter_contact_block"],
            # letter assets are hosted on s3
            admin_base_url=current_app.config["LETTER_LOGO_URL"],
            logo_file_name=filename,
            date=dateutil.parser.parse(json["date"]) if json.get("date") else None,
        )
    )


def get_pdf(html):
    @current_app.cache(html, folder="templated", extension="pdf")
    def _get():
        return BytesIO(HTML(string=html).write_pdf())

    return _get()


def get_png(html, page_number):
    @current_app.cache(html, folder="templated", extension="page{0:02d}.png".format(page_number))
    def _get():
        return png_from_pdf(
            get_pdf(html).read(),
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
        current_app.logger.warning(f"Failed to generate PDF: {e}")
        abort(400)


@preview_blueprint.route("/print.pdf", methods=["POST"])
@auth.login_required
def print_letter_template():
    """
    POST /print.pdf with the following json blob
    {
        "letter_contact_block": "contact block for service, if any",
        "template": {
            "template data, as it comes out of the database"
        }
        "values": {"dict of placeholder values"},
        "filename": {"type": "string"}
    }
    """
    json = get_and_validate_json_from_request(request, preview_schema)
    filename = f'{json["filename"]}.svg' if json["filename"] else None

    template = LetterPrintTemplate(
        json["template"],
        values=json["values"] or None,
        contact_block=json["letter_contact_block"],
        # letter assets are hosted on s3
        admin_base_url=current_app.config["LETTER_LOGO_URL"],
        logo_file_name=filename,
    )
    html = HTML(string=str(template))
    pdf = BytesIO(html.write_pdf())

    cmyk_pdf = convert_pdf_to_cmyk(pdf)

    response = send_file(cmyk_pdf, as_attachment=True, download_name="print.pdf")
    response.headers["X-pdf-page-count"] = get_page_count(cmyk_pdf.read())
    cmyk_pdf.seek(0)
    return response
