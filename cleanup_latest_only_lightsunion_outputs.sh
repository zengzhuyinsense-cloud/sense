#!/usr/bin/env bash
set -euo pipefail

# 需要整理的兩個來源資料夾（按最後修改時間保留最新一個）
DIR_A="/Users/zengzhuyin/Documents/Lightsunion/outputs/019f69f1-a1e0-7f90-8349-6adafdc393e8"
DIR_B="/Users/zengzhuyin/Documents/Lightsunion/outputs/019f8ff5-c419-78e2-b646-82a949a2503f"
BACKUP="/Users/zengzhuyin/Documents/Lightsunion/outputs/_backup_keep_last_$(date +%Y%m%d_%H%M%S)"

if [ ! -d "$DIR_A" ] || [ ! -d "$DIR_B" ]; then
  echo "找不到目標資料夾，請先確認路徑："
  echo "$DIR_A"
  echo "$DIR_B"
  exit 1
fi

TS_A=$(stat -f %m "$DIR_A")
TS_B=$(stat -f %m "$DIR_B")

if [ "$TS_A" -gt "$TS_B" ]; then
  KEEP="$DIR_A"
  DROP="$DIR_B"
else
  KEEP="$DIR_B"
  DROP="$DIR_A"
fi

echo "保留：$KEEP"
echo "移除/備份：$DROP"

echo "建立備份：$BACKUP"
mkdir -p "$BACKUP"
cp -R "$DROP" "$BACKUP/"

echo "已備份完成。若確認無誤，可刪除："
echo "rm -rf \"$DROP\""
