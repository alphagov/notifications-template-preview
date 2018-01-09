import os

from flask import Flask
from flask_httpauth import HTTPTokenAuth

from app import version  # noqa
from app.transformation import Logo


LOGOS = {
    '001': Logo(
        raster='hm-government.png',
        vector='hm-government.svg',
    ),
    '002': Logo(
        'opg.png',
    ),
    '003': Logo(
        'dwp.png',
    ),
    '004': Logo(
        'geo.png',
    ),
    '005': Logo(
        'ch.png',
    ),
    '006': Logo(
        'dwp-welsh.png',
    ),
    '007': Logo(
        'dept-for-communities.png',
    ),
    '008': Logo(
        'mmo.png',
    ),
    '500': Logo(
        'hm-land-registry.png',
    ),
}


def load_config(application):
    application.config['API_KEY'] = os.environ['TEMPLATE_PREVIEW_API_KEY']
    application.config['LOGOS'] = LOGOS


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
