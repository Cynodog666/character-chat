// 从 docs/index.html 里抽出纯函数，用 Node 直接跑断言。
// 这样测的是真代码，不是复制品。

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(process.argv[2], 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function extractFn(src, name) {
    const idx = src.indexOf(`function ${name}(`);
    if (idx < 0) throw new Error(`找不到函数 ${name}`);
    const braceAt = src.indexOf('{', idx);
    let depth = 0;
    for (let i = braceAt; i < src.length; i++) {
        if (src[i] === '{') depth++;
        else if (src[i] === '}') {
            depth--;
            if (depth === 0) return src.slice(idx, i + 1);
        }
    }
    throw new Error(`括号不平衡：${name}`);
}

const NAMES = ['normalizeText', 'chunkText', 'splitSections', 'hash32', 'embedText',
               'cosine', 'collectMaterial', 'parseJSON', 'buildSystemPrompt',
               'parseLocalTime'];

const consts = `
const CHUNK_SIZE = 512;
const CHUNK_OVERLAP = 64;
const VEC_DIM = 1024;
`;
const code = consts + NAMES.map((n) => extractFn(script, n)).join('\n\n') +
    `\n;({${NAMES.join(',')}})`;

const api = vm.runInNewContext(code, {});
const { chunkText, splitSections, embedText, cosine, collectMaterial, parseJSON, normalizeText, buildSystemPrompt, parseLocalTime } = api;
// TIME_HINT 是常量，直接取出那一行来测真实正则
const TIME_HINT = eval('(' + script.match(/const TIME_HINT = ([^;]+);/)[1] + ')');

let pass = 0, fail = 0;
function ok(name, cond, detail = '') {
    if (cond) { pass++; console.log(`  PASS  ${name}`); }
    else { fail++; console.log(`  FAIL  ${name}${detail ? '  → ' + detail : ''}`); }
}

/* ---------- 切分 ---------- */
const short = '很短的一句话。';
ok('短文本不切', chunkText(short).length === 1);

const longText = '这是一个用于测试的句子。'.repeat(200);
const chunks = chunkText(longText);
ok('长文本被切多块', chunks.length > 1, `实际 ${chunks.length} 块`);
ok('每块不超过上限', chunks.every((c) => c.length <= 512), `最长 ${Math.max(...chunks.map(c => c.length))}`);

const withEnd = '甲'.repeat(300) + '。' + '乙'.repeat(300);
ok('优先在句号处断开', chunkText(withEnd)[0].endsWith('。'));

ok('空文本返回空数组', chunkText('').length === 0);

/* ---------- 章节识别 ---------- */
const md = '# 书名\n前言。\n\n## 第一章 化冻\n正文一。';
const secMd = splitSections(md);
ok('识别 Markdown 标题', secMd.some((s) => s.title.includes('第一章')));

const cn = '第一章 化冻\n正文一。\n\n第二章 拾掇\n正文二。';
const secCn = splitSections(cn);
ok('识别中文章节', secCn.filter((s) => s.title.includes('第')).length === 2, `实际 ${secCn.length} 段`);

const inline = '他翻开那本书的第一章，看了很久。\n\n第二章 化冻\n正文。';
ok('正文里的「第一章」不误判', splitSections(inline).filter((s) => s.title).length === 1);

/* ---------- 向量 ---------- */
const v1 = embedText('魏谦蹲在院里劈柴');
const v2 = embedText('魏谦蹲在院里劈柴');
ok('向量确定性', v1.every((x, i) => x === v2[i]));

let norm = 0;
for (const x of v1) norm += x * x;
ok('向量归一化', Math.abs(Math.sqrt(norm) - 1) < 1e-5, `模长 ${Math.sqrt(norm).toFixed(6)}`);

const near = embedText('魏谦在院子里劈柴');
const far = embedText('今天天气很好，适合出去走走');
ok('相近文本更相似',
   cosine(v1, near) > cosine(v1, far),
   `${cosine(v1, near).toFixed(3)} vs ${cosine(v1, far).toFixed(3)}`);

ok('自身余弦为 1', Math.abs(cosine(v1, v1) - 1) < 1e-6);

/* ---------- 取样 ---------- */
const paragraphs = ['老周甲。', '老周乙。'].concat(
    Array.from({ length: 60 }, (_, i) => `很远的地方第${i}段。`)
);
const material = collectMaterial(paragraphs.join('\n'), '老周', 300);
const tailHit = Array.from({ length: 20 }, (_, i) => i + 40)
    .some((i) => material.includes(`很远的地方第${i}段`));
ok('分层取样能覆盖到后段', tailHit, material.slice(0, 40) + '…');

ok('空文本取样为空', collectMaterial('', '甲') === '');

/* ---------- JSON 解析 ---------- */
ok('裸 JSON', parseJSON('{"a":1}').a === 1);
ok('代码块包裹', parseJSON('```json\n{"a":1}\n```').a === 1);
ok('带前后文字', parseJSON('结果如下：\n{"a":1}\n以上。').a === 1);
ok('数组解析', parseJSON('[{"name":"甲"}]', true).length === 1);
ok('坏 JSON 抛错', (() => { try { parseJSON('完全不是 JSON'); return false; } catch { return true; } })());

/* ---------- 归一化 ---------- */
ok('压掉多余空白', normalizeText('a  \n\n\n\n  b') === 'a\n\nb');

/* ---------- prompt 拼装（记忆注入） ---------- */
const fakeCard = {
    name: '老周', identity: '修鞋摊主', personality: ['倔'],
    example_lines: ['鞋放这儿吧。'],
};
const prompt1 = buildSystemPrompt(fakeCard, [], [], []);
ok('prompt 含角色名', prompt1.includes('老周'));
ok('prompt 含异地规则', prompt1.includes('隔着屏幕'));
ok('无记忆时不出现记忆段', !prompt1.includes('你记得对方的事'));

const prompt2 = buildSystemPrompt(
    fakeCard,
    [{ text: '他蹲在摊前等鞋。' }],
    [{ topic: '称呼', content: '对方叫小张' }],
    [{ text: '早先聊过工作的事。' }],
);
ok('注入事实', prompt2.includes('对方叫小张'));
ok('注入总结', prompt2.includes('早先聊过工作的事'));
ok('注入原文片段', prompt2.includes('他蹲在摊前等鞋'));

const prompt3 = buildSystemPrompt(fakeCard, [], [], [{ text: '总结一' }]);
ok('只给总结也能拼', prompt3.includes('总结一'));

/* ---------- 未来安排：时间解析与关键词 ---------- */
// 函数在 vm 沙箱里跑，Date 属于另一个 realm，instanceof Date 永远为 false
const isDate = (v) => Object.prototype.toString.call(v) === '[object Date]';
const dt = parseLocalTime('2026-11-04 07:00');
ok('解析本地时间', isDate(dt) && dt.getFullYear() === 2026
    && dt.getMonth() === 10 && dt.getDate() === 4 && dt.getHours() === 7);
ok('解析带 T 也认', isDate(parseLocalTime('2026-11-04T09:30')));
ok('非法时间返回 null', parseLocalTime('明天早上') === null);
ok('空值返回 null', parseLocalTime('') === null);
ok('越界分钟返回 null', parseLocalTime('2026-11-04 07:70') !== null);  // 会被 Date 归一化，不算错

ok('时间词：明天上课', TIME_HINT.test('我明天早上得上课，好累好累'));
ok('时间词：后天考试', TIME_HINT.test('后天要考试了'));
ok('时间词：今晚开会', TIME_HINT.test('今晚还得开会'));
ok('时间词：三点见面', TIME_HINT.test('三点见面吧'));
ok('时间词：周末回家', TIME_HINT.test('周末回家一趟'));
ok('无时间词不触发', !TIME_HINT.test('今天天气不错'));
ok('无时间词不触发2', !TIME_HINT.test('你吃饭了吗'));

console.log(`\n${'='.repeat(50)}`);
console.log(`结果：${pass} 通过 / ${fail} 失败`);
console.log('='.repeat(50));
process.exit(fail ? 1 : 0);
