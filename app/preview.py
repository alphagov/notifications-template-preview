from io import BytesIO

import jsonschema
from flask import Blueprint, request, send_file, abort, current_app, jsonify
from flask_weasyprint import HTML, render_pdf
from wand.image import Image
from notifications_utils.template import LetterPreviewTemplate

from app import auth

preview_blueprint = Blueprint('preview_blueprint', __name__)


def validate_preview_request(json):
    schema = {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "description": "schema for parameters allowed when generating a template preview",
        "type": "object",
        "properties": {
            "letter_contact_block": {"type": ["string", "null"]},
            "values": {"type": ["object", "null"]},
            "template": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["subject", "content"]
            },
            "dvla_org_id": {"type": "string"},
        },
        "required": ["letter_contact_block", "template", "values", "dvla_org_id"],
        "additionalProperties": False,
    }

    try:
        jsonschema.validate(json, schema)
    except jsonschema.ValidationError as exc:
        abort(400, exc)


def png_from_pdf(pdf_endpoint, page_number):

    output = BytesIO()

    with Image(blob=pdf_endpoint.get_data(), resolution=150) as pdf:
        with Image(width=pdf.width, height=pdf.height) as image:
            try:
                page = pdf.sequence[page_number - 1]
            except IndexError:
                abort(400, 'Letter does not have a page {}'.format(page_number))

            image.composite(page, top=0, left=0)
            converted = image.convert('png')
            converted.save(file=output)

    output.seek(0)

    return {
        'filename_or_fp': output,
        'mimetype': 'image/png',
    }


@preview_blueprint.route("/preview.json", methods=['POST'])
@auth.login_required
def page_count():
    image = Image(blob=view_letter_template(filetype='pdf').get_data())
    return jsonify({'count': len(image.sequence)})


@preview_blueprint.route("/preview.<filetype>", methods=['POST'])
@auth.login_required
def view_letter_template(filetype):
    """
    POST /preview.pdf with the following json blob
    {
        "letter_contact_block": "contact block for service, if any",
        "template": {
            "template data, as it comes out of the database"
        }
        "values": {"dict of placeholder values"}
    }
    """
    try:
        if filetype not in ('pdf', 'png'):
            abort(404)

        if filetype == 'pdf' and request.args.get('page') is not None:
            abort(400)

        json = request.get_json()
        validate_preview_request(json)

        try:
            logo_file_name = current_app.config['LOGO_FILENAMES'][json['dvla_org_id']]
        except KeyError:
            abort(400)

        template = LetterPreviewTemplate(
            json['template'],
            values=json['values'] or None,
            contact_block=json['letter_contact_block'],
            # we get the images of our local server to keep network topography clean,
            # which is just http://localhost:6013
            admin_base_url='http://localhost:6013',
            logo_file_name=logo_file_name,
        )
        string = str(template)
        html = HTML(string=string)
        pdf = render_pdf(html)

        if filetype == 'pdf':
            return pdf
        elif filetype == 'png':
            return send_file(**png_from_pdf(
                pdf, page_number=int(request.args.get('page', 1))
            ))

    except Exception as e:
        current_app.logger.error(str(e))
        raise e


@preview_blueprint.route("/print.pdf", methods=['POST'])
@auth.login_required
def print_letter_template():
    """
    POST /print.pdf with the following json blob
    {
        "letter_contact_block": "contact block for service, if any",
        "template": {
            "template data, as it comes out of the database"
        }
        "values": {"dict of placeholder values"}
    }
    """
    try:
        json = request.get_json()
        validate_preview_request(json)

        try:
            logo_file_name = current_app.config['LOGO_FILENAMES'][json['dvla_org_id']]
        except KeyError:
            abort(400)

        template = LetterPreviewTemplate(
            json['template'],
            values=json['values'] or None,
            contact_block=json['letter_contact_block'],
            # we get the images of our local server to keep network topography clean,
            # which is just http://localhost:6013
            admin_base_url='http://localhost:6013',
            logo_file_name=logo_file_name,
        )
        html = HTML(string=str(template))
        pdf = render_pdf(html)

        return pdf

    except Exception as e:
        current_app.logger.error(str(e))
        raise e
