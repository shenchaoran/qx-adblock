#!/usr/bin/env bash
# 生成并提交三段 commit，把链接锁定到具体 commit：
#   ① assets：scripts/、filter/，以及工具、策略、上游快照
#   ② rewrite：rewrite/*.conf，其中的脚本链接锁定到 ①
#   ③ profile：QuantumultX.conf，其中的重写链接锁定到 ②，分流链接锁定到 ①
# 某一段没有变化时不新建 commit，直接复用该目录最近一次提交的 commit。
#
# 推送时不要 rebase / squash / amend，否则 commit 号会变，链接全部失效。
set -euo pipefail
cd "$(dirname "$0")/.."

python3 tools/build.py audit >/dev/null || { python3 tools/build.py audit; echo "审计未通过，已中止"; exit 1; }

# 自写脚本的离线测试（需要 node）
if command -v node >/dev/null; then
  node tests/zhihu.test.js >/dev/null || { node tests/zhihu.test.js; echo "知乎测试未通过，已中止"; exit 1; }
fi

# 防止把 CA 私钥提交进仓库
if grep -rInE '^\s*(passphrase|p12)\s*=\s*\S' --exclude-dir=.git --exclude-dir=upstream . ; then
  echo "发现 passphrase / p12，已中止。私钥绝不能进仓库"; exit 1
fi

commit_if_changed() { # $1=提交说明，其余=路径
  local msg="$1"; shift
  git add -A -- "$@"
  if git diff --cached --quiet; then return 0; fi
  git commit -q -m "$msg"
}

python3 tools/build.py assets
python3 tools/build.py docs
commit_if_changed "assets: 更新脚本与分流" . ':!rewrite' ':!QuantumultX.conf'
ASSET=$(git log -1 --format=%H -- scripts filter)

python3 tools/build.py rewrites --asset-ref "$ASSET"
commit_if_changed "rewrite: 脚本锁定到 ${ASSET:0:10}" rewrite
REWRITE=$(git log -1 --format=%H -- rewrite)

python3 tools/build.py profile --asset-ref "$ASSET" --rewrite-ref "$REWRITE"
commit_if_changed "profile: 重写锁定到 ${REWRITE:0:10}，分流锁定到 ${ASSET:0:10}" QuantumultX.conf
PROFILE=$(git log -1 --format=%H -- QuantumultX.conf)

REPO=$(python3 -c 'import json;print(json.load(open("sources.json"))["repo"])')
echo
echo "assets  @ $ASSET"
echo "rewrite @ $REWRITE"
echo "profile @ $PROFILE"
echo
echo "推送：git push origin main"
echo "配置文件（锁定版本）：https://cdn.jsdelivr.net/gh/$REPO@$PROFILE/QuantumultX.conf"
