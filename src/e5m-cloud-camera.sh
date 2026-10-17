#!/bin/sh
exec /usr/share/klippy-env/bin/python -u /usr/data/e5m-cloud-service.py "${1:-status}"
