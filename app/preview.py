from flask import Blueprint, request
from flask_weasyprint import HTML, render_pdf

from notifications_utils.template import LetterPreviewTemplate

from app import auth

preview_blueprint = Blueprint('preview_blueprint', __name__)


@preview_blueprint.route("/preview.pdf", methods=['POST'])
@auth.login_required
def view_letter_template_as_pdf():
    return '', 200
