#!/usr/bin/env bash
set -euo pipefail

# 保留最後一份：按資料夾 mtime 判斷，直接刪掉另一份
A="/Users/zengzhuyin/Documents/Lightsunion/outputs/019f69f1-a1e0-7f90-8349-6adafdc393e8"
B="/Users/zengzhuyin/Documents/Lightsunion/outputs/019f8ff5-c419-78e2-b646-82a949a2503f"

TS_A=$(stat -f %m "$A")
TS_B=$(stat -f %m "$B")

if [ "$TS_A" -gt "$TS_B" ]; then
  rm -rf "$B"
  echo "已刪除：$B"
else
  rm -rf "$A"
  echo "已刪除：$A"
fi
