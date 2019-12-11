# notifications-template-preview

GOV.UK Notify template preview service. Generates PNG and PDF previews of letter templates 
created in the [GOV.UK Notify admin app](http://github.com/alphagov/notifications-admin).

## First-time setup

Since it's run in docker on PaaS, it's recommended that you use docker to run this locally.

```shell
  make prepare-docker-build-image
```

This will create the docker container and install the dependencies.

## Tests

The command to run all of the tests is

```shell
make test-with-docker
```

This script will run all the tests. [py.test](http://pytest.org/latest/) is used for testing.

Running tests will also apply syntax checking, using [flake8](https://pypi.org/project/flake8/).


## Running the Flask application

```shell
make run-with-docker
```

Then visit your app at `http://localhost:6013/`. For authenticated endpoints, HTTP Token Authentication is used - by default, locally it's set to `my-secret-key`.


### Hitting the application manually
```shell
curl \
  -X POST \
  -H "Authorization: Token my-secret-key" \
  -H "Content-type: application/json" \
  -d '{
    "template":{
      "subject": "foo",
      "content": "bar"
    },
    "values": null,
    "letter_contact_block": "baz",
    "filename": "hm-government"
  }' \
  http://localhost:6013/preview.pdf
```

## Running the Celery application

The Celery app is used for sanitising PDF letters asynchronously. It requires the `NOTIFICATION_QUEUE_PREFIX` environment variable to be set to the same value used in notifications-api.

```shell
make run-celery-with-docker
```

## Deploying

You shouldn’t need to deploy this manually because there’s a pipeline setup in Concourse. If you do want to deploy it manually, you'll need the notify-credentials repo set up locally. `CF_APP` should be set to `NOTIFY_TEMPLATE_PREVIEW_CELERY` if deploying the Celery app.

```shell
make (preview|staging|production) upload-to-dockerhub
make (preview|staging|production) cf-deploy
```
