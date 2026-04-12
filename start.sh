#!/bin/bash
# Novel2Gal 统一启动脚本
# 核心原则：所有子进程跟随父进程生死，绝不留孤儿

set -euo pipefail
cd "$(dirname "$0")"
PROJECT_ROOT="$(pwd)"

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
NC='\033[0m'

# ── 目录 & 文件 ──
LOG_DIR="$PROJECT_ROOT/backend/data/logs"
mkdir -p "$LOG_DIR"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
LOCKFILE="$LOG_DIR/.novel2gal.lock"
PIDS=()          # 所有直接子进程 PID

# ── 加载 .env ──
if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a; source "$PROJECT_ROOT/.env"; set +a
fi

# ============================================================
# 进程管理核心
# ============================================================

# 锁：防止多实例
acquire_lock() {
  if [ -f "$LOCKFILE" ]; then
    local old_pid
    old_pid=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      echo -e "${RED}错误:${NC} Novel2Gal 已在运行 (PID $old_pid)"
      echo "  如需强制重启，先执行: kill $old_pid"
      exit 1
    fi
    # 旧锁文件但进程已死，清理
    rm -f "$LOCKFILE"
  fi
  echo $$ > "$LOCKFILE"
}

# 递归杀进程树：杀一个 PID 及其所有子孙
kill_tree() {
  local pid=$1 sig=${2:-TERM}
  # 先收集子进程（macOS 用 pgrep -P）
  local children
  children=$(pgrep -P "$pid" 2>/dev/null || true)
  for child in $children; do
    kill_tree "$child" "$sig"
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -"$sig" "$pid" 2>/dev/null || true
  fi
}

# 清理：杀所有子进程树 + 删锁
cleanup() {
  local exit_code=$?
  # 防止重复清理
  trap - EXIT INT TERM HUP
  echo ""
  echo -e "${YELLOW}[停止]${NC} 清理所有进程..."

  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill_tree "$pid" TERM
      echo -e "  ${RED}■${NC} 进程树 $pid 已终止"
    fi
  done

  # 等 2 秒让进程优雅退出
  sleep 1

  # 强杀残留
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill_tree "$pid" KILL
      echo -e "  ${RED}■${NC} 强杀残留 $pid"
    fi
  done

  # 兜底：按端口杀（防止 PID 追踪遗漏的情况）
  local port_pids
  port_pids=$(lsof -ti :8080,:5173 2>/dev/null || true)
  if [ -n "$port_pids" ]; then
    echo -e "  ${YELLOW}~${NC} 清理端口占用进程: $port_pids"
    echo "$port_pids" | xargs kill -9 2>/dev/null || true
  fi

  rm -f "$LOCKFILE"
  echo -e "${GREEN}已全部停止${NC}"
  exit "$exit_code"
}

# 捕获所有退出信号（EXIT 覆盖正常退出+异常退出+被信号杀）
trap cleanup EXIT INT TERM HUP

# ============================================================
# 健康检查
# ============================================================

wait_for_ready() {
  local name=$1 url=$2 timeout=$3 pid=$4
  for i in $(seq 1 "$timeout"); do
    # 先检查进程还在不在
    if ! kill -0 "$pid" 2>/dev/null; then
      echo -e "  ${RED}✗${NC} $name 进程已退出!"
      return 1
    fi
    if curl -s --connect-timeout 2 "$url" > /dev/null 2>&1; then
      echo -e "  ${GREEN}✓${NC} $name 就绪 (PID: $pid, ${i}s)"
      return 0
    fi
    sleep 1
  done
  echo -e "  ${RED}✗${NC} $name 启动超时 (${timeout}s)! 日志:"
  return 1
}

check_llm() {
  local url="${LLM_BASE_URL:-http://localhost:1234}"
  if curl -s --connect-timeout 3 "$url/v1/models" > /dev/null 2>&1; then
    local model
    model=$(curl -s "$url/v1/models" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(d.get('data',[{}])[0].get('id','unknown'))
" 2>/dev/null || echo "unknown")
    echo -e "  ${GREEN}✓${NC} LLM ($url) 在线 — $model"
  else
    echo -e "  ${RED}✗${NC} LLM ($url) 不可达! 场景生成将失败"
  fi
}

# ============================================================
# 启动
# ============================================================

acquire_lock

echo "══════════════════════════════════════"
echo "  Novel2Gal 启动 (PID: $$)"
echo "══════════════════════════════════════"

# ── 检查依赖 ──
echo -e "\n${YELLOW}[检查]${NC} 依赖环境..."
check_llm

# TTS 检查
if [ "${TTS_ENABLED:-false}" = "true" ]; then
  echo -e "  ${GREEN}✓${NC} TTS 已启用 (provider: ${TTS_PROVIDER:-edge_tts})"
else
  echo -e "  ${DIM}○${NC} TTS 未启用 (设置 TTS_ENABLED=true 开启)"
fi

# AnyGen 检查
if [ -n "${ANYGEN_API_KEY:-}" ]; then
  echo -e "  ${GREEN}✓${NC} AnyGen 生图已配置"
else
  echo -e "  ${DIM}○${NC} AnyGen 未配置 (无生图)"
fi

if [ ! -d "$PROJECT_ROOT/backend/.venv" ]; then
  echo -e "  ${YELLOW}~${NC} 创建 Python 虚拟环境..."
  (cd "$PROJECT_ROOT/backend" && uv venv .venv && source .venv/bin/activate && \
    uv pip install -e ".[dev]" 2>/dev/null || \
    uv pip install httpx pydantic rich beautifulsoup4 lxml surrealdb fastapi uvicorn Pillow numpy python-dotenv python-multipart)
  echo -e "  ${GREEN}✓${NC} Python 环境就绪"
fi

if [ ! -d "$PROJECT_ROOT/engine/node_modules" ]; then
  echo -e "  ${YELLOW}~${NC} 安装前端依赖..."
  (cd "$PROJECT_ROOT/engine" && npm install)
  echo -e "  ${GREEN}✓${NC} 前端依赖就绪"
fi

# ── 清理旧端口占用 ──
old_port_pids=$(lsof -ti :8080,:5173 2>/dev/null || true)
if [ -n "$old_port_pids" ]; then
  echo -e "  ${YELLOW}~${NC} 清理端口 8080/5173 上的旧进程..."
  echo "$old_port_pids" | xargs kill 2>/dev/null || true
  sleep 1
fi

# ── 启动后端 ──
echo -e "\n${YELLOW}[启动]${NC} 后端服务..."
(
  cd "$PROJECT_ROOT/backend"
  source .venv/bin/activate
  exec python -m uvicorn src.server:app --host 0.0.0.0 --port 8080 --log-level warning
) > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
PIDS+=("$BACKEND_PID")

if ! wait_for_ready "后端" "http://localhost:8080/api/stories" 15 "$BACKEND_PID"; then
  tail -20 "$BACKEND_LOG"
  exit 1
fi

# 检查已有故事
STORY_COUNT=$(curl -s http://localhost:8080/api/stories 2>/dev/null | python3 -c "
import sys,json; print(len(json.load(sys.stdin).get('stories',[])))
" 2>/dev/null || echo 0)
echo -e "  已有故事: $STORY_COUNT 个"

# ── 启动前端 ──
echo -e "\n${YELLOW}[启动]${NC} 前端服务..."
(
  cd "$PROJECT_ROOT/engine"
  exec npx vite --port 5173 --host
) > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
PIDS+=("$FRONTEND_PID")

if ! wait_for_ready "前端" "http://localhost:5173" 10 "$FRONTEND_PID"; then
  tail -10 "$FRONTEND_LOG"
  exit 1
fi

# ── 启动完成 ──
echo ""
echo "══════════════════════════════════════"
echo -e "  ${GREEN}Novel2Gal 已启动!${NC}"
echo ""
echo "  浏览器: http://localhost:5173"
echo "  后端:   http://localhost:8080"
echo "  日志:   $LOG_DIR/"
echo ""
echo "  主进程 PID: $$"
echo "  后端 PID:   $BACKEND_PID"
echo "  前端 PID:   $FRONTEND_PID"
echo ""
echo -e "  按 ${YELLOW}Ctrl+C${NC} 停止所有服务"
echo "══════════════════════════════════════"

# ============================================================
# 监控循环：子进程挂了就整体退出（不自动重启，避免掩盖问题）
# ============================================================

echo ""
echo -e "${DIM}[监控] 每 10 秒检查进程状态...${NC}"
while true; do
  sleep 10

  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo ""
    echo -e "$(date +%H:%M:%S) ${RED}[致命]${NC} 后端进程已退出!"
    echo -e "  最后日志:"
    tail -20 "$BACKEND_LOG"
    exit 1
  fi

  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo ""
    echo -e "$(date +%H:%M:%S) ${RED}[致命]${NC} 前端进程已退出!"
    echo -e "  最后日志:"
    tail -10 "$FRONTEND_LOG"
    exit 1
  fi
done
