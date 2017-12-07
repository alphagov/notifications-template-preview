import os
import json
import subprocess

from flask import Flask
from flask_httpauth import HTTPTokenAuth

from app import version


LOGO_FILENAMES = {
    '001': 'hm-government.png',
    '002': 'opg.png',
    '003': 'dwp.png',
    '004': 'geo.png',
    '005': 'ch.png',
    '006': 'dwp-welsh.png',
    '007': 'dept-for-communities.png',
    '008': 'mmo.jpg',
    '500': 'hm-land-registry.png',
}


def load_config(application):
    vcap_services = json.loads(os.environ['VCAP_SERVICES'])
    template_preview_config = next(
        service for service in vcap_services['user-provided']
        if service['name'] == 'notify-template-preview'
    )

    application.config['API_KEY'] = template_preview_config['credentials']['api_key']
    application.config['LOGO_FILENAMES'] = LOGO_FILENAMES


def create_app():
    application = Flask(
        __name__,
        static_url_path='/static',
        static_folder='../static'
    )

    load_config(application)

    from app.preview import preview_blueprint
    from app.status import status_blueprint
    application.register_blueprint(status_blueprint)
    application.register_blueprint(preview_blueprint)

    @auth.verify_token
    def verify_token(token):
        return token == application.config['API_KEY']

    return application


auth = HTTPTokenAuth(scheme='Token')
