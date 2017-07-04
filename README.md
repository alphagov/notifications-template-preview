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

These can only be run when the app is not running due to port clashes

```shell
make test-with-docker
```

This script will run all the tests. [py.test](http://pytest.org/latest/) is used for testing.

Running tests will also apply syntax checking, using [pycodestyle](https://pypi.python.org/pypi/pycodestyle).


### Running the application


```shell
make run-with-docker
```


Then visit your app at `http://localhost:6013/`. For authenticated endpoints, HTTP Token Authentication is used - by default, locally it's set to `my-secret-key`.

If you want to run this locally, follow these [instructions](#running-locally):

### hitting the application manually
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
    "letter_contact_block": "baz"
  }'
  http://localhost:6013/preview.pdf
```

## Deploying

You'll need the notify-credentials repo set up for this

```shell
make (sandbox|preview|staging|production) upload-to-dockerhub
make (sandbox|preview|staging|production) cf-deploy
```

## Running locally

During development it may be preferable to run locally.

If you haven't installed the app yet follow these steps - 

```shell
# binary dependencies
brew install imagemagick ghostscript cairo pango

mkvirtualenv -p /usr/local/bin/python3 notifications-template-preview
pip install -r requirements.txt

# create a version file
make _generate-version-file
```

You will also need to set VCAP_SERVICES (extracted from Makefile) -

```shell
export VCAP_SERVICES='{"user-provided":[{"credentials":{"api_host": "some_domain","api_key":"my-secret-key"},"label":"user-provided","name":"notify-template-preview","syslog_drain_url":"","tags":[],"volume_mounts":[]}]}'
```

Then call the run app script -

```shell
./scripts/run_app.sh 6013
```

Thereafter activate the virtualenv prior to executing the run app script above -

```shell
workon notifications-template-preview
```
