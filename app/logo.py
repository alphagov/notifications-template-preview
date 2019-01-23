import requests

from cairosvg import svg2png
from flask import abort, Blueprint, current_app, send_file
from io import BytesIO
from notifications_utils.statsd_decorators import statsd

from app.preview import get_logo_from_filename

logo_blueprint = Blueprint('logo', __name__)


@logo_blueprint.route("/<logo>.svg.png", methods=['GET'])
@statsd(namespace="template_preview")
def view_letter_template(logo):

    svg_file_url = '{}/static/images/letter-template/{}'.format(
        current_app.config['LETTER_LOGO_URL'],
        get_logo_from_filename(logo).vector,
    )
    return send_file(
        filename_or_fp=_get_png_from_svg(svg_file_url),
        mimetype='image/png',
    )


def _get_png_from_svg(svg_file_url, width=1000):
    response = requests.get(svg_file_url)

    if response.status_code != 200:
        abort(response.status_code)

    return BytesIO(svg2png(
        bytestring=response.content,
        output_width=width,
    ))
