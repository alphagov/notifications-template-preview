import subprocess

from flask import Blueprint, jsonify

from app import version

status_blueprint = Blueprint('status_blueprint', __name__)


@status_blueprint.route('/_status')
def _status():
    return jsonify(
        status="ok",

        commit=version.__commit__,
        build_time=version.__time__,
        build_number=version.__jenkins_job_number__,
        build_url=version.__jenkins_job_url__,

        ghostscript_version=get_ghostscript_version(),
        imagemagick_version=get_imagemagick_version(),
    ), 200


def get_imagemagick_version():
    return subprocess.check_output('convert -version', shell=True).decode('utf-8')


def get_ghostscript_version():
    return subprocess.check_output('gs --version', shell=True).decode('utf-8')

