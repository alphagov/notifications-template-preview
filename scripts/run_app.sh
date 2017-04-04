#!/bin/bash

source environment.sh

if [[ -z "$VIRTUAL_ENV" ]] && [[ -d venv ]]; then
  source ./venv/bin/activate
fi

export FLASK_APP=application.py
export FLASK_DEBUG=1
export WERKZEUG_DEBUG_PIN=off

flask run --host=0.0.0.0 --port=6013
