#!/bin/bash

if [ "$lidarr_eventtype" == 'Test' ]; then
  echo "This is a test!" >> /config/rsgain.txt
  exit 0
fi
echo "Lidarr ReplayGain script" >> /config/rsgain.log
echo "Added tracks $lidarr_addedtrackpaths" >> /config/rsgain.log
FOLDER="$(dirname "$(echo $lidarr_addedtrackpaths | awk -F '|' '{print $1}')")"
echo "Computing ReplayGain for $FOLDER" >> /config/rsgain.log
rsgain easy "$FOLDER" &>> /config/rsgain.log