# notifications-template-preview

Generates PNG and PDF previews of letter templates created in the [GOV.UK Notify admin app](http://github.com/alphagov/notifications-admin).

## Setting Up

### Docker container

This app uses dependencies that are difficult to install locally. In order to make local development easy, we run app commands through a Docker container. Run the following to set this up:

```shell
  make bootstrap
```

Because the container caches things like Python packages, you will need to run this again if you change things like "requirements.txt".

### AWS credentials

To run the app you will need appropriate AWS credentials. See the [Wiki](https://github.com/alphagov/notifications-manuals/wiki/aws-accounts#how-to-set-up-local-development) for more details.

### `environment.sh`

In the root directory of the application, run:

```
echo "
export NOTIFICATION_QUEUE_PREFIX='YOUR_OWN_PREFIX'
"> environment.sh
```

Things to change:

- Replace YOUR_OWN_PREFIX with local_dev_\<first name\>.


## To test the application

```shell
make test-with-docker
```

If you need to run a specific command, such as a single test, you can use the `run_with_docker.sh` script. This is what `test` and other `make` rules use.

```shell
./scripts/run_with_docker.sh pytest tests/some_specific_test.py
```

## To run the application

```shell
# run the web app
make run-flask-with-docker
```

Then visit your app at `http://localhost:6013/`.

```shell
# run the background tasks
make run-celery-with-docker
```

Celery is used for sanitising PDF letters asynchronously. It requires the `NOTIFICATION_QUEUE_PREFIX` environment variable to be set to the same value used in notifications-api.

### Hitting the application manually

For authenticated endpoints, HTTP Token Authentication is used - by default, locally it's set to `my-secret-key`.

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

## Deploying

If you need to deploy the app manually, you'll need to set a few environment variables first.

```
# in the notifications-credentials repo
notify-pass credentials/dockerhub/access-token

export DOCKERHUB_PASSWORD=$(notify-pass credentials/dockerhub/access-token)
export CF_DOCKER_PASSWORD=$(notify-pass credentials/dockerhub/access-token)

# upload image for deployment
make upload-to-dockerhub
```

Now follow the [instructions on the Wiki](https://github.com/alphagov/notifications-manuals/wiki/Merging-and-deploying#deploying-a-branch-before-merging) to deploy the Flask app. To deploy the Celery app instead, run `export CF_APP=notifications-template-preview-celery` first.
