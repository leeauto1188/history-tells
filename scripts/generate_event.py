#!/usr/bin/env python3
"""
History Tells — 每日历史事件自动生成脚本
运行时间：22:00 UTC = 北京时间 06:00（次日）
逻辑：检查今日是否已有事件 → 无则调用 GLM API 生成 → 注入 index.html
"""

import os
import re
import sys
import json
import datetime
from openai import OpenAI

# ── 路径配置 ─────────────────────────────────────────────────────────────────
HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "index.html")

# ── Step 1：确定目标日期（CST = UTC+8）───────────────────────────────────────
utc_now = datetime.datetime.utcnow()
cst_now = utc_now + datetime.timedelta(hours=8)
target_month = cst_now.month
target_day   = cst_now.day

print(f"[INFO] 目标日期（CST）：{target_month}月{target_day}日")

# ── Step 2：读取 index.html，检查是否已有当日事件 ─────────────────────────────
with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

existing_pairs = re.findall(r'\{\s*month:(\d+),day:(\d+),', html)
existing_dates = {(int(m), int(d)) for m, d in existing_pairs}

if (target_month, target_day) in existing_dates:
    print(f"[SKIP] {target_month}/{target_day} 已有事件，跳过生成。")
    sys.exit(0)

print(f"[INFO] 未找到 {target_month}/{target_day} 的事件，开始生成...")

# ── Step 3：调用 GLM API ──────────────────────────────────────────────────────
client = OpenAI(
    api_key=os.environ["GLM_API_KEY"],
    base_url="https://open.bigmodel.cn/api/paas/v4/"
)

SYSTEM_PROMPT = """你是「History Tells」的首席历史编辑。这是一个以「以史鉴今」为核心理念的精品历史应用，面向有深度思考需求的中文读者。

你的任务是为指定的日期（月/日）选择并撰写一个历史事件词条。

**写作原则：**
1. 选择真实发生、有据可查的历史事件，优先选择重大性、深远影响、知名度高者
2. 叙述风格：严谨而不枯燥，有温度、有细节、有画面感。避免教科书腔
3. description 必须分为2-4段，段落间用 \\n\\n 分隔，每段150-250字，要有具体细节、人物行为、现场感
4. impact：聚焦客观历史影响，2-3句话，具体而非泛泛
5. insight：这是本品牌的灵魂。必须连接历史与当代，尤其是科技、商业、AI、组织管理视角。200字以内，要有洞见，不要说废话
6. figures：只列真实的关键人物，每人写清楚具体角色，不要超过4人
7. reading：推荐2-4本真实存在的书或纪录片，格式「《书名》— 作者」或「纪录片《名称》」
8. title：格式「事件核心——精炼的一句话点评」，例如：「达·芬奇诞生——文艺复兴最完整的人类」

**风格参考（已有词条的 insight 示例）：**
- 霍金诞生：「身体的局限不等于思想的局限。在AI时代，当机器能替代大部分体力和事务性工作后，深度思考的能力变得更加珍贵。」
- 泰坦尼克沉没：「「不可能失败」是最危险的想法。过度自信导致的风险管理缺失，是灾难最常见的前奏。为「不可能发生」的事情做准备，才是真正的专业主义。」
- 柏林墙倒塌：「看似坚不可摧的体制可以一夜崩塌。柏林墙不是被军事力量推倒的，而是被信息流动和人心思变瓦解的。」

**输出要求：**
严格返回合法的 JSON，不要包含任何其他文字、代码块标记或解释：
{
  "month": <整数>,
  "day": <整数>,
  "year": "<年份字符串，如 1945年 或 前221年>",
  "title": "<事件核心——精炼点评>",
  "description": "<第一段\\n\\n第二段\\n\\n第三段>",
  "figures": [{"name": "<人名>", "role": "<具体角色描述>"}],
  "impact": "<历史影响，2-3句>",
  "insight": "<以史鉴今洞见，200字内>",
  "reading": ["<《书名》— 作者>"]
}"""

USER_PROMPT = f"""请为 {target_month}月{target_day}日 生成一个「历史上的今天」词条。

要求：
- 必须是真实发生在 {target_month}月{target_day}日 的历史事件
- 优先选择在该日期最具重大意义的事件（政治、科技、文化、战争、经济均可）
- 若该日期有多个重要事件，选择最具普世意义、最能引发当代思考的那个

输出纯 JSON，无任何其他内容。"""

response = client.chat.completions.create(
    model="glm-4-plus",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": USER_PROMPT}
    ],
    max_tokens=2000,
    temperature=0.7
)

raw = response.choices[0].message.content.strip()

# ── Step 4：解析并验证 JSON ───────────────────────────────────────────────────
# 兼容模型有时会返回 ```json ... ``` 包裹的情况
if raw.startswith("```"):
    raw = re.sub(r'^```(?:json)?\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw.strip())
    raw = raw.strip()

try:
    event = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"[ERROR] JSON 解析失败: {e}")
    print(f"[RAW] {raw[:500]}")
    sys.exit(1)

required_fields = ["month", "day", "year", "title", "description", "figures", "impact", "insight", "reading"]
missing = [k for k in required_fields if k not in event]
if missing:
    print(f"[ERROR] 缺少字段: {missing}")
    sys.exit(1)

# 确保日期与目标一致
if event["month"] != target_month or event["day"] != target_day:
    print(f"[WARN] 模型返回日期 ({event['month']}/{event['day']}) 与目标 ({target_month}/{target_day}) 不符，已覆盖。")
    event["month"] = target_month
    event["day"]   = target_day

print(f"[INFO] 生成事件：{event['title']}")

# ── Step 5：序列化为 JS 对象字面量（与现有风格一致）───────────────────────────
def js_str(s):
    return (s
        .replace('\\', '\\\\')
        .replace('"', '\\"')
        .replace('\n', '\\n'))

def serialize_event(e):
    figures_js = ",".join(
        f'{{name:"{js_str(f["name"])}",role:"{js_str(f["role"])}"}}'
        for f in e["figures"]
    )
    reading_js = ",".join(f'"{js_str(r)}"' for r in e["reading"])
    return (
        f'  {{ month:{e["month"]},day:{e["day"]},year:"{js_str(e["year"])}",'
        f'title:"{js_str(e["title"])}",'
        f'description:"{js_str(e["description"])}",'
        f'figures:[{figures_js}],'
        f'impact:"{js_str(e["impact"])}",'
        f'insight:"{js_str(e["insight"])}",'
        f'reading:[{reading_js}]}}'
    )

new_line = serialize_event(event)

# ── Step 6：注入 index.html ───────────────────────────────────────────────────
PRIMARY  = re.compile(r'(\n\];\s*//\s*END_EVENTS\n)', re.MULTILINE)
FALLBACK = re.compile(r'(\n\];\n\nconst QUOTES)', re.MULTILINE)

match = PRIMARY.search(html) or FALLBACK.search(html)
if not match:
    print("[ERROR] 无法在 index.html 中定位 EVENTS 数组结尾，注入失败。")
    sys.exit(1)

insert_pos = match.start() + 1
new_html = html[:insert_pos] + new_line + ",\n" + html[insert_pos:]

# ── Step 7：写回文件 ──────────────────────────────────────────────────────────
with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(new_html)

print(f"[OK] 已注入事件：{event['title']}")
print(f"[OK] index.html 已更新（{len(new_html)} 字节）")
