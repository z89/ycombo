#!/usr/bin/env bash
EWW_CFG="/home/archie/Documents/Github-Projects/ycombo/eww"
eww --config "$EWW_CFG" active-windows | grep -q ycombo \
  && eww --config "$EWW_CFG" close ycombo \
  || eww --config "$EWW_CFG" open ycombo
