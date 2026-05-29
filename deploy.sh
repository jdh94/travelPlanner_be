#!/bin/bash
set -e

export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus

cd /home/ringdingdonghu/projects/travelPlanner_be

git pull origin main
.venv/bin/pip install -r requirements.txt -q
.venv/bin/python manage.py migrate --noinput

systemctl --user restart travelplanner-be
echo "travelPlanner_be deployed"
