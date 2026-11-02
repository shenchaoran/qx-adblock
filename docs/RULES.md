# 规则说明

> 由 `python3 tools/build.py docs` 生成，请勿手改。内容与 `QuantumultX.conf`、`rewrite/*.conf` 里的注释一一对应。

## 0. 运行模式

| 运行模式 | 分流（下面第 1 节的黑名单） | 重写 + MitM（第 2、3 节） |
|---|---|---|
| **规则分流（推荐）** | 生效 | 生效 |
| 全部直连 | **不生效**（教程原文：必须切到规则分流，分流规则才会生效） | 间接证据显示仍然生效，但没有官方说明，需在手机上自己验证 |

你不用翻墙，不代表用不到「分流」：这里的分流不是在选线路，而是一份**广告域名黑名单**。
淘宝、京东、拼多多、美团、QQ 音乐、哈啰、一嗨租车这些 App 没有解密，去广告全靠它。切到全部直连，它们就一点都拦不住了。
规则分流模式下 `final, direct` 让所有未命中的流量照常直连，速度与全部直连基本一样。

## 1. 分流（filter_remote）

| 列表 | 作用 | 条数 | 策略 |
|---|---|---|---|
| 重写附带直连 | 重写文件里要求直连的域名 | 1 | direct |
| 误杀修正 | 把黑名单可能误拦的域名放行（Firebase 推送、谷歌更新、阿里统计、得到、B 站视频 CDN 等），直连 | 34 | direct |
| 广告域名 | 广告 SDK、统计与追踪域名黑名单（blackmatrix7 精简版），对所有 App 生效，只按域名拦截、不解密 | 38065 | reject |
| 重写附带拦截 | 重写文件里要求拦截的域名 | 1 | reject |

顺序有意义：直连类排在拦截类之前，所以「误杀修正」能把被黑名单误拦的域名放行。

### 1.1 误杀修正

把黑名单可能误拦的域名放行（Firebase 推送、谷歌更新、阿里统计、得到、B 站视频 CDN 等），直连

| 归属 | 域名 |
|---|---|
| 得到 | umiwi.com |
| 通用（Adjust / AppsFlyer / 个推等归因与推送） | app.adjust.com、app.appsflyer.com、bdtj.tagtic.cn |
| 阿里（统计） | log.mmstat.com、sycm.mmstat.com |
| 哔哩哔哩（视频 CDN） | bilivideo.cn、bilivideo.com |
| 谷歌（更新与服务） | blog.google、googletraveladservices.com、clientservices.googleapis.com、update.googleapis.com、dl.google.com、dl.l.google.com、update.googleapis.com |
| Firebase 推送（各 App 的消息推送） | mtalk.google.com、alt1-mtalk.google.com、alt2-mtalk.google.com、alt3-mtalk.google.com、alt4-mtalk.google.com、alt5-mtalk.google.com、alt6-mtalk.google.com、alt7-mtalk.google.com、alt8-mtalk.google.com |
| 腾讯视频 | fairplay.l.qq.com、livew.l.qq.com、vd.l.qq.com、vi.l.qq.com |
| 微信 | dns.weixin.qq.com.cn、dns.weixin.qq.com |
| Strava | analytics.strava.com |
| 友盟推送 | msg.umeng.com、msg.umengcloud.com |
| 直播吧 | stats.qiumibao.com |

### 1.2 为什么有 38065 条：广告域名

这是一份别人维护的广告域名黑名单，覆盖**所有 App** 里常见的广告 SDK、统计和追踪域名，不是针对你列的某几个 App。
按域名关键字粗分如下（仅供参考，一条只归一类）：

| 归属 | 条数 |
|---|---|
| 其他（小型广告 / 统计 / 垃圾站点） | 36177 |
| 海外广告与统计（Google / Meta / Unity / AppsFlyer 等） | 365 |
| 百度（联盟 / 统计） | 309 |
| 阿里（阿里妈妈 / 友盟 / 统计） | 251 |
| 腾讯（广点通 / 统计） | 245 |
| 京东 / 美团 / 网易 / 360 / 搜狗 | 205 |
| IP 段 | 186 |
| 新浪 / 微博 | 144 |
| 手机厂商（小米 / 华为 / OPPO / vivo） | 101 |
| 字节跳动（穿山甲 / 巨量引擎） | 76 |
| 快手联盟 | 6 |

按类型：host 23753、host-suffix 13939、host-keyword 187、ip-cidr 185、ip6-cidr 1

其中约 95% 属于最后一类：成千上万个只被少数 App 或网站使用的小型广告、统计和垃圾站点域名。数量多是因为广告生态本身就很碎片化，不代表你用到了这么多 App。

### 1.3 重写附带直连

| App | 类型 | 域名 |
|---|---|---|
| 高德地图 | host-suffix | optimus-ads.amap.com |

### 1.4 重写附带拦截

| App | 类型 | 域名 |
|---|---|---|
| 闲鱼 | host-suffix | iyes.youku.com |

## 2. 重写（rewrite_remote）

重写只对第 3 节列出的、被解密的域名生效。动作含义：返回空响应 = 直接回一个空的 200；返回空对象 = 回 `{}`；断开连接 = 直接拒绝。

### 2.1 去开屏（滴滴/盒马/去哪儿/携程/神州/马蜂窝/两步路）（`rewrite/StartUpAds.conf`）

作用的 App：滴滴、盒马、两步路、马蜂窝、去哪儿、神州租车、携程；9 条规则；解密 8 个域名。

| App | 作用 | 动作 | 匹配（已省略协议头，缩略） |
|---|---|---|---|
| 滴滴 | 活动弹窗 | 返回空响应 | `res.xiaojukeji.com/resapi/activity/mget` |
| 滴滴 | 开屏广告预加载与通知 | 返回空响应 | `res.xiaojukeji.com/resapi/activity/get(Ruled\|Preload\|PasMultiNotices` |
| 盒马 | 首页弹窗与开屏 | 返回空响应 | `acs-m.freshippo.com/gw/mtop.wdk.render.querysinglepage` |
| 两步路 | 开屏、弹窗、推广任务 | 返回空响应 | `helper.2bulu.com/(greenPea/queryTasks\|proSpecial/allData\|saveSplashF` |
| 马蜂窝 | 开屏广告 | 返回空响应 | `mapi.mafengwo.cn/ad/get_launch_ad_list/v2` |
| 去哪儿 | 开屏广告 | 返回空响应 | `homefront.qunar.com/front/splash/ad` |
| 去哪儿 | 开屏广告 | 返回空响应 | `client.qunar.com/pitcher-proxy?qrt=p_splashAd` |
| 神州租车 | 营销投放位（返回空对象） | 脚本改写响应（`dict.js`） | `apiproxy.zuche.com/resource/cardes/toufang/marketing` |
| 携程 | 广告埋点 | 返回空响应 | `ma-adx.ctrip.com/_ma.gif` |

### 2.2 知乎（`rewrite/Zhihu.conf`）

作用的 App：知乎；27 条规则；解密 5 个域名。

| App | 作用 | 动作 | 匹配（已省略协议头，缩略） |
|---|---|---|---|
| 知乎 | 拦截对广告服务器 IP 的直连访问 | 返回空响应 | `118.89.204.198` |
| 知乎 | 拦截对广告服务器 IP 的直连访问 | 返回空响应 | `103.41.167.237` |
| 知乎 | 拦截对广告服务器 IPv6 的直连访问 | 返回空响应 | `2402:4e00:1200:ed00:0:9089:6dac:96b6` |
| 知乎 | 开屏广告 | 脚本改写响应（`zhihu.ads.js`） | `api.zhihu.com/commercial_api.*launch_v2` |
| 知乎 | 品牌提问广告 | 返回空对象 {} | `api.zhihu.com/brand/question/\d+/card?` |
| 知乎 | 品牌提问广告 | 返回空对象 {} | `www.zhihu.com/api/v\d+/brand/question/\d+/card?` |
| 知乎 | 拦截回答下的卡片广告 | 返回空对象 {} | `www.zhihu.com/api/v\d/answers/\d+/recommendations` |
| 知乎 | 拦截应用内弹窗 | 返回空对象 {} | `api.zhihu.com/me/guides` |
| 知乎 | 拦截推荐页顶部广告 | 返回空对象 {} | `api.zhihu.com/api/v4/ecom_data/config` |
| 知乎 | 底栏加号的广告 | 返回空对象 {} | `api.zhihu.com/content-distribution-core/bubble/common/settings` |
| 知乎 | 商业化接口整体拦截（广告、浮层、开屏等） | 返回空对象 {} | `.*zhihu.com/commercial_api` |
| 知乎 | 广告样式服务 | 断开连接 | `.*zhihu.com/ad-style-service/request` |
| 知乎 | 文章页去除底部广告 | 返回空对象 {} | `www.zhihu.com/api/v\d/articles/\d+/recommendation` |
| 知乎 | 推荐信息流去广告 | 脚本改写响应（`zhihu.ads.js`） | `api.zhihu.com/topstory/recommend` |
| 知乎 | 搜索页去除推广 | 脚本改写响应（`zhihu.ads.js`） | `api.zhihu.com/search/preset_words` |
| 知乎 | 热榜页去除广告 | 脚本改写响应（`zhihu.ads.js`） | `api.zhihu.com/v2/topstory/hot-lists` |
| 知乎 | 热榜页去除直播 | 断开连接 | `api.zhihu.com/drama/hot-drama-list` |
| 知乎 | 回答信息流去广告 | 脚本改写响应（`zhihu.ads.js`） | `api.zhihu.com/next-data` |
| 知乎 | 回答页翻页去广告 | 脚本改写响应（`zhihu.ads.js`） | `api.zhihu.com/next-render` |
| 知乎 | 回答页面顶部推广 | 断开连接 | `www.zhihu.com/api/v4/topics/rank_list/question/\d+/related` |
| 知乎 | 问题回答列表 | 脚本改写响应（`zhihu.ads.js`） | `api.zhihu.com/(v4/)?questions/\d+/feeds` |
| 知乎 | 消息页 | 脚本改写响应（`zhihu.ads.js`） | `api.zhihu.com/notifications/v3/(message\|timeline/entry/system_message` |
| 知乎 | 首页右下角悬浮窗 | 断开连接 | `api.zhihu.com/commercial_api/app_float_layer` |
| 知乎 | 回答页面相关搜索词 | 返回空对象 {} | `www.zhihu.com/api/v4/search/related_queries/answer/` |
| 知乎 | 广告请求 | 返回空响应 | `^http://[a-zA-Z0-9_-]+(.[a-zA-Z0-9_-]+){1,4}(:\d+)?/v2/resolv` |
| 知乎 | 首页左侧图标 | 返回空对象 {} | `api.zhihu.com/root/window` |
| 知乎 | 回答页底部相关圈子及搜索词 | 删除 / 改写 JSON 字段 | `.*zhihu.com/(answers\|articles)/v\d` |

### 2.3 哔哩哔哩（`rewrite/Bilibili.conf`）

作用的 App：哔哩哔哩；6 条规则；解密 1 个域名。

| App | 作用 | 动作 | 匹配（已省略协议头，缩略） |
|---|---|---|---|
| 哔哩哔哩 | 开屏广告 | 返回空响应 | `app.bilibili.com/x/v2/splash/show` |
| 哔哩哔哩 | 开屏广告列表 | 脚本改写响应（`bilibili.ads.js`） | `app.bilibili.com/x/v2/splash/list` |
| 哔哩哔哩 | 首页推荐流去广告 | 脚本改写响应（`bilibili.ads.js`） | `app.bilibili.com/x/v2/feed/index` |
| 哔哩哔哩 | 顶栏 / 底栏标签精简 | 脚本改写响应（`bilibili.ads.js`） | `app.bilibili.com/x/resource/show/tab` |
| 哔哩哔哩 | 顶部活动入口 | 脚本改写响应（`bilibili.ads.js`） | `app.bilibili.com/x/resource/top/activity` |
| 哔哩哔哩 | 搜索页热搜与推广 | 脚本改写响应（`bilibili.ads.js`） | `app.bilibili.com/x/v2/search/square` |

### 2.4 小红书（`rewrite/XiaoHongShu.conf`）

作用的 App：小红书；15 条规则；解密 1 个域名。

| App | 作用 | 动作 | 匹配（已省略协议头，缩略） |
|---|---|---|---|
| 小红书 | 搜索结果推荐信息 | 返回空响应 | `[a-z]+.xiaohongshu.com/api/sns/v\d+/search/notes/recommend_info?` |
| 小红书 | 开屏广告 | 返回空响应 | `[a-z]+.xiaohongshu.com/api/sns/v\d+/system_service/splash` |
| 小红书 | 搜索结果去广告 | 脚本改写响应（`xiaohongshu.ads.js`） | `[a-z]+.xiaohongshu.com/api/sns/v\d+/search/notes?` |
| 小红书 | 笔记详情页挂件（商品卡、活动卡） | 脚本改写响应（`xiaohongshu.ads.js`） | `[a-z]+.xiaohongshu.com/api/sns/v\d+/note/widgets` |
| 小红书 | 开屏广告预加载（把投放时间改到远期） | 脚本改写响应（`xiaohongshu.ads.js`） | `[a-z]+.xiaohongshu.com/api/sns/v\d+/system_service/splash_config` |
| 小红书 | 首页信息流去广告 | 脚本改写响应（`xiaohongshu.ads.js`） | `[a-z]+.xiaohongshu.com/api/sns/v\d+/homefeed?` |
| 小红书 | 启动配置（去掉商城入口、开屏图、加载图） | 脚本改写响应（`xiaohongshu.ads.js`） | `[a-z]+.xiaohongshu.com/api/sns/v\d+/system_service/config?` |
| 小红书 | 首页频道（去掉购物、直播等商业频道） | 脚本改写响应（`xiaohongshu.ads.js`） | `[a-z]+.xiaohongshu.com/api/sns/v\d+/homefeed/categories` |
| 小红书 | HTTPDNS 调度（让广告域名解析失败） | 返回空响应 | `[a-z]+.xiaohongshu.com/api/gslb` |
| 小红书 | HTTPDNS 调度（让广告域名解析失败） | 返回空响应 | `[a-z]+.xiaohongshu.com/api/httpdns` |
| 小红书 | 广告接口 | 返回空响应 | `[a-z]+.xiaohongshu.com/api/sns/v\d+/(tag/)?ads` |
| 小红书 | 状态上报 | 返回空响应 | `[a-z]+.xiaohongshu.com/v\d+/stateReport` |
| 小红书 | 运营开关 | 返回空响应 | `[a-z]+.xiaohongshu.com/data/native/matrix_switches` |
| 小红书 | 青少年模式状态上报 | 返回空响应 | `[a-z]+.xiaohongshu.com/api/sns/v\d+/user/teenager/status` |
| 小红书 | 首页引导弹窗 | 返回空响应 | `[a-z]+.xiaohongshu.com/api/sns/v\d+/guide/home_guide` |

### 2.5 高德地图（`rewrite/Amap.conf`）

作用的 App：高德地图；8 条规则；解密 5 个域名。

| App | 作用 | 动作 | 匹配（已省略协议头，缩略） |
|---|---|---|---|
| 高德地图 | 开屏请求 | 返回空响应 | `.*.amap.com/ws/aos/alimama/splash_screen` |
| 高德地图 | 首页底部信息流 | 返回空对象 {} | `.*.amap.com/v\d/ai_rec/` |
| 高德地图 | 路线规划下方广告 | 返回空对象 {} | `.*.amap.com/ws/faas/amap-navigation/card-service-route-plan?` |
| 高德地图 | Tip请求 | 返回空响应 | `.*.amap.com/ws/boss/order_web/\w{8}_information` |
| 高德地图 | 通用广告请求 | 断开连接 | `.*.amap.com/ws/asa/ads_attribution` |
| 高德地图 | 搜索框scene | 返回空对象 {} | `.*.amap.com/ws/shield/scene/recommend` |
| 高德地图 | 首页左上角gif | 返回空图片 | `.*.amap.com/uploadimg/\w+.gif` |
| 高德地图 | 左下天气 | 返回空对象 {} | `.*.amap.com/ws/valueadded/weather` |

### 2.6 闲鱼（`rewrite/Goofish.conf`）

作用的 App：闲鱼；14 条规则；解密 2 个域名。

| App | 作用 | 动作 | 匹配（已省略协议头，缩略） |
|---|---|---|---|
| 闲鱼 | 开屏广告 | 返回空响应 | `(g-)?acs.m.goofish.com/gw/mtop.*splash.ads` |
| 闲鱼 | 首页右下角悬浮球 | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.taobao.idle.user.strategy.list` |
| 闲鱼 | 开屏通用广告 | 返回空响应 | `(g-)?acs.m.goofish.com/gw/mtop.idle.ad.expose` |
| 闲鱼 | 首页顶部Tab | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.taobao.idlehome.home.circle.list` |
| 闲鱼 | 首页信息流 | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.taobao.idlehome.home.nextfresh` |
| 闲鱼 | 搜索填词 | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.taobao.idlemtopsearch.search.shade` |
| 闲鱼 | 猜你可能找 | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.taobao.idlemtopsearch.item.search.activ` |
| 闲鱼 | 搜索发现 | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.taobao.idlemtopsearch.search.discover` |
| 闲鱼 | 我的页面 | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.idle.user.page.my.adapter` |
| 闲鱼 | 我的页面信息流处理 | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.taobao.idle.item.buy.feeds` |
| 闲鱼 | 本地信息流AD | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.taobao.idle.local.home` |
| 闲鱼 | 搜索结果信息流AD | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.taobao.idlemtopsearch.search` |
| 闲鱼 | 商品底部推荐商品信息流AD | 删除 / 改写 JSON 字段 | `(g-)?acs.m.goofish.com/gw/mtop.taobao.idle.item.recommend` |
| 闲鱼 | AMDC处理 | 脚本改写响应（`amdc.js`） | `^http://[a-zA-Z0-9_-]+(.[a-zA-Z0-9_-]+){1,4}(:\d+)?/amdc/mobileDispatc` |

## 3. MitM（主机名）

### 3.1 作用：会被解密的域名（用来改写广告）

| 域名 | App | 来自 |
|---|---|---|
| `res.xiaojukeji.com` | 滴滴 | 去开屏（滴滴/盒马/去哪儿/携程/神州/马蜂窝/两步路） |
| `acs-m.freshippo.com` | 盒马 | 去开屏（滴滴/盒马/去哪儿/携程/神州/马蜂窝/两步路） |
| `homefront.qunar.com` | 去哪儿 | 去开屏（滴滴/盒马/去哪儿/携程/神州/马蜂窝/两步路） |
| `client.qunar.com` | 去哪儿 | 去开屏（滴滴/盒马/去哪儿/携程/神州/马蜂窝/两步路） |
| `ma-adx.ctrip.com` | 携程 | 去开屏（滴滴/盒马/去哪儿/携程/神州/马蜂窝/两步路） |
| `apiproxy.zuche.com` | 神州租车 | 去开屏（滴滴/盒马/去哪儿/携程/神州/马蜂窝/两步路） |
| `mapi.mafengwo.cn` | 马蜂窝 | 去开屏（滴滴/盒马/去哪儿/携程/神州/马蜂窝/两步路） |
| `helper.2bulu.com` | 两步路 | 去开屏（滴滴/盒马/去哪儿/携程/神州/马蜂窝/两步路） |
| `api.zhihu.com` | 知乎（接口） | 知乎 |
| `www.zhihu.com` | 知乎（网页接口） | 知乎 |
| `118.89.204.198` | 知乎（广告服务器 IP） | 知乎 |
| `103.41.167.237` | 知乎（广告服务器 IP） | 知乎 |
| `2402:4e00:1200:ed00:0:9089:6dac:96b6` | 知乎（广告服务器 IPv6） | 知乎 |
| `app.bilibili.com` | 哔哩哔哩 | 哔哩哔哩 |
| `*.xiaohongshu.com` | 小红书 | 小红书 |
| `m5.amap.com` | 高德地图 | 高德地图 |
| `m5-zb.amap.com` | 高德地图 | 高德地图 |
| `center.amap.com` | 高德地图 | 高德地图 |
| `amap-aos-info-nogw.amap.com` | 高德地图 | 高德地图 |
| `ai.amap.com` | 高德地图 | 高德地图 |
| `acs.m.goofish.com` | 闲鱼 | 闲鱼 |
| `g-acs.m.goofish.com` | 闲鱼 | 闲鱼 |

### 3.2 排除：永远不解密的域名（133 项）

即使某个重写夹带了这些域名，QX 也不会解密它们。


**证书锁定（解密后 App 会直接断网，沿用原配置）**

| 域名 | App / 服务 |
|---|---|
| `testflight.apple.com` | TestFlight |
| `*.fcbox.com` | 丰巢快递柜 |
| `*huami.com` | 华米 / Zepp / 小米运动 |
| `*amemv.com` | 抖音 |
| `*snssdk.com` | 抖音、今日头条的 API 域名 |
| `www.google.com` | 谷歌搜索 |

**Apple / 系统**

| 域名 | App / 服务 |
|---|---|
| `*.apple.com` | Apple ID、App Store、系统服务 |
| `*.icloud.com` | iCloud |
| `*.icloud.com.cn` | iCloud（中国大陆） |
| `*.mzstatic.com` | App Store 图片与资源 |
| `*.apple-cloudkit.com` | CloudKit |

**支付 / 银行 / 信用卡**

| 域名 | App / 服务 |
|---|---|
| `*.alipay.com` | 支付宝 |
| `*.alipayobjects.com` | 支付宝静态资源 |
| `*.alipay.cn` | 支付宝 |
| `*.tenpay.com` | 微信支付 / 财付通 |
| `*.unionpay.com` | 云闪付 / 银联 |
| `*.95516.com` | 云闪付 / 银联 |
| `*.cmbchina.com` | 招商银行 |
| `*.cmbimg.com` | 招商银行 |
| `*.icbc.com.cn` | 工商银行 |
| `*.ccb.com` | 建设银行 |
| `*.abchina.com` | 农业银行 |
| `*.abchina.com.cn` | 农业银行 |
| `*.boc.cn` | 中国银行 |
| `*.bankofchina.com` | 中国银行 |
| `*.bankcomm.com` | 交通银行 |
| `*.bankcomm.cn` | 交通银行 |
| `*.psbc.com` | 邮储银行 |
| `*.cebbank.com` | 光大银行 |
| `*.cib.com.cn` | 兴业银行 |
| `*.spdb.com.cn` | 浦发银行 |
| `*.cmbc.com.cn` | 民生银行 |
| `*.hxb.com.cn` | 华夏银行 |
| `*.pingan.com` | 平安银行 / 平安金融 |
| `*.pingan.com.cn` | 平安银行 / 平安金融 |
| `*.pingan.cn` | 平安 |
| `*.ecitic.com` | 中信银行 |
| `*.citicbank.com` | 中信银行 |
| `*.webank.com` | 微众银行 |
| `*.mybank.cn` | 网商银行 |
| `*.js96008.com` | 江苏农商行 |
| `*.helipay.com` | 合利宝支付 |
| `*.duxiaoman.com` | 度小满金融 |
| `*.qjjfin.com` | 钱就就 |
| `*.wacaijizhang.com` | 挖财记账 |
| `jr.jd.com` | 京东金融 |
| `*.jr.jd.com` | 京东金融 |
| `api.jr.mi.com` | 小米金融 |

**证券 / 基金 / 金融数据**

| 域名 | App / 服务 |
|---|---|
| `*.futunn.com` | 富途牛牛 |
| `*.futuhk.com` | 富途 |
| `*.moomoo.com` | moomoo |
| `*.xueqiu.com` | 雪球 |
| `*.10jqka.com.cn` | 同花顺 |
| `*.eastmoney.com` | 东方财富 |
| `*.1234567.com.cn` | 天天基金 |
| `*.chinastock.com.cn` | 中国银河证券 |
| `*.touker.com` | 投客 |
| `*.wind.com.cn` | 万得 |
| `*.hgold.cn` | 汇通财经 |
| `*.zhaojinapp.com` | 招金 |
| `*.htsc.com.cn` | 华泰证券 |
| `*.gtja.com` | 国泰君安 |
| `*.citics.com` | 中信证券 |
| `*.longbridge.global` | 长桥 |
| `*.tigerbrokers.com` | 老虎证券 |

**即时通讯 / 社交账号**

| 域名 | App / 服务 |
|---|---|
| `*.weixin.qq.com` | 微信、公众号 |
| `*.wechat.com` | 微信 |
| `*.wxs.qq.com` | 微信小程序 |
| `weixin110.qq.com` | 微信安全拦截页 |
| `mp.weixin.qq.com` | 公众号文章 |
| `ptlogin2.qq.com` | QQ 登录 |
| `*.ptlogin2.qq.com` | QQ 登录 |
| `ssl.ptlogin2.qq.com` | QQ 登录 |

**政务 / 出行实名 / 医疗**

| 域名 | App / 服务 |
|---|---|
| `*.gov.cn` | 政务服务、医保、交管 12123 |
| `mobile.12306.cn` | 12306 |
| `kyfw.12306.cn` | 12306 |
| `www.12306.cn` | 12306 |
| `*.122.gov.cn` | 交管 12123 |
| `*.csair.com` | 南方航空 |
| `*.xiamenair.com` | 厦门航空 |
| `*.juneyaoair.com` | 吉祥航空 |
| `*.ceair.com` | 东方航空 |
| `*.airchina.com.cn` | 国航 |
| `*.umetrip.com` | 航旅纵横 |
| `*.umetrip.com.cn` | 航旅纵横 |
| `*.jk.cn` | 平安好医生 |
| `*.91160.com` | 挂号网 |

**电商主站 / 外卖（同一网关承载登录态与订单）**

| 域名 | App / 服务 |
|---|---|
| `*.taobao.com` | 淘宝 |
| `*.tmall.com` | 天猫 |
| `*.jd.com` | 京东 |
| `*.jdcloud.com` | 京东云 |
| `*.yangkeduo.com` | 拼多多 |
| `*.pinduoduo.com` | 拼多多 |
| `*.meituan.com` | 美团、美团外卖 |
| `*.meituan.net` | 美团图片与资源 |
| `*.dianping.com` | 大众点评 |
| `*.ele.me` | 饿了么 |
| `app.dewu.com` | 得物 |

**邮箱 / 运营商 / 网盘**

| 域名 | App / 服务 |
|---|---|
| `*.mail.163.com` | 网易邮箱 |
| `appconf.mail.163.com` | 网易邮箱 |
| `*.mail.qq.com` | QQ 邮箱 |
| `*.mail.10086.cn` | 139 邮箱 |
| `*.10086.cn` | 中国移动 |
| `*.10010.com` | 中国联通 |
| `*.189.cn` | 中国电信、天翼云盘 |
| `*.ahmobile.cn` | 安徽移动 |
| `www.123pan.com` | 123 云盘 |

**智能家居 / 摄像头 / 远程控制 / 车机**

| 域名 | App / 服务 |
|---|---|
| `*.mi.com` | 小米商城、米家 |
| `*.ys7.com` | 萤石摄像头 |
| `*.lechange.cn` | 乐橙摄像头 |
| `*.xiaoyi.com` | 小蚁摄像头 |
| `*.oray.com` | 向日葵远程控制 |
| `*.oray.net` | 向日葵远程控制 |
| `*.narwaltech.com` | 云鲸扫地机 |
| `*.onethingpcs.com` | 玩客云 |
| `*.geely.com` | 吉利汽车 |
| `*.faw-vw.com` | 一汽大众 |
| `*.gwmapp-w.com` | 长城汽车 |
| `*.leapmotor.cn` | 零跑汽车 |
| `*.jetour.com.cn` | 捷途汽车 |
| `*.bjev.com.cn` | 北京汽车 |
| `*.ftms.com.cn` | 广汽丰田 |
| `*.ghac.cn` | 广汽 |
| `*.shouqiev.com` | 首汽约车 |

**密码管理 / 开发者账号**

| 域名 | App / 服务 |
|---|---|
| `*.1password.com` | 1Password |
| `*.bitwarden.com` | Bitwarden |
| `*.github.com` | GitHub |
| `*.githubusercontent.com` | GitHub |

**你的其他 App（本来就没有重写会解密它们，这里是预防性排除）**

| 域名 | App / 服务 |
|---|---|
| `*.y.qq.com` | QQ 音乐 |
| `*.music.qq.com` | QQ 音乐 |
| `*.hellobike.com` | 哈啰 |
| `*.1hai.cn` | 一嗨租车 |
| `*.ehi.com.cn` | 一嗨租车 |

