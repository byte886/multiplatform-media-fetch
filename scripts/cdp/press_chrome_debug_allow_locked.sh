#!/usr/bin/env bash
# press_allow_locked.sh — 跨进程串行化 press_allow.applescript 的薄包装
#
# 为什么需要它（B-103）：
#   多个取 key 进程会各自启动 startPressLoop，每 ~800ms 派生一个 osascript 访问 System Events；
#   进程之间没有共享锁，并发的 AppleEvent 在 System Events 里互相拥塞/死等，子进程堆在 S 状态，
#   授权 sheet 反而谁都点不中（「时好时坏、弹窗卡住」）。单进程内的 inFlight 标志只能管住自己，
#   管不住「跨进程」。本包装用 mkdir 原子锁保证：全机同一时刻最多一个 press osascript 在跑。
#
# 用法与 press_allow.applescript 完全一致（透明代理）：
#   bash press_allow_locked.sh ["连接前前台App名(用于还焦)"]
#
# 行为：拿到锁才调真正的 AppleScript；等锁超过上限就本轮安静放弃（pressed=false），
#       调用方下一轮(800ms/1s)自然再试 —— 绝不并发硬闯 System Events。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRESS_SCRIPT="$SCRIPT_DIR/press_allow.applescript"
LOCK_DIR="${TMPDIR:-/tmp}/gaodun_cdp_press.lock"
RESTORE="${1:-}"

# 尝试获取原子锁：最多等约 2.5s（50 × 0.05s），与调用方单次硬超时同量级
held=0
for _ in $(seq 1 50); do
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    held=1
    break
  fi
  # 陈旧锁回收：持锁进程已不存在则抢占（锁只持有毫秒级，PID 复用概率可忽略）
  if [ -f "$LOCK_DIR/pid" ]; then
    old_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null)"
    if [ -n "$old_pid" ] && ! kill -0 "$old_pid" 2>/dev/null; then
      rm -rf "$LOCK_DIR" 2>/dev/null
      continue
    fi
  fi
  sleep 0.05
done

if [ "$held" != "1" ]; then
  # 等锁超时：放弃本轮，不并发
  echo "pressed=false"
  exit 0
fi

echo $$ > "$LOCK_DIR/pid" 2>/dev/null
release() { rm -rf "$LOCK_DIR" 2>/dev/null; }
trap release EXIT INT TERM

osascript "$PRESS_SCRIPT" "$RESTORE"
