#!/bin/bash

# the user's crontab that runs daily at 3AM
echo "user crontab run at " `date`
cd /home/pi/RPi4_behavior_boxes  && git checkout season-crontab && git pull origin season-crontab
