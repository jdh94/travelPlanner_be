#!/bin/bash
set -e

cd /home/ringdingdonghu/projects/travelPlanner_be

git pull origin main
.venv/bin/pip install -r requirements.txt -q
.venv/bin/python manage.py migrate --noinput

systemctl --user restart travelplanner-be
echo "travelPlanner_be deployed"
