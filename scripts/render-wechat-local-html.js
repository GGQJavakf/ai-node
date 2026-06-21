const fs = require("fs");
const path = require("path");

function usage() {
  console.error("Usage: node scripts/render-wechat-local-html.js <article.md> <output.html>");
  process.exit(2);
}

const [, , articleArg, outputArg] = process.argv;
if (!articleArg || !outputArg) {
  usage();
}

const articlePath = path.resolve(articleArg);
const outputPath = path.resolve(outputArg);
const raw = fs.readFileSync(articlePath, "utf8");

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function inlineMarkdown(value) {
  return escapeHtml(value).replace(/\*\*(.+?)\*\*/g, '<strong style="color:#576b95;font-weight:700;">$1</strong>');
}

let title = "未命名文章";
let author = "";
let digest = "";
let body = raw;

const frontmatterMatch = raw.match(/^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n([\s\S]*)$/);
if (frontmatterMatch) {
  const frontmatter = frontmatterMatch[1];
  body = frontmatterMatch[2];
  for (const line of frontmatter.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z0-9_-]+):\s*["']?(.+?)["']?\s*$/);
    if (!match) continue;
    if (match[1] === "title") title = match[2];
    if (match[1] === "author") author = match[2];
    if (match[1] === "digest") digest = match[2];
  }
}

const blocks = [];
let paragraph = [];
let ordered = [];

function flushParagraph() {
  if (!paragraph.length) return;
  blocks.push(`  <p style="margin:0 0 9px;font-size:16px;line-height:1.72;color:#2b2f36;">${paragraph.join("<br />")}</p>`);
  paragraph = [];
}

function flushOrdered() {
  if (!ordered.length) return;
  const items = ordered.map((item) => `<li style="margin:0 0 6px;font-size:16px;line-height:1.72;color:#2b2f36;">${item}</li>`).join("");
  blocks.push(`  <section style="margin:10px 0 12px;padding:12px 14px;background:#fbfbfc;border:1px solid #e6e8ef;border-radius:6px;"><ol style="margin:0;padding-left:1.25em;color:#2b2f36;font-size:16px;line-height:1.72;">${items}</ol></section>`);
  ordered = [];
}

for (const rawLine of body.split(/\r?\n/)) {
  const line = rawLine.trimEnd().replace(/\s{2,}$/, "");
  if (!line.trim()) {
    flushParagraph();
    flushOrdered();
    continue;
  }

  const image = line.match(/^!\[(.*?)\]\((.*?)\)\s*$/);
  if (image) {
    flushParagraph();
    flushOrdered();
    const alt = escapeHtml(image[1]);
    const src = escapeHtml(image[2]);
    blocks.push(`  <p style="margin:12px 0 4px;text-align:center;line-height:1.5;"><img src="${src}" alt="${alt}" style="max-width:100%;height:auto;border-radius:6px;display:block;margin:0 auto;" /></p>`);
    if (alt) {
      blocks.push(`  <p style="margin:0 0 12px;text-align:center;color:#888;font-size:13px;line-height:1.5;">${alt}</p>`);
    }
    continue;
  }

  const heading = line.match(/^(#{1,3})\s+(.+)$/);
  if (heading) {
    flushParagraph();
    flushOrdered();
    blocks.push(`  <h2 style="margin:18px 0 10px;padding:0 0 0 9px;border-left:4px solid #576b95;font-size:18px;line-height:1.38;font-weight:700;color:#1f2937;">${inlineMarkdown(heading[2])}</h2>`);
    continue;
  }

  const chineseOrdered = line.match(/^[一二三四五六七八九十]，(.+)$/);
  if (chineseOrdered) {
    flushParagraph();
    ordered.push(inlineMarkdown(chineseOrdered[1]));
    continue;
  }

  paragraph.push(inlineMarkdown(line));
}

flushParagraph();
flushOrdered();

const digestBlock = digest
  ? `  <section style="margin:0 0 12px;padding:10px 12px;border-left:4px solid #576b95;background:#f7f8fb;border-radius:6px;color:#3f4652;">\n    <p style="margin:0;font-size:15px;line-height:1.6;color:#3f4652;">${escapeHtml(digest)}</p>\n  </section>\n`
  : "";

const html = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(title)}</title>
  <style>
    body { margin: 0; background: #ffffff; }
    @media (max-width: 520px) { .article-wrap { padding: 16px 14px !important; } }
  </style>
</head>
<body>
<section class="article-wrap" style="max-width:760px;margin:0 auto;padding:18px 16px;background:#ffffff;font-size:16px;line-height:1.72;color:#2b2f36;letter-spacing:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Arial,sans-serif;box-sizing:border-box;">
${digestBlock}
${blocks.join("\n")}
</section>
</body>
</html>
`;

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, html, "utf8");
console.log(JSON.stringify({ success: true, output: outputPath, bytes: Buffer.byteLength(html) }, null, 2));
