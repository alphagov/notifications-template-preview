#!/bin/bash
gunicorn -w 5 -b 0.0.0.0:$1 wsgi
