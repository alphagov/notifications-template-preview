import base64
import dateutil.parser
from io import BytesIO

from PyPDF2 import PdfFileReader
from flask import Blueprint, request, send_file, abort, current_app, jsonify
from flask_weasyprint import HTML
from notifications_utils.statsd_decorators import statsd
from wand.image import Image
from wand.color import Color
from wand.exceptions import MissingDelegateError
from notifications_utils.template import (
    LetterPreviewTemplate,
    LetterPrintTemplate,
)

from app import auth
from app.schemas import get_and_validate_json_from_request, preview_schema
from app.transformation import convert_pdf_to_cmyk

preview_blueprint = Blueprint('preview_blueprint', __name__)


# When the background is set to white traces of the Notify tag are visible in the preview png
# As modifying the pdf text is complicated, a quick solution is to place a white block over it
def hide_notify_tag(image):
    with Image(width=130, height=50, background=Color('white')) as cover:
        if image.colorspace == 'cmyk':
            cover.transform_colorspace('cmyk')
        image.composite(cover, left=0, top=0)


@statsd(namespace="template_preview")
def png_from_pdf(data, page_number, hide_notify=False):
    output = BytesIO()
    with Image(blob=data, resolution=150) as pdf:
        with Image(width=pdf.width, height=pdf.height) as image:
            try:
                page = pdf.sequence[page_number - 1]
            except IndexError:
                abort(400, 'Letter does not have a page {}'.format(page_number))

            if pdf.colorspace == 'cmyk':
                image.transform_colorspace('cmyk')

            image.composite(page, top=0, left=0)
            if hide_notify:
                hide_notify_tag(image)
            converted = image.convert('png')
            converted.save(file=output)

    output.seek(0)
    return output


@statsd(namespace="template_preview")
def get_logo(dvla_org_id):
    try:
        return current_app.config['LOGOS'][dvla_org_id]
    except KeyError:
        abort(400)


@statsd(namespace="template_preview")
def get_page_count(pdf_data):
    with Image(blob=pdf_data) as image:
        return len(image.sequence)


@preview_blueprint.route("/preview.json", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def page_count():
    json = get_and_validate_json_from_request(request, preview_schema)
    return jsonify(
        {
            'count': get_page_count(get_pdf(get_html(json)).read())
        }
    )


@preview_blueprint.route("/preview.<filetype>", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def view_letter_template(filetype):
    """
    POST /preview.pdf with the following json blob
    {
        "letter_contact_block": "contact block for service, if any",
        "template": {
            "template data, as it comes out of the database"
        },
        "values": {"dict of placeholder values"},
        "dvla_org_id": {"type": "string"}
    }
    """
    try:
        if filetype not in ('pdf', 'png'):
            abort(404)

        if filetype == 'pdf' and request.args.get('page') is not None:
            abort(400)

        html = get_html(
            get_and_validate_json_from_request(request, preview_schema)
        )

        if filetype == 'pdf':
            return send_file(
                filename_or_fp=get_pdf(html),
                mimetype='application/pdf',
            )
        elif filetype == 'png':
            return send_file(
                filename_or_fp=get_png(
                    html,
                    int(request.args.get('page', 1)),
                ),
                mimetype='image/png',
            )

    except Exception as e:
        current_app.logger.error(str(e))
        raise e


def get_html(json):
    return str(LetterPreviewTemplate(
        json['template'],
        values=json['values'] or None,
        contact_block=json['letter_contact_block'],
        # we get the images of our local server to keep network topography clean,
        # which is just http://localhost:6013
        admin_base_url='http://localhost:6013',
        logo_file_name=get_logo(json['dvla_org_id']).raster,
        date=dateutil.parser.parse(json['date']) if json.get('date') else None,
    ))


def get_pdf(html):

    @current_app.cache(html, folder='templated', extension='pdf')
    def _get():
        return BytesIO(HTML(string=html).write_pdf())

    return _get()


def get_png(html, page_number):

    @current_app.cache(html, folder='templated', extension='page{0:02d}.png'.format(page_number))
    def _get():
        return png_from_pdf(
            get_pdf(html).read(),
            page_number=page_number,
        )

    return _get()


def get_png_from_precompiled(encoded_string, page_number, hide_notify):

    @current_app.cache(
        encoded_string.decode('ascii'), hide_notify,
        folder='precompiled',
        extension='page{0:02d}.png'.format(page_number)
    )
    def _get():
        return png_from_pdf(
            base64.decodestring(encoded_string),
            page_number=page_number,
            hide_notify=hide_notify,
        )

    return _get()


@preview_blueprint.route("/precompiled-preview.png", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def view_precompiled_letter():
    try:
        encoded_string = request.get_data()

        if not encoded_string:
            abort(400)

        return send_file(
            filename_or_fp=get_png_from_precompiled(
                encoded_string,
                int(request.args.get('page', 1)),
                hide_notify=request.args.get('hide_notify', '') == 'true',
            ),
            mimetype='image/png',
        )

    # catch invalid pdfs
    except MissingDelegateError as e:
        current_app.logger.warn("Failed to generate PDF", str(e))
        abort(400)


@preview_blueprint.route("/print.pdf", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def print_letter_template():
    """
    POST /print.pdf with the following json blob
    {
        "letter_contact_block": "contact block for service, if any",
        "template": {
            "template data, as it comes out of the database"
        }
        "values": {"dict of placeholder values"},
        "dvla_org_id": {"type": "string"}
    }
    """
    json = get_and_validate_json_from_request(request, preview_schema)
    logo = get_logo(json['dvla_org_id']).vector

    template = LetterPrintTemplate(
        json['template'],
        values=json['values'] or None,
        contact_block=json['letter_contact_block'],
        # we get the images of our local server to keep network topography clean,
        # which is just http://localhost:6013
        admin_base_url='http://localhost:6013',
        logo_file_name=logo,
    )
    html = HTML(string=str(template))
    pdf = html.write_pdf()

    cmyk_pdf = convert_pdf_to_cmyk(pdf)

    response = send_file(
        BytesIO(cmyk_pdf),
        as_attachment=True,
        attachment_filename='print.pdf'
    )

    response.headers['X-pdf-page-count'] = get_page_count(pdf)
    return response


@preview_blueprint.route("/logos.pdf", methods=['GET'])
# No auth on this endpoint to make debugging easier
@statsd(namespace="template_preview")
def print_logo_sheet():

    html = HTML(string="""
        <html>
            <head>
            </head>
            <body>
                <h1>All letter logos</h1>
                {}
            </body>
        </html>
    """.format('\n<br><br>'.join(
        '<img src="/static/images/letter-template/{}" width="100%">'.format(logo.vector)
        for org_id, logo in current_app.config['LOGOS'].items()
    )))

    pdf = html.write_pdf()
    cmyk_pdf = convert_pdf_to_cmyk(pdf)

    return send_file(
        BytesIO(cmyk_pdf),
        as_attachment=True,
        attachment_filename='print.pdf'
    )


@preview_blueprint.route("/logos.json", methods=['GET'])
@auth.login_required
@statsd(namespace="template_preview")
def get_available_logos():
    return jsonify({
        key: logo.raster
        for key, logo in current_app.config['LOGOS'].items()
    })


@preview_blueprint.route("/convert.pdf", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def convert_precomplied_to_cmyk():

    encoded_string = request.get_data()

    if not encoded_string:
        abort(400)

    file_data = base64.decodebytes(encoded_string)

    PdfFileReader(BytesIO(file_data))

    cmyk_pdf = convert_pdf_to_cmyk(file_data)

    return send_file(
        BytesIO(cmyk_pdf),
        as_attachment=True,
        attachment_filename='convert.pdf'
    )
