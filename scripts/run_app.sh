#!/bin/bash

source environment.sh

if [[ -z "$VIRTUAL_ENV" ]] && [[ -d venv ]]; then
  source ./venv/bin/activate
fi
FLASK_APP=application.py flask run --host=0.0.0.0
