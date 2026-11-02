/*
 * 知乎去广告（可读版）
 *
 * 来源：从 ddgksf2013 的 zhihu.ads.js（V1.0.75，商业混淆器加密）解码后，
 * 只保留「去广告 / 去推广」分支，并改写为可读代码。
 *
 * 删掉的原版功能：伪装盐选会员（people/self、my_card、vip_tab）、伪造盐值分数、
 * 注入作者 Telegram 链接、按关键词过滤推荐内容、改写消息已读状态、视频 ID 修补。
 *
 * 只使用 $request.url、$response.body 和 $done：
 * 不读请求头，不读写持久化存储，不发起任何网络请求。
 * 解析失败时原样放行，不影响 App 正常使用。
 */

const url = $request.url;
const raw = $response.body;

function isAdItem(item) {
  return (
    Object.prototype.hasOwnProperty.call(item, 'ad') ||
    item.promotion_extra != null ||
    item.type === 'feed_advert' ||
    (item.extra && (item.extra.type === 'pin' || item.extra.type === 'Training'))
  );
}

function handle(body) {
  // 开屏广告：展示时长和等待超时都置 0。
  // 注意：替换结果里没有反斜杠，这与上游 zhihu.ads.js 和 zhihu_openads.js 的输出逐字节一致。
  // 响应里这两个字段位于嵌套的 JSON 字符串中（写作 \"key\":N），去掉反斜杠后外层 JSON 不再合法，
  // 客户端解析失败，就不会展示开屏广告。我没有真实响应可验证哪种写法更好，所以保持与上游一致。
  // 如果开屏广告又出现了，抓一份 launch_v2 的响应来调整这里。
  if (/commercial_api\/(.*launch_v2|real_time_launch)/.test(url)) {
    return body
      .replace(/img_play_duration\\":\d+/g, 'img_play_duration":0')
      .replace(/launch_timeout\\":\d+/g, 'launch_timeout":0');
  }

  // 问题回答列表：让客户端识别不到 ad_info 字段
  if (/questions\/\d+\/feeds/.test(url)) {
    return body.replace(/ad_info"/g, 'ad_info_removed"');
  }

  const obj = JSON.parse(body);

  if (/topstory\/recommend/.test(url) && Array.isArray(obj.data)) {
    // 推荐信息流
    obj.data = obj.data.filter((item) => !isAdItem(item));
    obj.data.forEach((item, i) => { item.offset = i + 1; });
  } else if (/topstory\/hot-lists/.test(url) && obj.data && Array.isArray(obj.data.data)) {
    // 热榜
    obj.data.data = obj.data.data.filter((item) => !item.promotion_extra);
  } else if (/next-data/.test(url) && obj.data && Array.isArray(obj.data.data)) {
    // 回答页信息流：只保留普通内容，并清空内容里的商品卡片
    obj.data.data = obj.data.data.filter((item) => item.resource_type === 'normal');
    obj.data.data.forEach((item) => {
      if (item.data && item.data.link_cards) item.data.link_cards = [];
    });
  } else if (/next-render/.test(url) && Array.isArray(obj.data)) {
    // 回答页翻页：只保留回答，并去掉回答上挂的广告
    obj.data = obj.data.filter((item) => item.type === 'answer');
    obj.data.forEach((item) => {
      if (item.ad_info && item.ad_info.data) delete item.ad_info;
    });
  } else if (/search\/preset_words/.test(url) && obj.preset_words) {
    // 搜索框推广词：把展示时间改到很远的将来，使其不显示
    ['words', 'force_words'].forEach((key) => {
      (obj.preset_words[key] || []).forEach((w) => {
        w.begin_ts = 3000000000;
        w.end_ts = 3000003600;
      });
    });
  } else if (/notifications\/v3\//.test(url) && Array.isArray(obj.data)) {
    // 消息页：去掉「活动助手」推广消息
    obj.data = obj.data.filter((item) => item.detail_title !== '活动助手');
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
