#!/usr/bin/env python3
"""qx-adblock 构建工具。

  python3 tools/build.py bump                    # 把 sources.json 里的 pins 更新到上游最新 commit
  python3 tools/build.py sync                    # 按 pins 拉取上游快照到 upstream/，记录 sha256
  python3 tools/build.py audit                   # 审计将被收录的脚本（含 custom/）
  python3 tools/build.py assets                  # 生成 scripts/ 与 filter/
  python3 tools/build.py rewrites --asset-ref SHA
  python3 tools/build.py profile  --asset-ref SHA --rewrite-ref SHA

日常发布直接用 tools/release.sh，它会按顺序生成并提交，并把 commit 串起来。
"""
import argparse
import fnmatch
import hashlib
import ipaddress
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UP = ROOT / "upstream"
SOURCES = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
POLICY = json.loads((ROOT / "policy" / "policy.json").read_text(encoding="utf-8"))
DENY = [l.strip() for l in (ROOT / "policy" / "mitm-deny.txt").read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.lstrip().startswith("#")]
# 证书锁定、MitM 后会断网的 App（沿用原配置）
PINNING_EXCLUDES = ["testflight.apple.com", "*.fcbox.com", "*huami.com", "*amemv.com", "*snssdk.com", "www.google.com"]

SCRIPT_ACTIONS = ("script-response-body", "script-request-body", "script-response-header",
                  "script-request-header", "script-echo-response", "script-analyze-echo-response")
FILTER_TYPES = {"host", "host-suffix", "host-keyword", "host-wildcard", "ip-cidr", "ip6-cidr", "user-agent"}
SURGE_TO_QX = {"domain": "host", "domain-suffix": "host-suffix", "domain-keyword": "host-keyword",
               "ip-cidr": "ip-cidr", "ip-cidr6": "ip6-cidr", "user-agent": "user-agent"}
IP_RE = re.compile(r"^(\d{1,3}(\.(\d{1,3}|\*)){3}|[0-9a-fA-F:]*:[0-9a-fA-F:]+)$")


def die(msg):
    sys.exit(f"错误：{msg}")


# ---------------------------------------------------------------- 来源与 URL

def key_from_url(url):
    """把各种写法的上游 URL 归一成来源键，例如 gh:owner/repo:path。"""
    m = re.match(r"https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/(?:refs/heads/)?[^/]+/(.+)$", url)
    if m:
        return f"gh:{m[1]}/{m[2]}:{m[3]}"
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/raw/(?:refs/heads/)?[^/]+/(.+)$", url)
    if m:
        return f"gh:{m[1]}/{m[2]}:{m[3]}"
    m = re.match(r"https?://gist\.githubusercontent\.com/([^/]+)/([^/]+)/raw/(?:[0-9a-f]+/)?(.+)$", url)
    if m:
        return f"gist:{m[1]}/{m[2]}:{m[3]}"
    if url.startswith(SOURCES["site_base"]):
        return "site:" + url[len(SOURCES["site_base"]):]
    return "url:" + url


def fetch_url(key):
    kind, rest = key.split(":", 1)
    if kind == "gh":
        repo, path = rest.split(":", 1)
        pin = SOURCES["pins"].get(repo)
        if not pin:
            die(f"{key} 所在仓库 {repo} 没有登记在 sources.json 的 pins 里")
        return f"https://raw.githubusercontent.com/{repo}/{pin['commit']}/{path}"
    if kind == "site":
        return SOURCES["site_base"] + rest
    die(f"{key} 无法锁定版本，不能收录")


def snapshot_path(key):
    kind, rest = key.split(":", 1)
    return UP / kind / rest.replace(":", "/")


def read_snapshot(key):
    p = snapshot_path(key)
    if not p.exists():
        die(f"缺少上游快照 {p.relative_to(ROOT)}，先运行 sync")
    return p.read_text(encoding="utf-8")


def cdn_url(ref, path):
    repo = SOURCES["repo"]
    if SOURCES.get("cdn") == "raw":
        return f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"
    return f"https://cdn.jsdelivr.net/gh/{repo}@{ref}/{path}"


# ---------------------------------------------------------------- 匹配工具

def deny_hit_host(host):
    h = host.lower()
    for p in DENY:
        if fnmatch.fnmatch(h, p) or (p.startswith("*.") and h == p[2:]):
            return p
    return None


def deny_hit_rule(line):
    for p in DENY:
        base = p[2:] if p.startswith("*.") else p
        if "*" in base:
            continue
        for form in (base.replace(".", r"\."), base):
            if re.search(r"(?<![A-Za-z0-9-])" + re.escape(form) + r"(?![A-Za-z0-9-])", line):
                return p
    return None


STRICT = True      # sync 阶段会置为 False：只收集未登记脚本，不中断
UNKNOWN = set()


def script_policy(key):
    entry = POLICY["scripts"].get(key)
    if not entry:
        die(f"脚本 {key} 没有在 policy/policy.json 里登记处理方式。先审计，再登记 keep / replace / drop")
    return entry


def app_of(text, cfg):
    """按 App 白名单判断一条规则属于哪个 App。没有配置白名单时返回 ''（全部收录），不命中返回 None。"""
    allow = cfg.get("keep_if_matches")
    if not allow:
        return ""
    flat = text.replace("\\", "")
    for app, pat in allow.items():
        if re.search(pat, flat):
            return app
    return None


def rule_host(line):
    """从规则左半部分提取目标域名；含正则元字符（无法精确判断）时返回 None。"""
    left = line.split(" url ", 1)[0].replace("\\/", "/")
    m = re.search(r"://([^/\s]+)", left)
    if not m:
        return None
    host = m.group(1).replace("\\.", ".")
    return None if re.search(r"[\\()|?*+\[\]{}^$]", host) else host


def script_output_name(key):
    entry = script_policy(key)
    if entry["action"] == "replace":
        return entry["with"]
    return key.rsplit(":", 1)[1].rsplit("/", 1)[-1]


# ---------------------------------------------------------------- 解析重写

def parse_rewrite(src):
    """返回 (规则列表, hostname 列表, 内嵌分流行, 统计)。规则为 (说明注释, 规则行, 脚本键或 None)。"""
    rid = src["id"]
    text = read_snapshot(src["from"])
    cfg = POLICY["rewrites"].get(rid, {})
    if src.get("embedded"):
        # 脚本头部注释里内嵌的 [rewrite_local] 与 [mitm]
        head = text.split("*/", 1)[0]
        text = head
    rules, hosts, filters = [], [], []
    stats = {"dropped_policy": 0, "dropped_deny": 0, "dropped_script": 0, "dropped_app": 0,
             "hosts_removed": [], "apps": {}}
    label = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("[", "/*", "*")):
            continue
        if line.startswith("# >"):
            label = line
            continue
        if line.startswith(("#", ";", "//")):
            continue
        if line.lower().startswith("hostname"):
            hosts += [h.strip() for h in line.split("=", 1)[1].split(",") if h.strip()]
            continue
        head = line.split(",", 1)[0].strip().lower()
        if head in FILTER_TYPES and "," in line:
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 3 and parts[2].lower() in ("direct", "reject") and app_of(line, cfg) is not None:
                filters.append((parts[0].lower(), parts[1], parts[2].lower()))
            continue
        if " url " not in f" {line} ":
            continue
        app = app_of(line.split(" url ", 1)[0], cfg)
        if app is None:
            stats["dropped_app"] += 1
            continue
        if any(s in line for s in cfg.get("drop_if_contains", [])):
            stats["dropped_policy"] += 1
            continue
        if deny_hit_rule(line.split(" url ", 1)[0]):
            stats["dropped_deny"] += 1
            continue
        tokens = line.split()
        skey = None
        for act in SCRIPT_ACTIONS + ("echo-response",):
            if act in tokens:
                tail = tokens[-1]
                if tail.startswith("http"):
                    skey = key_from_url(tail)
                break
        if skey:
            entry = POLICY["scripts"].get(skey)
            if entry is None:
                if STRICT:
                    script_policy(skey)
                UNKNOWN.add(skey)
            elif entry["action"] == "drop":
                stats["dropped_script"] += 1
                continue
        if app:
            stats["apps"][app] = stats["apps"].get(app, 0) + 1
        rules.append((label, line, skey))
        label = None

    if "hostname" in cfg:
        hosts = list(cfg["hostname"])
    kept = []
    for h in hosts:
        if cfg.get("strip_ip_hosts") and IP_RE.match(h):
            stats["hosts_removed"].append(f"{h}（IP）")
        elif deny_hit_host(h):
            stats["hosts_removed"].append(f"{h}（敏感：{deny_hit_host(h)}）")
        elif h not in kept:
            kept.append(h)
    return rules, kept, filters, stats


# ---------------------------------------------------------------- 子命令

def http_get(url, ua=None):
    req = urllib.request.Request(url, headers={"User-Agent": ua or "curl/8"})
    with urllib.request.urlopen(req, timeout=120) as r:
        if r.status != 200:
            die(f"{url} 返回 {r.status}")
        return r.read()


def cmd_bump(_):
    for repo, pin in SOURCES["pins"].items():
        out = subprocess.run(["git", "ls-remote", f"https://github.com/{repo}", f"refs/heads/{pin['branch']}"],
                             capture_output=True, text=True, check=True).stdout.split()
        if out and out[0] != pin["commit"]:
            print(f"{repo}: {pin['commit'][:10]} -> {out[0][:10]}")
            pin["commit"] = out[0]
    (ROOT / "sources.json").write_text(json.dumps(SOURCES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已更新 sources.json。接下来运行 sync，并用 git diff upstream/ 审查上游改动")


def cmd_sync(_):
    lock = {}

    def save(key):
        url = fetch_url(key)
        ua = SOURCES["site_user_agent"] if key.startswith("site:") else None
        data = http_get(url, ua)
        if data.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
            die(f"{url} 返回的是网页而不是资源文件（站点可能按 User-Agent 区分内容）")
        p = snapshot_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        lock[key] = {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        print(f"  {len(data):>9}  {key}")

    if UP.exists():
        shutil.rmtree(UP)
    for src in SOURCES["rewrites"] + SOURCES["filters"]:
        save(src["from"])
    # 只拉取“过了 App 白名单、策略和敏感域名过滤后”仍会被引用的脚本
    global STRICT
    STRICT = False
    for src in SOURCES["rewrites"]:
        for _, _, skey in parse_rewrite(src)[0]:
            entry = POLICY["scripts"].get(skey) if skey else None
            if entry and entry["action"] in ("keep", "replace") and skey not in lock:
                save(skey)
    STRICT = True
    unknown = UNKNOWN
    (UP / "LOCK.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if unknown:
        print("\n以下脚本还没登记处理方式（已被收录的规则引用，构建会报错）：")
        for k in sorted(unknown):
            print("  ", k)


def kept_script_keys():
    keys = set()
    for src in SOURCES["rewrites"]:
        for _, _, skey in parse_rewrite(src)[0]:
            if skey:
                keys.add(skey)
    return keys


def cmd_audit(_):
    sys.path.insert(0, str(ROOT / "tools"))
    import audit
    bad = False
    for key in sorted(kept_script_keys()):
        entry = script_policy(key)
        path = ROOT / "custom" / entry["with"] if entry["action"] == "replace" else snapshot_path(key)
        hits, hosts = audit.audit(path)
        blocks = [h for h in hits if h[0] == "BLOCK" and h[1] not in entry.get("allow", [])]
        verdict = "BLOCK" if blocks else ("WARN" if hits else "OK")
        bad |= bool(blocks)
        print(f"[{verdict:5}] {key}  ->  {path.relative_to(ROOT)}")
        for level, name, n in hits:
            flag = "（已人工放行）" if name in entry.get("allow", []) else ""
            print(f"          {level:5} {name} x{n}{flag}")
    sys.exit(1 if bad else 0)


def cmd_assets(_):
    out = ROOT / "scripts"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    names = {}
    for key in sorted(kept_script_keys()):
        entry = script_policy(key)
        name = script_output_name(key)
        if name in names and names[name] != key:
            die(f"脚本重名：{name}（{names[name]} 与 {key}）")
        names[name] = key
        src = ROOT / "custom" / entry["with"] if entry["action"] == "replace" else snapshot_path(key)
        shutil.copyfile(src, out / name)

    fdir = ROOT / "filter"
    if fdir.exists():
        shutil.rmtree(fdir)
    fdir.mkdir()
    allow, block = [], []
    skipped_private = []
    for src in SOURCES["filters"]:
        text = read_snapshot(src["from"])
        rows = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", ";", "//")):
                continue
            parts = [x.strip() for x in line.split(",")]
            typ = SURGE_TO_QX.get(parts[0].lower(), parts[0].lower())
            if typ not in FILTER_TYPES or len(parts) < 2:
                continue
            if typ in ("ip-cidr", "ip6-cidr"):
                try:
                    net = ipaddress.ip_network(parts[1], strict=False)
                except ValueError:
                    continue
                if net.is_private or net.is_loopback or net.is_link_local or net.is_multicast:
                    skipped_private.append(parts[1])   # 清单里混入的内网段，拦截会误伤局域网
                    continue
                rows.append(f"{typ}, {parts[1]}, {src['policy']}, no-resolve")
                continue
            rows.append(f"{typ}, {parts[1]}, {src['policy']}")
        (fdir / f"{src['id']}.list").write_text(
            f"# {src['tag']}：来自 {src['from']}，共 {len(rows)} 条，策略统一为 {src['policy']}\n" + "\n".join(rows) + "\n",
            encoding="utf-8")
        print(f"  filter/{src['id']}.list  {len(rows)} 条")
    if skipped_private:
        print(f"  已忽略清单中的内网/保留地址段：{', '.join(skipped_private)}")
    for src in SOURCES["rewrites"]:
        for typ, val, pol in parse_rewrite(src)[2]:
            (allow if pol == "direct" else block).append(f"{typ}, {val}, {pol}")
    for name, rows, desc in (("RewriteAllow", allow, "重写作者要求直连的域名"),
                             ("RewriteBlock", block, "重写作者要求拦截的域名")):
        rows = list(dict.fromkeys(rows))
        (fdir / f"{name}.list").write_text(f"# {desc}（从重写文件中提取）\n" + "\n".join(rows) + "\n", encoding="utf-8")
        print(f"  filter/{name}.list  {len(rows)} 条")
    print(f"  scripts/  {len(names)} 个脚本")


def cmd_rewrites(args):
    out = ROOT / "rewrite"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    lock = json.loads((UP / "LOCK.json").read_text(encoding="utf-8"))
    for src in SOURCES["rewrites"]:
        rules, hosts, _, st = parse_rewrite(src)
        body = [
            f"# {src['tag']}：去广告重写（由 tools/build.py 生成，请勿手改）",
            f"# 上游：{lock[src['from']]['url']}",
            f"# 上游 sha256：{lock[src['from']]['sha256']}",
            f"# 收录规则 {len(rules)} 条；不在 App 白名单内删除 {st['dropped_app']} 条，按策略删除 {st['dropped_policy']} 条，"
            f"敏感域名删除 {st['dropped_deny']} 条，因脚本不安全删除 {st['dropped_script']} 条",
        ]
        if st["apps"]:
            body.append("# 按 App 收录：" + "、".join(f"{a} {n} 条" for a, n in st["apps"].items()))
        if st["hosts_removed"]:
            body.append(f"# 从 hostname 剔除 {len(st['hosts_removed'])} 个：" + ", ".join(st["hosts_removed"]))
        # 校验：规则里的 https 域名必须在 hostname 里，否则 QX 不解密、规则永远不生效
        for _, line, _s in rules:
            h = rule_host(line)
            if h and line.lstrip("^").startswith("https") and not any(fnmatch.fnmatch(h, p) for p in hosts):
                print(f"  警告：{src['id']} 的规则域名 {h} 不在 hostname 里，这条规则不会生效", file=sys.stderr)
        body += ["", "hostname = " + ", ".join(hosts), ""]
        for label, line, skey in rules:
            if skey:
                tail = line.split()[-1]
                line = line[: len(line) - len(tail)] + cdn_url(args.asset_ref, "scripts/" + script_output_name(skey))
            if label:
                body.append(label)
            body.append(line)
        (out / f"{src['id']}.conf").write_text("\n".join(body) + "\n", encoding="utf-8")
        print(f"  rewrite/{src['id']}.conf  规则 {len(rules)}  hostname {len(hosts)}")


def cmd_profile(args):
    a, r = args.asset_ref, args.rewrite_ref
    filters = [
        f"{cdn_url(a, 'filter/RewriteAllow.list')}, tag=重写附带直连, force-policy=direct, update-interval=604800, opt-parser=false, enabled=true",
    ]
    for src in SOURCES["filters"]:
        filters.append(f"{cdn_url(a, 'filter/' + src['id'] + '.list')}, tag={src['tag']}, force-policy={src['policy']}, "
                       f"update-interval=604800, opt-parser=false, enabled=true")
    filters.append(f"{cdn_url(a, 'filter/RewriteBlock.list')}, tag=重写附带拦截, force-policy=reject, update-interval=604800, opt-parser=false, enabled=true")
    # 直连类必须排在拦截类之前
    filters.sort(key=lambda l: 0 if "force-policy=direct" in l else 1)
    rewrites = [f"{cdn_url(r, 'rewrite/' + s['id'] + '.conf')}, tag={s['tag']}, update-interval=604800, opt-parser=false, enabled=true"
                for s in SOURCES["rewrites"]]
    deny = []
    for p in DENY:
        deny.append("-" + p)
        if p.startswith("*."):
            deny.append("-" + p[2:])
    mitm = ", ".join("-" + p for p in PINNING_EXCLUDES) + ", " + ", ".join(dict.fromkeys(deny))
    tpl = (ROOT / "profile.template.conf").read_text(encoding="utf-8")
    conf = (tpl.replace("{{REPO}}", SOURCES["repo"]).replace("{{ASSET_REF}}", a).replace("{{REWRITE_REF}}", r)
            .replace("{{FILTER_REMOTE}}", "\n".join(filters)).replace("{{REWRITE_REMOTE}}", "\n".join(rewrites))
            .replace("{{MITM_HOSTNAME}}", mitm))
    (ROOT / "QuantumultX.conf").write_text(conf, encoding="utf-8")
    print("  QuantumultX.conf")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("bump", "sync", "audit", "assets"):
        sub.add_parser(name)
    p = sub.add_parser("rewrites")
    p.add_argument("--asset-ref", required=True)
    p = sub.add_parser("profile")
    p.add_argument("--asset-ref", required=True)
    p.add_argument("--rewrite-ref", required=True)
    args = ap.parse_args()
    {"bump": cmd_bump, "sync": cmd_sync, "audit": cmd_audit, "assets": cmd_assets,
     "rewrites": cmd_rewrites, "profile": cmd_profile}[args.cmd](args)


if __name__ == "__main__":
    main()
