# qx-adblock

只用来去广告的 Quantumult X 配置。仓库里的远程资源全部固定到某个 commit，并收录在本仓库内，上游作者以后改什么都影响不到你。

- 没有节点，不走代理，未命中规则的流量全部直连
- 不用资源解析器，不用 BoxJs，没有定时任务
- 不收录任何混淆脚本，收录的每个脚本都能直接读懂
- 银行、支付、券商、政务、微信、Apple，以及淘宝、京东、拼多多、美团、大众点评的主网关，一律不做 MitM
- 只处理下面列出的 App，其余 App 的规则全部不收录

## 处理的 App

| App | 方式 | 说明 |
|---|---|---|
| 哔哩哔哩、知乎、小红书、高德地图、闲鱼 | 重写（解密） | 每个 App 一个重写文件；知乎、小红书用自写的可读脚本 |
| 滴滴、盒马、去哪儿、携程、神州租车、马蜂窝、两步路 | 重写（解密） | 来自「去开屏」重写，只留这几个 App 的开屏规则，共 9 条 |
| 淘宝、京东、拼多多、美团、大众点评 | 只靠域名黑名单 | 它们的开屏接口和登录、下单是同一个主网关，不解密，所以开屏广告可能去不干净 |
| QQ 音乐、哈啰、一嗨租车 | 只靠域名黑名单 | 上游没有这几个 App 的规则 |
| 其他所有 App | 只靠域名黑名单 | `AdvertisingLite` 约 3.8 万条，只按域名拦截，不解密 |

要增加或删除某个 App，改 `policy/policy.json` 里 `StartUpAds.keep_if_matches` 和 `hostname`，再运行 `tools/release.sh`。

## 目录结构

```
QuantumultX.conf        主配置（生成，导入 QX 用这个）
profile.template.conf   主配置模板
sources.json            上游来源及锁定的 commit
policy/
  policy.json           每个上游脚本的处理决定（收录 / 替换 / 删除）及理由，各重写的裁剪规则
  mitm-deny.txt         敏感域名清单：构建时从重写里剔除，主配置里用 "-" 全局排除
upstream/               上游原始快照（只读，用于对比审查）及 LOCK.json（sha256）
custom/                 自写的可读脚本（替换掉原来的混淆脚本）
scripts/  filter/  rewrite/   构建产物，QX 实际加载的就是这些
tools/
  build.py              bump / sync / audit / assets / rewrites / profile
  audit.py              脚本静态审计（混淆、外发请求、读凭证、持久化存储）
  release.sh            生成产物，并按三段 commit 锁定链接
```

## 链接是怎么锁定的

一个文件不能引用包含它自己的 commit，所以发布分三段提交：

1. **assets**：`scripts/`、`filter/`（以及工具、策略、上游快照）
2. **rewrite**：`rewrite/*.conf`，里面的脚本链接指向第 1 段的 commit
3. **profile**：`QuantumultX.conf`，里面的重写链接指向第 2 段，分流链接指向第 1 段

链接格式是 `https://cdn.jsdelivr.net/gh/shenchaoran/qx-adblock@<commit>/路径`。commit 号对应的内容不可变。想改用 GitHub raw，把 `sources.json` 里的 `cdn` 改成 `raw`，重新发布即可。国内不走代理时，raw.githubusercontent.com 经常连不上，所以默认用 jsDelivr。

> **推送时不要 rebase、squash 或 amend**，否则 commit 号会变，所有链接都会失效。

## 在 iPhone 上使用

1. QX → 设置 → 配置文件 → 下载，填 `release.sh` 最后打印的配置文件链接。
2. 设置 → MitM → **生成新证书** → 安装描述文件 → 到「设置 › 通用 › 关于本机 › 证书信任设置」里开启完全信任。
   到「设置 › 通用 › VPN 与设备管理」**删除旧的 QX 证书描述文件**，只保留新的这一个。
3. 运行模式选「规则分流」；设置 › VPN 里**关闭「兼容性增强」**。
4. 第一次使用时，部分 App 要卸载重装或清除缓存，广告才会消失（高德地图、闲鱼的作者有此说明）。

**升级时**：不要整份重新下载配置，否则会覆盖掉 `[mitm]` 里的 `passphrase` 和 `p12`，证书需要重装。
只把新配置的 `[filter_remote]` 和 `[rewrite_remote]` 两段粘贴进现有配置即可。

## 更新上游（需要审查）

```bash
python3 tools/build.py bump        # pins 更新到上游最新 commit
python3 tools/build.py sync        # 重新拉取快照
git diff --stat upstream/          # 看看上游改了什么
git diff upstream/                 # 重点审查：新增 hostname、新脚本、脚本里的外发请求
python3 tools/build.py audit       # 静态审计
tools/release.sh                   # 生成产物并提交，打印新链接
git push origin main
```

上游引用了没登记过的新脚本时，构建会直接报错。先审计这个脚本，再在 `policy/policy.json` 里写明处理方式。默认拒绝。

`ddgksf2013.top` 不是 git 仓库，没有 commit 可锁，所以只能以 `upstream/` 里的快照为准。这个站点还会按 User-Agent 返回不同内容，浏览器看到的和 QX 拿到的不一定一样，sync 时用的是 QX 的 UA。

## 安全审计结论（2026-11-02）

| 处理 | 内容 | 原因 |
|---|---|---|
| 删除 | 资源解析器、BoxJs、节点订阅（免费机场）、IP 纯净度 / 流媒体查询任务 | 不是去广告所需；免费节点能看到全部流量，解析器能改写所有远程资源 |
| 删除 | 微博、网易云、彩云天气、百度网盘、Spotify、YouTube、微信解锁 URL、Safari 搜索、豆瓣、Google 重定向 | 不在需要处理的 App 清单里，或不是去广告 |
| 白名单 | 「去开屏」重写 498 条规则只留 9 条 | 其余约 300 个 App 你没装，不需要解密它们的域名 |
| 替换 | 知乎 `zhihu.ads.js`、小红书 `redbook.ads.js` | 混淆加密。解码后发现知乎脚本含伪装会员、伪造盐值、往 App 里注入作者 TG 链接；小红书脚本内置可联网的 Env 库并读写持久化存储。已改写为只去广告的可读版（`custom/`） |
| 不解密 | 淘宝、京东、拼多多、美团、大众点评 | 主网关同时承载登录和下单，解密等于让重写看到登录凭证和订单 |
| 全局排除 | `policy/mitm-deny.txt`（银行、券商、支付、政务、车机、摄像头等） | 防止以后某个重写夹带敏感域名 |
| 修正 | `skip_validating_cert = false` | 解密后转发时仍校验真实服务器证书 |
| 保留 | blackmatrix7 AdvertisingLite（约 3.8 万条，强制 `reject`）、墨鱼 Unbreak（强制 `direct`） | 只按域名拦截，不解密内容；就算上游被篡改，`force-policy` 也让它只能拦截或直连。已去掉清单里混入的内网段 `10.72.25.0/24` |

### 仍会被解密的域名

`api.zhihu.com`、`www.zhihu.com`、`app.bilibili.com`、`*.xiaohongshu.com`、高德 5 个、闲鱼 2 个（`acs.m.goofish.com`、`g-acs.m.goofish.com`），以及滴滴 / 盒马 / 去哪儿 / 携程 / 神州租车 / 马蜂窝 / 两步路共 8 个。

其中闲鱼（`acs.m.goofish.com`）和盒马（`acs-m.freshippo.com`）与淘宝同属阿里 mtop 网关，也会承载登录态和订单。它们的规则是 reject 和 jq 字段删除；闲鱼另有一条 `amdc.js`，只读 User-Agent 并返回固定值，不读 Cookie、不发请求。如果你也不想解密，把这两个域名加进 `policy/mitm-deny.txt` 重新发布即可。
