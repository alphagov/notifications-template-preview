import os
import json

from flask import Flask
from flask_httpauth import HTTPTokenAuth
from notifications_utils.clients.statsd.statsd_client import StatsdClient

from app import version  # noqa


LOGO_FILENAMES = {
    '001': 'hm-government.png',
    '002': 'opg.png',
    '003': 'dwp.png',
    '004': 'geo.png',
    '005': 'ch.png',
    '006': 'dwp-welsh.png',
    '007': 'dept-for-communities.png',
    '008': 'mmo.png',
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

    if os.environ['STATSD_ENABLED'] == "1":

        hosted_graphite_config = next(
            service for service in vcap_services['user-provided']
            if service['name'] == 'hosted-graphite'
        )

        application.config['STATSD_ENABLED'] = True
        application.config['STATSD_HOST'] = "statsd.hostedgraphite.com"
        application.config['STATSD_PORT'] = 8125
        application.config['STATSD_PREFIX'] = hosted_graphite_config['credentials']['statsd_prefix']
    else:
        application.config['STATSD_ENABLED'] = False


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

    application.statsd_client = StatsdClient()
    application.statsd_client.init_app(application)

    @auth.verify_token
    def verify_token(token):
        return token == application.config['API_KEY']

    return application


auth = HTTPTokenAuth(scheme='Token')
