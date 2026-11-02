#!/usr/bin/env node
/*
 * 知乎去广告离线测试（不需要手机）。
 *
 *   node tests/zhihu.test.js
 *
 * 做三件事：
 *   1. 规则匹配：按 rewrite/Zhihu.conf 里的顺序，给一批真实形态的 URL 找第一条命中的规则，
 *      确认广告接口被拦、登录和正文接口不受影响，并确认域名在 MitM 的 hostname 里。
 *   2. 脚本行为：把同一份构造数据分别喂给「上游原版（混淆）」和「自写可读版」，对比输出。
 *   3. 容错：响应体不是 JSON 时必须原样放行。
 *
 * 局限：数据是按脚本读取的字段构造的，不是知乎真实响应。能证明逻辑正确，不能证明知乎当前接口仍是这个结构。
 */
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');

// ---------------------------------------------------------------- 1. 规则匹配
const conf = read('rewrite/Zhihu.conf');
const hostnames = conf.match(/^hostname = (.*)$/m)[1].split(',').map((s) => s.trim());
const rules = conf.split('\n')
  .filter((l) => l.includes(' url ') && !l.startsWith('#'))
  .map((l) => {
    const i = l.indexOf(' url ');
    const rest = l.slice(i + 5).trim().split(/\s+/);
    return { re: new RegExp(l.slice(0, i).trim()), action: rest[0], script: (rest[1] || '').split('/').pop() };
  });

const hostOk = (url) => {
  const h = new URL(url).hostname;
  return hostnames.some((p) => new RegExp('^' + p.replace(/\./g, '\\.').replace(/\*/g, '.*') + '$').test(h));
};
const firstHit = (url) => rules.find((r) => r.re.test(url));

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  ok ? pass++ : fail++;
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`);
};

console.log(`\n[1] 规则匹配（共 ${rules.length} 条规则，MitM 域名：${hostnames.join(', ')}）`);

const BLOCK = [
  ['推荐信息流',         'https://api.zhihu.com/topstory/recommend?action=down&page_number=2', /^script/, 'zhihu.ads.js'],
  ['开屏广告',           'https://api.zhihu.com/commercial_api/launch_v2?x=1',                  /^script/, 'zhihu.ads.js'],
  ['开屏实时拉取',       'https://api.zhihu.com/commercial_api/real_time_launch',               /^reject/],
  ['商业接口兜底',       'https://api.zhihu.com/commercial_api/anything',                       /^reject/],
  ['浮层广告',           'https://api.zhihu.com/commercial_api/app_float_layer',                /^reject/],
  ['广告样式服务',       'https://api.zhihu.com/ad-style-service/request',                      /^reject/],
  ['热榜',               'https://api.zhihu.com/v2/topstory/hot-lists/total?limit=50',          /^script/, 'zhihu.ads.js'],
  ['问题回答列表',       'https://api.zhihu.com/questions/123456/feeds?limit=5',                /^script/, 'zhihu.ads.js'],
  ['问题回答列表 v4',    'https://api.zhihu.com/v4/questions/123456/feeds?limit=5',             /^script/, 'zhihu.ads.js'],
  ['回答页信息流',       'https://api.zhihu.com/next-data?id=1',                                /^script/, 'zhihu.ads.js'],
  ['回答页翻页',         'https://api.zhihu.com/next-render?id=1',                              /^script/, 'zhihu.ads.js'],
  ['搜索框推广词',       'https://api.zhihu.com/search/preset_words?x=1',                       /^script/, 'zhihu.ads.js'],
  ['消息页活动助手',     'https://api.zhihu.com/notifications/v3/message?limit=20',             /^script/, 'zhihu.ads.js'],
  ['回答下卡片广告',     'https://www.zhihu.com/api/v4/answers/123/recommendations?limit=3',    /^reject/],
  ['文章底部广告',       'https://www.zhihu.com/api/v4/articles/123/recommendation',            /^reject/],
  ['应用内弹窗',         'https://api.zhihu.com/me/guides',                                     /^reject/],
  ['首页左侧图标',       'https://api.zhihu.com/root/window',                                   /^reject/],
  ['品牌提问广告',       'https://api.zhihu.com/brand/question/123/card?x=1',                   /^reject/],
];
for (const [name, url, actionRe, script] of BLOCK) {
  const r = firstHit(url);
  check(`拦截  ${name}`, !!r && actionRe.test(r.action) && (!script || r.script === script) && hostOk(url),
        r ? `-> ${r.action}${r.script ? ' ' + r.script : ''}` : '-> 未命中');
}

const UNTOUCHED = [
  ['登录',           'https://api.zhihu.com/sign_in'],
  ['登录 v3',        'https://www.zhihu.com/api/v3/oauth/sign_in'],
  ['刷新令牌',       'https://www.zhihu.com/api/v3/oauth/token'],
  ['个人信息',       'https://api.zhihu.com/people/self'],
  ['当前用户',       'https://api.zhihu.com/me'],
  ['回答正文',       'https://api.zhihu.com/answers/123456'],
  ['问题详情',       'https://api.zhihu.com/v4/questions/123456'],
  ['发表评论',       'https://api.zhihu.com/comment_v5/answers/123/root_comment'],
  ['私信',           'https://api.zhihu.com/im/conversations'],
  ['盐选会员页',     'https://api.zhihu.com/bazaar/vip_tab/modules'],
  ['盐值',           'https://api.zhihu.com/user-credit/basis'],
  ['专栏文章',       'https://zhuanlan.zhihu.com/p/123456'],
  ['图片',           'https://pic1.zhimg.com/v2-abc_r.jpg'],
];
for (const [name, url] of UNTOUCHED) {
  const r = firstHit(url);
  check(`不碰  ${name}`, !r, r ? `-> 被 ${r.action} 命中: ${r.re}` : '');
}

// ---------------------------------------------------------------- 2. 脚本行为对比
function run(file, url, body) {
  let out;
  const ctx = {
    $request: { url, headers: {} }, $response: { body }, $done: (o) => { out = o; },
    console: { log() {} }, JSON, Object, Array, parseInt, String, Number, RegExp, Math, Date,
  };
  vm.runInNewContext(file, ctx, { timeout: 5000 });
  // 约定：$done({}) 或不带 body = 不修改
  return out && typeof out.body === 'string' ? out.body : body;
}
const original = read('upstream/site/scripts/zhihu.ads.js');          // 上游原版（混淆）
// 上游开屏脚本 ddgksf2013/Scripts@0cddbb6 的 zhihu_openads.js，全文只有这一行（本仓库不再收录它，这里内联用于对照）
const openAds  = String.raw`var body=$response.body.replace(/img_play_duration\\":\d+/g,'img_play_duration":0').replace(/launch_timeout\\":\d+/g,'launch_timeout":0');$done({body});`;
const mine     = read('custom/zhihu.ads.js');                          // 自写可读版

const norm = (s) => { try { return JSON.stringify(JSON.parse(s)); } catch { return s; } };
const J = JSON.stringify;

console.log('\n[2] 脚本行为：自写版 vs 上游原版（相同输入，比较输出）');
const SAME = [
  ['推荐信息流：去掉广告', 'https://api.zhihu.com/topstory/recommend?x=1', J({ data: [
      { type: 'feed', id: 1 }, { type: 'feed_advert', id: 2 }, { id: 3, ad: { x: 1 } },
      { id: 4, promotion_extra: { a: 1 } }, { id: 5, extra: { type: 'pin' } },
      { id: 6, extra: { type: 'Training' } }, { type: 'feed', id: 7, extra: { type: 'answer' } }] })],
  ['热榜：去掉推广', 'https://api.zhihu.com/v2/topstory/hot-lists/total', J({ data: { data: [{ id: 1 }, { id: 2, promotion_extra: {} }] } })],
  ['回答页信息流', 'https://api.zhihu.com/next-data?id=1', J({ data: { data: [
      { resource_type: 'normal', data: { link_cards: [1, 2] } }, { resource_type: 'ad' }] } })],
  ['回答页翻页', 'https://api.zhihu.com/next-render?id=1', J({ data: [
      { type: 'answer', ad_info: { data: { x: 1 } } }, { type: 'answer', id: 2 }, { type: 'zvideo' }] })],
  ['搜索框推广词', 'https://api.zhihu.com/search/preset_words?x=1', J({ preset_words: {
      words: [{ w: 'a', begin_ts: 1, end_ts: 2 }], force_words: [{ begin_ts: 1, end_ts: 2 }] } })],
  ['消息：去掉活动助手', 'https://api.zhihu.com/notifications/v3/message', J({ data: [{ detail_title: '活动助手' }, { detail_title: '赞同', id: 2 }] })],
];
for (const [name, url, body] of SAME) {
  const a = norm(run(original, url, body)), b = norm(run(mine, url, body));
  check(`一致  ${name}`, a === b, a === b ? '' : `\n        原版: ${a}\n        自写: ${b}`);
}

// 开屏：上游 zhihu.ads.js 只认 real_time_launch，launch_v2 实际由 zhihu_openads.js 处理；替换逻辑完全相同
const LAUNCH = '{"x":"{\\"img_play_duration\\":5000,\\"launch_timeout\\":300,\\"keep\\":1}"}';
{
  const a = run(openAds, 'https://api.zhihu.com/commercial_api/launch_v2?x=1', LAUNCH);
  const b = run(mine,    'https://api.zhihu.com/commercial_api/launch_v2?x=1', LAUNCH);
  check('一致  开屏 launch_v2（对照上游 zhihu_openads.js）', a === b, a === b ? '' : `\n        上游: ${a}\n        自写: ${b}`);
  check('开屏  展示时长与超时已被改写', a !== LAUNCH && b !== LAUNCH);
  const c = run(original, 'https://api.zhihu.com/commercial_api/real_time_launch', LAUNCH);
  const d = run(mine,     'https://api.zhihu.com/commercial_api/real_time_launch', LAUNCH);
  check('一致  开屏 real_time_launch（对照上游 zhihu.ads.js）', c === d, c === d ? '' : `\n        上游: ${c}\n        自写: ${d}`);
}

console.log('\n    已知且有意的差异（自写版没有这些行为）：');
const KNOWN = [
  ['按关键词过滤推荐（副业/赚钱…）', 'https://api.zhihu.com/topstory/recommend?x=1',
   J({ data: [{ type: 'common_card', id: 1, common_card: { feed_content: { title: { panel_text: '副业赚钱' } } } }] })],
  ['改写「官方帐号消息」的已读状态', 'https://api.zhihu.com/notifications/v3/message',
   J({ data: [{ detail_title: '官方帐号消息', unread_count: 3, content: { text: 'x' } }] })],
  ['伪装盐选会员', 'https://api.zhihu.com/people/self', J({ vip_info: { is_vip: false } })],
  ['改写盐值分数', 'https://api.zhihu.com/user-credit/basis', J({ credit_basis: { total_score: 100 } })],
  ['注入作者 Telegram 链接', 'https://api.zhihu.com/bazaar/vip_tab/header', J({ vip_tip: { text: 'x' } })],
];
for (const [name, url, body] of KNOWN) {
  const a = norm(run(original, url, body)), b = norm(run(mine, url, body));
  const diff = a !== b;
  console.log(`      ${diff ? '不同' : '相同'}  ${name}${diff && /telegram|t\.me/i.test(a) ? '（原版输出含 t.me 链接）' : ''}`);
  assert(diff, `预期有差异但没有：${name}`);
}

// ---------------------------------------------------------------- 3. 容错
console.log('\n[3] 容错');
for (const [name, url, body] of [
  ['响应体不是 JSON', 'https://api.zhihu.com/topstory/recommend', '<html>502 Bad Gateway</html>'],
  ['响应体为空',      'https://api.zhihu.com/topstory/recommend', ''],
  ['data 不是数组',   'https://api.zhihu.com/topstory/recommend', '{"data":null}'],
  ['缺少字段',        'https://api.zhihu.com/v2/topstory/hot-lists/total', '{}'],
  ['未知接口',        'https://api.zhihu.com/whatever', '{"a":1}'],
]) {
  let out, err = null;
  try { out = run(mine, url, body); } catch (e) { err = e; }
  check(`放行  ${name}`, !err && out === body, err ? String(err) : '');
}

console.log(`\n结果：${pass} 项通过，${fail} 项失败`);
process.exit(fail ? 1 : 0);
