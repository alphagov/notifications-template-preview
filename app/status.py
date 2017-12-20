import subprocess

from flask import Blueprint, jsonify

status_blueprint = Blueprint('status_blueprint', __name__)


@status_blueprint.route('/_status')
def _status():
    return jsonify(
        status="ok",
        ghostscript_version=get_ghostscript_version(),
        imagemagick_version=get_imagemagick_version(),
    ), 200


def get_imagemagick_version():
    return subprocess.check_output('convert -version', shell=True).decode('utf-8')


def get_ghostscript_version():
    return subprocess.check_output('gs --version', shell=True).decode('utf-8')
