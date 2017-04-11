from io import BytesIO

from flask import Blueprint, request, send_file, abort
from flask_weasyprint import HTML, render_pdf
from wand.image import Image
from notifications_utils.template import LetterPreviewTemplate

from app import auth

preview_blueprint = Blueprint('preview_blueprint', __name__)


def png_from_pdf(pdf_endpoint):
    output = BytesIO()
    with Image(
        blob=pdf_endpoint.get_data(),
        resolution=150,
    ) as image:
        with image.convert('png') as converted:
            converted.save(file=output)
    output.seek(0)
    return {
        'filename_or_fp': output,
        'mimetype': 'image/png',
    }


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
        "values": {"dict of placeholder values (or None)"}
    }
    """
    json = request.get_json()
    template = LetterPreviewTemplate(
        json['template'],
        values=json['values'] or None,
        contact_block=json['letter_contact_block'],
        # we get the images of our local server to keep network topography clean, which is just http://localhost:6013
        admin_base_url='http://localhost:6013'
    )
    string = str(template)
    html = HTML(string=string)
    pdf = render_pdf(html)

    if filetype == 'pdf':
        return pdf
    elif filetype == 'png':
        return send_file(**png_from_pdf(pdf))
    else:
        abort(404)
