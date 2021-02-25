# notifications-template-preview

GOV.UK Notify template preview service. Generates PNG and PDF previews of letter templates
created in the [GOV.UK Notify admin app](http://github.com/alphagov/notifications-admin).

## First-time setup

This app uses dependencies that are difficult to install locally. In order to make local development easy, we run app commands through a Docker container. Run the following to set this up:

```shell
  make bootstrap
```

Because the container caches things like Python packages, you will need to run this again if you change things like "requirements.txt".

## Tests

The command to run all of the tests is

```shell
make test-with-docker
```

If you need to run a specific command, such as a single test, you can use the `run_with_docker.sh` script. This is what `test-with-docker` and other `make` rules use.

```shell
./scripts/run_with_docker.sh pytest tests/some_specific_test.py
```

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
      "content": "bar",
      "template_type": "letter"
    },
    "values": null,
    "letter_contact_block": "baz",
    "filename": "hm-government"
  }' \
  http://localhost:6013/preview.pdf
```

- `template` is an object containing the subject and content of the letter, including any placeholders
- `values` is an object containing the keys and values which should be used to populate the placeholders and the lines of the address
- `letter_contact_block` is the text that appears in the top right of the first page, can include placeholders
- `filename` is an absolute URL of the logo that goes in the top left of the first page (must be an SVG image)

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
