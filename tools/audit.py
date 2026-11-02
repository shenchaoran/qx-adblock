#!/usr/bin/env python3
"""静态审计 QX 脚本：检测混淆、外发请求、凭证读取、持久化等高风险特征。

用法：python3 tools/audit.py <file-or-dir> [...]
退出码：存在 BLOCK 级问题时返回 1。
"""
import re
import sys
from pathlib import Path

# (等级, 名称, 正则)。BLOCK = 直接拒绝收录；WARN = 需要人工复核。
RULES = [
    ("BLOCK", "混淆代码(jsjiami/obfuscator)", r"jsjiami|_0x[0-9a-f]{4,}|\\x[0-9a-f]{2}\\x[0-9a-f]{2}\\x[0-9a-f]{2}"),
    ("BLOCK", "动态执行 eval/Function", r"\beval\s*\(|\bnew\s+Function\s*\(|\bFunction\s*\(\s*['\"]"),
    ("BLOCK", "主动外发请求", r"\$task\.fetch|\$httpClient|\bfetch\s*\(|XMLHttpRequest"),
    ("WARN", "读取请求头", r"\$request\.headers"),
    ("WARN", "读取请求体", r"\$request\.body"),
    ("WARN", "凭证关键字", r"(?i)\b(cookie|authorization|x-access-token|z_c0|SESSDATA|access_token)\b"),
    ("WARN", "持久化存储", r"\$prefs\.|\$persistentStore|\$persistentStore|setValueForKey|\.setdata\("),
    ("WARN", "base64 解码", r"\batob\s*\(|Base64\.decode|fromCharCode"),
    ("WARN", "通知/日志", r"\$notify|console\.log"),
]
URL_RE = re.compile(r"https?://[A-Za-z0-9.\-_]+")
MAX_LINE = 2000  # 超长单行通常是压缩/混淆产物


def audit(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = []
    for level, name, pat in RULES:
        n = len(re.findall(pat, text))
        if n:
            hits.append((level, name, n))
    longest = max((len(l) for l in text.splitlines()), default=0)
    if longest > MAX_LINE and path.suffix == ".js":
        hits.append(("WARN", f"超长单行({longest} 字符)", 1))
    hosts = sorted({u.split("//", 1)[1] for u in URL_RE.findall(text)})
    return hits, hosts


def main(args):
    files = []
    for a in args:
        p = Path(a)
        files += sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
    blocked = False
    for f in files:
        if f.suffix not in (".js", ".json"):
            continue
        hits, hosts = audit(f)
        verdict = "BLOCK" if any(h[0] == "BLOCK" for h in hits) else ("WARN" if hits else "OK")
        blocked |= verdict == "BLOCK"
        print(f"[{verdict:5}] {f}")
        for level, name, n in hits:
            print(f"        {level:5} {name} x{n}")
        if hosts:
            print(f"        hosts: {', '.join(hosts[:12])}{' ...' if len(hosts) > 12 else ''}")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["scripts"]))
