import logging
import os

from flask import Flask
from flask_httpauth import HTTPTokenAuth
<<<<<<< HEAD
from notifications_utils.clients.statsd.statsd_client import StatsdClient

from app import version  # noqa
from app.transformation import Logo

=======
from notifications_utils.clients.redis.redis_client import RedisClient
>>>>>>> Update preview with a new endpoint to cache the pdf data so that it is

LOGOS = {
    '001': Logo(
        raster='hm-government.png',
        vector='hm-government.svg',
    ),
    '002': Logo(
        raster='opg.png',
        vector='opg.svg',
    ),
    '003': Logo(
        raster='dwp.png',
        vector='dwp.svg',
    ),
    '004': Logo(
        raster='geo.png',
        vector='geo.svg',
    ),
    '005': Logo(
        raster='ch.png',
        vector='ch.svg',
    ),
    '006': Logo(
        'dwp-welsh.png',
    ),
    '007': Logo(
        'dept-for-communities.png',
    ),
    '008': Logo(
        raster='mmo.png',
        vector='mmo.svg',
    ),
    '500': Logo(
        'hm-land-registry.png',
    ),
}


def load_config(application):
    application.config['API_KEY'] = os.environ['TEMPLATE_PREVIEW_API_KEY']
    application.config['LOGOS'] = LOGOS
    application.config['NOTIFY_ENVIRONMENT'] = os.environ['NOTIFICATION_QUEUE_PREFIX']
    application.config['NOTIFY_APP_NAME'] = 'template-preview'

    if os.environ['STATSD_ENABLED'] == "1":
        application.config['STATSD_ENABLED'] = True
        application.config['STATSD_HOST'] = "statsd.hostedgraphite.com"
        application.config['STATSD_PORT'] = 8125
        application.config['STATSD_PREFIX'] = os.environ['STATSD_PREFIX']
    else:
        application.config['STATSD_ENABLED'] = False

    redis_config = next(
        service for service in vcap_services['user-provided']
        if service['name'] == 'redis'
    )

    application.config['REDIS_ENABLED'] = redis_config['credentials']['redis_enabled']
    application.config['REDIS_URL'] = redis_config['credentials']['redis_url']
    application.config['EXPIRE_CACHE_IN_SECONDS'] = 600

    application.redis_store = RedisClient()
    application.redis_store.init_app(application)



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

    console = logging.StreamHandler()
    application.logger.addHandler(console)
    application.logger.setLevel(logging.INFO)

    application.statsd_client = StatsdClient()
    application.statsd_client.init_app(application)

    @auth.verify_token
    def verify_token(token):
        return token == application.config['API_KEY']

    return application


auth = HTTPTokenAuth(scheme='Token')
