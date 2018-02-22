import base64
from io import BytesIO

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
        image.composite(cover, left=0, top=0)


@statsd(namespace="template_preview")
def png_from_pdf(data, page_number, hide_notify=False):
    output = BytesIO()
    with Image(blob=data, resolution=150) as pdf:
        with Image(width=pdf.width, height=pdf.height, background=Color('white')) as image:
            try:
                page = pdf.sequence[page_number - 1]
            except IndexError:
                abort(400, 'Letter does not have a page {}'.format(page_number))

            image.composite(page, top=0, left=0)
            if hide_notify:
                hide_notify_tag(image)
            converted = image.convert('png')
            converted.save(file=output)

    output.seek(0)

    return {
        'filename_or_fp': output,
        'mimetype': 'image/png',
    }


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
    return jsonify(
        {
            'count': get_page_count(
                view_letter_template(filetype='pdf').get_data()
            )
        }
    )


@statsd(namespace="template_preview")
def get_pdf_redis_key(json):
    def print_dict(d):
        """
        From any environment/system will return the same string representation of a given dict.
        """
        return sorted(d.items())

    unique_name_dict = {
        'template_id': json['template']['id'],
        'version': json['template']['version'],
        'dvla_org_id': json['dvla_org_id'],
        'letter_contact_block': json['letter_contact_block'],
        'values': None if not json['values'] else print_dict(json['values'])
    }

    return print_dict(unique_name_dict)


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

        json = get_and_validate_json_from_request(request, preview_schema)
        logo_file_name = get_logo(json['dvla_org_id']).raster

        unique_name = get_pdf_redis_key(json)
        pdf = current_app.redis_store.get(unique_name)

        if not pdf:
            template = LetterPreviewTemplate(
                json['template'],
                values=json['values'] or None,
                contact_block=json['letter_contact_block'],
                # we get the images of our local server to keep network topography clean,
                # which is just http://localhost:6013
                admin_base_url='http://localhost:6013',
                logo_file_name=logo_file_name
            )
            string = str(template)
            html = HTML(string=string)
            pdf = html.write_pdf()
            current_app.redis_store.set(unique_name, pdf, ex=current_app.config['EXPIRE_CACHE_IN_SECONDS'])

        if filetype == 'pdf':
            return current_app.response_class(pdf, mimetype='application/pdf')
        elif filetype == 'png':
            return send_file(**png_from_pdf(
                pdf, page_number=int(request.args.get('page', 1))
            ))

    except Exception as e:
        current_app.logger.error(str(e))
        raise e


@preview_blueprint.route("/precompiled-preview.png", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def view_precompiled_letter():
    try:
        encoded_string = request.get_data()

        if not encoded_string:
            abort(400)

        pdf = base64.decodestring(encoded_string)

        return send_file(**png_from_pdf(
            pdf, page_number=int(request.args.get('page', 1)), hide_notify=True
        ))

    # catch invalid pdfs
    except MissingDelegateError as e:
        current_app.logger.error(str(e))
        abort(400)

    except Exception as e:
        current_app.logger.error(str(e))
        raise e


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
    try:
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

    except Exception as e:
        current_app.logger.error(str(e))
        raise e
