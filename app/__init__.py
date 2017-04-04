import subprocess

from flask import Flask, jsonify

from app import version


def create_app():
    application = Flask(__name__)

    @application.route('/_status', methods=['GET'])
    def _status():
        return jsonify(
            status="ok",
            travis_commit=version.__travis_commit__,
            travis_build_number=version.__travis_job_number__,
            build_time=version.__time__,

            ghostscript_version=get_ghostscript_version(),
            imagemagick_version=get_imagemagick_version(),
        ), 200

    def get_imagemagick_version():
        return subprocess.check_output('convert -version', shell=True)

    def get_ghostscript_version():
        return subprocess.check_output('gs --version', shell=True)

    return application
