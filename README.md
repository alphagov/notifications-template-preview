# notifications-template-preview

Generates PNG and PDF previews of letter templates created in the [GOV.UK Notify admin app](http://github.com/alphagov/notifications-admin).

## Setting Up

### Docker container

This app uses dependencies that are difficult to install locally. In order to make local development easy, we run app commands through a Docker container. Run the following to set this up:

```shell
  make bootstrap-with-docker
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

### uv

We use [uv](https://github.com/astral-sh/uv) for Python dependency management. Follow the [install instructions](https://github.com/astral-sh/uv?tab=readme-ov-file#installation) or run:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Pre-commit

We use [pre-commit](https://pre-commit.com/) to ensure that committed code meets basic standards for formatting, and will make basic fixes for you to save time and aggravation.

Install pre-commit system-wide with, eg `brew install pre-commit`. Then, install the hooks in this repository with `pre-commit install --install-hooks`.

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

## Further documentation

- [Making local requests](docs/local-requests.md)
- [Guidance for deploying changes](docs/deploying.md)
- [The invisible "NOTIFY" tag](docs/notify-tag.md)
- [Updating dependencies](https://github.com/alphagov/notifications-manuals/wiki/Dependencies)
