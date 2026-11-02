#!/usr/bin/env python3
"""qx-adblock 构建工具。

  python3 tools/build.py bump                    # 把 sources.json 里的 pins 更新到上游最新 commit
  python3 tools/build.py sync                    # 按 pins 拉取上游快照到 upstream/，记录 sha256
  python3 tools/build.py audit                   # 审计将被收录的脚本（含 custom/）
  python3 tools/build.py assets                  # 生成 scripts/ 与 filter/
  python3 tools/build.py docs                    # 生成 docs/RULES.md（分流 / 重写 / MitM 的逐项说明）
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


def load_deny():
    """policy/mitm-deny.txt -> [(域名模式, App 或服务名, 分组)]。"""
    items, group = [], ""
    for raw in (ROOT / "policy" / "mitm-deny.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = re.match(r"^#\s*----\s*(.+?)\s*----\s*$", line)
        if m:
            group = m.group(1)
            continue
        if not line or line.startswith("#"):
            continue
        pat, _, name = line.partition("#")
        items.append((pat.strip(), name.strip(), group))
    return items


DENY_ITEMS = load_deny()
DENY = [p for p, _, _ in DENY_ITEMS]

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


ACTION_TEXT = {
    "reject": "断开连接", "reject-200": "返回空响应", "reject-dict": "返回空对象 {}", "reject-img": "返回空图片",
    "script-response-body": "脚本改写响应", "script-request-body": "脚本改写请求体",
    "script-response-header": "脚本改写响应头", "script-request-header": "脚本改写请求头",
    "jsonjq-response-body": "删除 / 改写 JSON 字段", "response-body": "文本替换响应体", "request-body": "文本替换请求体",
}


def rule_action(line):
    m = re.search(r" url (\S+)", line)
    return m.group(1) if m else ""


def rule_note(line, label):
    """一条规则的作用说明：优先用 policy.json 的 rule_notes，其次取上游注释里的中文描述。"""
    left = line.split(" url ", 1)[0].replace("\\", "")
    for n in POLICY.get("rule_notes", []):
        if n["match"] in left:
            return n["note"]
    if label:
        t = re.sub(r"@.*$", "", label[3:].strip()).strip()
        if "_" in t:
            t = t.split("_", 1)[1]
        if re.search(r"[\u4e00-\u9fff]", t):
            return t
    return ""


def rewrite_cfg(rid):
    return POLICY["rewrites"].get(rid, {})


def host_app(rid, host):
    cfg = rewrite_cfg(rid)
    return cfg.get("host_apps", {}).get(host) or cfg.get("app", "")


# ---------------------------------------------------------------- 解析重写

def parse_rewrite(src):
    """返回 (规则列表, hostname 列表, 内嵌分流行, 统计)。
    规则为 (上游注释, 规则行, 脚本键或 None, App 名)；分流行为 (类型, 值, 策略, 重写 id)。"""
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
                filters.append((parts[0].lower(), parts[1], parts[2].lower(), rid))
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
        rules.append((label, line, skey, app or cfg.get("app", "")))
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
        for _, _, skey, _app in parse_rewrite(src)[0]:
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
        for _, _, skey, _app in parse_rewrite(src)[0]:
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
    skipped_private = []
    for src in SOURCES["filters"]:
        text = read_snapshot(src["from"])
        rows, n = [], 0
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("# >"):                      # 保留上游的分组注释，并译成中文
                g = line[3:].strip()
                rows.append("# " + POLICY.get("group_names", {}).get(g, g))
                continue
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
            else:
                rows.append(f"{typ}, {parts[1]}, {src['policy']}")
            n += 1
        head = [f"# {src['tag']}：{src.get('desc', '')}", f"# 来源 {src['from']}，共 {n} 条，策略统一为 {src['policy']}"]
        (fdir / f"{src['id']}.list").write_text("\n".join(head + rows) + "\n", encoding="utf-8")
        print(f"  filter/{src['id']}.list  {n} 条")
    if skipped_private:
        print(f"  已忽略清单中的内网/保留地址段：{', '.join(skipped_private)}")

    groups = {"direct": {}, "reject": {}}
    for src in SOURCES["rewrites"]:
        for typ, val, pol, rid in parse_rewrite(src)[2]:
            app = rewrite_cfg(rid).get("app") or src["tag"]
            groups[pol].setdefault(app, [])
            row = f"{typ}, {val}, {pol}"
            if row not in groups[pol][app]:
                groups[pol][app].append(row)
    for name, pol, desc in (("RewriteAllow", "direct", "重写作者要求直连的域名"),
                            ("RewriteBlock", "reject", "重写作者要求拦截的域名")):
        n = sum(len(v) for v in groups[pol].values())
        lines = [f"# {desc}（从重写文件中提取，按 App 分组），共 {n} 条"]
        for app, rows in groups[pol].items():
            lines.append(f"# {app}")
            lines += rows
        (fdir / f"{name}.list").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  filter/{name}.list  {n} 条")
    print(f"  scripts/  {len(names)} 个脚本")


def cmd_rewrites(args):
    out = ROOT / "rewrite"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    lock = json.loads((UP / "LOCK.json").read_text(encoding="utf-8"))
    for src in SOURCES["rewrites"]:
        rid = src["id"]
        rules, hosts, _, st = parse_rewrite(src)
        apps = list(dict.fromkeys(a for _, _, _, a in rules if a))
        body = [
            f"# {src['tag']}：去广告重写（由 tools/build.py 生成，请勿手改）",
            f"# 作用的 App：{'、'.join(apps)}",
            f"# 上游：{lock[src['from']]['url']}",
            f"# 上游 sha256：{lock[src['from']]['sha256']}",
            f"# 收录规则 {len(rules)} 条；不在 App 白名单内删除 {st['dropped_app']} 条，按策略删除 {st['dropped_policy']} 条，"
            f"敏感域名删除 {st['dropped_deny']} 条，因脚本不安全删除 {st['dropped_script']} 条",
        ]
        if st["apps"]:
            body.append("# 按 App 收录：" + "、".join(f"{a} {n} 条" for a, n in st["apps"].items()))
        body.append(f"# 会被解密（MitM）的域名 → App，共 {len(hosts)} 个：")
        for h in hosts:
            body.append(f"#   {h}  →  {host_app(rid, h) or '（未标注）'}")
        if st["hosts_removed"]:
            body.append(f"# 从 hostname 剔除 {len(st['hosts_removed'])} 个：" + ", ".join(st["hosts_removed"]))
        # 校验：规则里的 https 域名必须在 hostname 里，否则 QX 不解密、规则永远不生效
        for _l, line, _s, _a in rules:
            h = rule_host(line)
            if h and line.lstrip("^").startswith("https") and not any(fnmatch.fnmatch(h, p) for p in hosts):
                print(f"  警告：{rid} 的规则域名 {h} 不在 hostname 里，这条规则不会生效", file=sys.stderr)
        body += ["", "hostname = " + ", ".join(hosts), ""]
        for label, line, skey, app in rules:
            note = rule_note(line, label)
            head = "：".join(x for x in (app, note) if x)
            if skey:
                tail = line.split()[-1]
                line = line[: len(line) - len(tail)] + cdn_url(args.asset_ref, "scripts/" + script_output_name(skey))
            if head:
                body.append(f"# > {head}")
            body.append(line)
        (out / f"{rid}.conf").write_text("\n".join(body) + "\n", encoding="utf-8")
        print(f"  rewrite/{rid}.conf  规则 {len(rules)}  hostname {len(hosts)}")


def list_count(name):
    p = ROOT / "filter" / f"{name}.list"
    if not p.exists():
        return 0
    return sum(1 for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#"))


def list_apps(name):
    """RewriteAllow / RewriteBlock 里按 App 分组的组名。"""
    p = ROOT / "filter" / f"{name}.list"
    if not p.exists():
        return ""
    return "、".join(l[2:].strip() for l in p.read_text(encoding="utf-8").splitlines()[1:] if l.startswith("# "))


def mitm_comment():
    """[mitm] 里 hostname 一行的逐项说明：先排除，后作用。"""
    L = ["# hostname 由两部分合成（QX 要求写在同一行，所以说明放在这里）：",
         f"#   一、排除（'-' 前缀）：共 {len(DENY_ITEMS)} 项，这些域名永远不解密。分组与对应 App 如下。",
         "#   二、作用：本行不直接写，由各重写文件自带的 hostname 合并进来，见本段末尾。"]
    group = None
    for pat, name, g in DENY_ITEMS:
        if g != group:
            L.append(f"# ---- 排除：{g} ----")
            group = g
        L.append(f"#   -{pat:<26} {name}")
    L.append("# ---- 作用：以下域名会被解密，用来改写广告（来自各重写文件）----")
    for src in SOURCES["rewrites"]:
        for h in parse_rewrite(src)[1]:
            L.append(f"#   {h:<34} {host_app(src['id'], h) or src['tag']}")
    return "\n".join(L)


def cmd_profile(args):
    a, r = args.asset_ref, args.rewrite_ref
    entries = [(
        "direct",
        [f"# 重写文件附带的直连域名，共 {list_count('RewriteAllow')} 条，涉及：{list_apps('RewriteAllow')}"],
        f"{cdn_url(a, 'filter/RewriteAllow.list')}, tag=重写附带直连, force-policy=direct, update-interval=604800, opt-parser=false, enabled=true")]
    for src in SOURCES["filters"]:
        entries.append((src["policy"],
                        [f"# {src['tag']}：{src.get('desc', '')}（{list_count(src['id'])} 条，{src['policy']}）"],
                        f"{cdn_url(a, 'filter/' + src['id'] + '.list')}, tag={src['tag']}, force-policy={src['policy']}, "
                        f"update-interval=604800, opt-parser=false, enabled=true"))
    entries.append((
        "reject",
        [f"# 重写文件附带的拦截域名，共 {list_count('RewriteBlock')} 条，涉及：{list_apps('RewriteBlock')}"],
        f"{cdn_url(a, 'filter/RewriteBlock.list')}, tag=重写附带拦截, force-policy=reject, update-interval=604800, opt-parser=false, enabled=true"))
    entries.sort(key=lambda e: 0 if e[0] == "direct" else 1)     # 直连类必须排在拦截类之前
    filters = []
    for _pol, comments, line in entries:
        filters += comments + [line]

    rewrites = []
    for s in SOURCES["rewrites"]:
        rules, hosts, _, _st = parse_rewrite(s)
        apps = "、".join(dict.fromkeys(x for _, _, _, x in rules if x))
        rewrites.append(f"# {s['tag']}：{apps}；{len(rules)} 条规则，解密 {len(hosts)} 个域名")
        rewrites.append(f"{cdn_url(r, 'rewrite/' + s['id'] + '.conf')}, tag={s['tag']}, update-interval=604800, opt-parser=false, enabled=true")

    deny = []
    for p in DENY:
        deny.append("-" + p)
        if p.startswith("*."):
            deny.append("-" + p[2:])
    mitm = ", ".join(dict.fromkeys(deny))
    tpl = (ROOT / "profile.template.conf").read_text(encoding="utf-8")
    conf = (tpl.replace("{{REPO}}", SOURCES["repo"]).replace("{{ASSET_REF}}", a).replace("{{REWRITE_REF}}", r)
            .replace("{{FILTER_REMOTE}}", "\n".join(filters)).replace("{{REWRITE_REMOTE}}", "\n".join(rewrites))
            .replace("{{MITM_COMMENT}}", mitm_comment()).replace("{{MITM_HOSTNAME}}", mitm))
    (ROOT / "QuantumultX.conf").write_text(conf, encoding="utf-8")
    print("  QuantumultX.conf")


# ---------------------------------------------------------------- 文档

VENDORS = [   # 按域名关键字粗分，仅用于 docs，顺序即优先级
    ("字节跳动（穿山甲 / 巨量引擎）", ["pangle", "pangolin", "snssdk", "toutiao", "bytedance", "bytecdn", "byteimg", "ixigua", "douyin", "pstatp", "volcengine", "zijieapi", "oceanengine", "amemv", "tiktok", "musical.ly"]),
    ("腾讯（广点通 / 统计）", ["gdt.qq", ".qq.com", "gtimg", "qpic", "tencent", "qcloud", "weixin", "wechat", "tencentmusic"]),
    ("百度（联盟 / 统计）", ["baidu", "bdstatic", "bdimg", "bcebos", "bdtj"]),
    ("阿里（阿里妈妈 / 友盟 / 统计）", ["alimama", "umeng", "alicdn", "aliyun", "mmstat", "taobao", "tanx", "youku", "alipay", "cnzz", "alibaba", "umsns", "umtrack", ".uc.cn"]),
    ("快手联盟", ["kuaishou", "gifshow", "yximgs", "ksapisrv", "kwai"]),
    ("新浪 / 微博", ["sina", "weibo"]),
    ("手机厂商（小米 / 华为 / OPPO / vivo）", ["miui", "xiaomi", ".mi.com", "hicloud", "huawei", "hihonor", "oppo", "heytap", "vivo"]),
    ("京东 / 美团 / 网易 / 360 / 搜狗", [".jd.com", "360buy", "meituan", ".163.com", "netease", "youdao", ".360.cn", ".360.com", "qihoo", "sogou", ".so.com"]),
    ("海外广告与统计（Google / Meta / Unity / AppsFlyer 等）", ["google", "doubleclick", "facebook", "fbcdn", "admob", "unity", "applovin", "appsflyer", "adjust", "criteo", "taboola", "outbrain", "amazon", "adcolony", "vungle", "ironsrc", "mopub", "inmobi", "chartboost", "smaato", "pubmatic", "rubicon", "openx", "adnxs", "yandex", "mintegral", "adsense", "analytics", "twitter", "branch.io", "flurry", "crashlytics"]),
]


def classify(value):
    v = value.lower()
    for name, keys in VENDORS:
        for k in keys:
            if (v == k[1:] or v.endswith(k)) if k.startswith(".") else (k in v):
                return name
    return "其他（小型广告 / 统计 / 垃圾站点）"


def cmd_docs(_):
    W = []
    w = W.append
    w("# 规则说明")
    w("")
    w("> 由 `python3 tools/build.py docs` 生成，请勿手改。内容与 `QuantumultX.conf`、`rewrite/*.conf` 里的注释一一对应。")
    w("")
    w("## 0. 运行模式")
    w("")
    w("| 运行模式 | 分流（下面第 1 节的黑名单） | 重写 + MitM（第 2、3 节） |")
    w("|---|---|---|")
    w("| **规则分流（推荐）** | 生效 | 生效 |")
    w("| 全部直连 | **不生效**（教程原文：必须切到规则分流，分流规则才会生效） | 间接证据显示仍然生效，但没有官方说明，需在手机上自己验证 |")
    w("")
    w("你不用翻墙，不代表用不到「分流」：这里的分流不是在选线路，而是一份**广告域名黑名单**。")
    w("淘宝、京东、拼多多、美团、QQ 音乐、哈啰、一嗨租车这些 App 没有解密，去广告全靠它。切到全部直连，它们就一点都拦不住了。")
    w("规则分流模式下 `final, direct` 让所有未命中的流量照常直连，速度与全部直连基本一样。")
    w("")

    # ---- 分流
    w("## 1. 分流（filter_remote）")
    w("")
    w("| 列表 | 作用 | 条数 | 策略 |")
    w("|---|---|---|---|")
    w(f"| 重写附带直连 | 重写文件里要求直连的域名 | {list_count('RewriteAllow')} | direct |")
    for src in SOURCES["filters"]:
        w(f"| {src['tag']} | {src.get('desc', '')} | {list_count(src['id'])} | {src['policy']} |")
    w(f"| 重写附带拦截 | 重写文件里要求拦截的域名 | {list_count('RewriteBlock')} | reject |")
    w("")
    w("顺序有意义：直连类排在拦截类之前，所以「误杀修正」能把被黑名单误拦的域名放行。")
    w("")

    sec = 0
    for src in SOURCES["filters"]:
        path = ROOT / "filter" / f"{src['id']}.list"
        if not path.exists():
            continue
        sec += 1
        lines = path.read_text(encoding="utf-8").splitlines()
        data = [l for l in lines if l.strip() and not l.startswith("#")]
        if src["policy"] == "reject":
            w(f"### 1.{sec} 为什么有 {len(data)} 条：{src['tag']}")
            w("")
            w("这是一份别人维护的广告域名黑名单，覆盖**所有 App** 里常见的广告 SDK、统计和追踪域名，不是针对你列的某几个 App。")
            w("按域名关键字粗分如下（仅供参考，一条只归一类）：")
            w("")
            kinds, vend = {}, {}
            for l in data:
                typ, val = [x.strip() for x in l.split(",")[:2]]
                kinds[typ] = kinds.get(typ, 0) + 1
                v = "IP 段" if typ in ("ip-cidr", "ip6-cidr") else classify(val)
                vend[v] = vend.get(v, 0) + 1
            w("| 归属 | 条数 |")
            w("|---|---|")
            for k, n in sorted(vend.items(), key=lambda x: -x[1]):
                w(f"| {k} | {n} |")
            w("")
            w("按类型：" + "、".join(f"{k} {n}" for k, n in sorted(kinds.items(), key=lambda x: -x[1])))
            w("")
            other = vend.get("其他（小型广告 / 统计 / 垃圾站点）", 0)
            w(f"其中约 {round(100 * other / len(data))}% 属于最后一类：成千上万个只被少数 App 或网站使用的小型广告、统计和垃圾站点域名。"
              "数量多是因为广告生态本身就很碎片化，不代表你用到了这么多 App。")
            w("")
        else:
            w(f"### 1.{sec} {src['tag']}")
            w("")
            w(src.get("desc", ""))
            w("")
            groups, cur = {}, "其他"
            for l in lines:
                if l.startswith("# ") and not l.startswith(("# " + src["tag"], "# 来源")):
                    cur = l[2:].strip()
                elif l.strip() and not l.startswith("#"):
                    groups.setdefault(cur, []).append(l.split(",")[1].strip())
            w("| 归属 | 域名 |")
            w("|---|---|")
            for g, vs in groups.items():
                w(f"| {g} | {'、'.join(vs)} |")
            w("")

    for name, title in (("RewriteAllow", "重写附带直连"), ("RewriteBlock", "重写附带拦截")):
        path = ROOT / "filter" / f"{name}.list"
        if not path.exists():
            continue
        sec += 1
        w(f"### 1.{sec} {title}")
        w("")
        w("| App | 类型 | 域名 |")
        w("|---|---|---|")
        cur = ""
        for l in path.read_text(encoding="utf-8").splitlines()[1:]:
            if l.startswith("# "):
                cur = l[2:].strip()
            elif l.strip():
                typ, val = [x.strip() for x in l.split(",")[:2]]
                w(f"| {cur} | {typ} | {val} |")
        w("")

    # ---- 重写
    w("## 2. 重写（rewrite_remote）")
    w("")
    w("重写只对第 3 节列出的、被解密的域名生效。动作含义：返回空响应 = 直接回一个空的 200；返回空对象 = 回 `{}`；断开连接 = 直接拒绝。")
    w("")
    for src in SOURCES["rewrites"]:
        rid = src["id"]
        rules, hosts, _, st = parse_rewrite(src)
        apps = "、".join(dict.fromkeys(a for _, _, _, a in rules if a))
        w(f"### 2.{SOURCES['rewrites'].index(src) + 1} {src['tag']}（`rewrite/{rid}.conf`）")
        w("")
        w(f"作用的 App：{apps}；{len(rules)} 条规则；解密 {len(hosts)} 个域名。")
        w("")
        w("| App | 作用 | 动作 | 匹配（已省略协议头，缩略） |")
        w("|---|---|---|---|")
        for label, line, skey, app in rules:
            left = re.sub(r"\\([/.:?\-])", r"\1", line.split(" url ", 1)[0])
            left = re.sub(r"^\^?https\??:?//", "", left).replace("|", "\\|")
            act = rule_action(line)
            what = ACTION_TEXT.get(act, act)
            if skey:
                what += f"（`{script_output_name(skey)}`）"
            w(f"| {app} | {rule_note(line, label) or '—'} | {what} | `{left[:70]}` |")
        w("")

    # ---- MitM
    w("## 3. MitM（主机名）")
    w("")
    w("### 3.1 作用：会被解密的域名（用来改写广告）")
    w("")
    w("| 域名 | App | 来自 |")
    w("|---|---|---|")
    for src in SOURCES["rewrites"]:
        for h in parse_rewrite(src)[1]:
            w(f"| `{h}` | {host_app(src['id'], h) or '—'} | {src['tag']} |")
    w("")
    w(f"### 3.2 排除：永远不解密的域名（{len(DENY_ITEMS)} 项）")
    w("")
    w("即使某个重写夹带了这些域名，QX 也不会解密它们。")
    w("")
    group = None
    for pat, name, g in DENY_ITEMS:
        if g != group:
            w("")
            w(f"**{g}**")
            w("")
            w("| 域名 | App / 服务 |")
            w("|---|---|")
            group = g
        w(f"| `{pat}` | {name} |")
    w("")
    out = ROOT / "docs"
    if not out.exists():
        out.mkdir()
    (out / "RULES.md").write_text("\n".join(W) + "\n", encoding="utf-8")
    print(f"  docs/RULES.md  {len(W)} 行")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("bump", "sync", "audit", "assets", "docs"):
        sub.add_parser(name)
    p = sub.add_parser("rewrites")
    p.add_argument("--asset-ref", required=True)
    p = sub.add_parser("profile")
    p.add_argument("--asset-ref", required=True)
    p.add_argument("--rewrite-ref", required=True)
    args = ap.parse_args()
    {"bump": cmd_bump, "sync": cmd_sync, "audit": cmd_audit, "assets": cmd_assets, "docs": cmd_docs,
     "rewrites": cmd_rewrites, "profile": cmd_profile}[args.cmd](args)


if __name__ == "__main__":
    main()
