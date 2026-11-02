/*
 * 小红书去广告（可读版）
 *
 * 来源：从 ddgksf2013 的 redbook.ads.js（V1.0.28，商业混淆器加密，内置可联网的 Env 库）解码后，
 * 只保留「去广告 / 去推广」分支，并改写为可读代码。
 *
 * 删掉的原版功能：去水印、保存视频 / 实况图（会把媒体地址写入持久化存储）、
 * 评论区处理、搜索热词与默认填词替换。
 *
 * 只使用 $request.url、$response.body 和 $done：
 * 不读请求头，不读写持久化存储，不发起任何网络请求。
 * 解析失败时原样放行，不影响 App 正常使用。
 */

const url = $request.url;
const raw = $response.body;
const FAR_START = '2208963661'; // 2039-12-31
const FAR_END = '2209050061';

function handle(body) {
  const obj = JSON.parse(body);
  const data = obj.data;

  if (/api\/sns\/v\d+\/homefeed\?/.test(url) && Array.isArray(data)) {
    // 首页信息流
    obj.data = data.filter((item) => !item.is_ads);
  } else if (/api\/sns\/v\d+\/search\/notes\?/.test(url) && data && Array.isArray(data.items)) {
    // 搜索结果
    data.items = data.items.filter((item) => !item.ads);
  } else if (/api\/sns\/v\d+\/note\/widgets/.test(url)) {
    // 笔记详情页的挂件（商品卡、活动卡）
    obj.data = {};
  } else if (/api\/sns\/v\d+\/homefeed\/categories\?/.test(url) && data && Array.isArray(data.categories)) {
    // 首页顶部频道：去掉购物、直播等商业频道
    const blocked = ['homefeed.shop', 'homefeed.sketch', 'homefeed.live'];
    data.categories = data.categories.filter((c) => !blocked.includes(c.oid));
  } else if (/api\/sns\/v\d+\/system_service\/splash_config/.test(url) && data && Array.isArray(data.ads_groups)) {
    // 开屏广告预加载：把投放时间改到很远的将来
    data.ads_groups.forEach((group) => {
      group.start_time = FAR_START;
      group.end_time = FAR_END;
      (group.ads || []).forEach((ad) => {
        ad.start_time = FAR_START;
        ad.end_time = FAR_END;
      });
    });
  } else if (/api\/sns\/v\d+\/system_service\/config\?/.test(url) && data) {
    // 启动配置：去掉商城入口、开屏、加载图等运营配置
    ['store', 'splash', 'loading_img', 'app_theme', 'cmt_words', 'highlight_tab'].forEach((k) => {
      delete data[k];
    });
  } else {
    return null;
  }
  return JSON.stringify(obj);
}

try {
  const out = raw ? handle(raw) : null;
  $done(out == null ? {} : { body: out });
} catch (e) {
  $done({});
}
