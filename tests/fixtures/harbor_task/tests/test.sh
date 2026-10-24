#!/bin/bash

if [ "$(cat /app/greeting.txt)" = "hello from harbor" ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
