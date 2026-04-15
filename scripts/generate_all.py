#!/usr/bin/env python3
"""
History Tells — 批量生成全年 365 天历史事件
用法：GLM_API_KEY=xxx python3 scripts/generate_all.py
进度实时写入 index.html，中断后重跑会自动跳过已有日期
"""

import os
import re
import sys
import json
import time
import calendar
from openai import OpenAI

HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "index.html")

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


def get_existing_dates(html):
    pairs = re.findall(r'\{\s*month:(\d+),day:(\d+),', html)
    return {(int(m), int(d)) for m, d in pairs}


def generate_event(month, day, retry=3):
    for attempt in range(retry):
        try:
            resp = client.chat.completions.create(
                model="glm-4-plus",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content":
                        f"请为 {month}月{day}日 生成一个「历史上的今天」词条。\n"
                        f"必须是真实发生在 {month}月{day}日 的历史事件，选择最具普世意义的那个。\n"
                        f"输出纯 JSON，无任何其他内容。"}
                ],
                max_tokens=2000,
                temperature=0.7
            )
            raw = resp.choices[0].message.content.strip()

            # 去除可能的 ```json ``` 包裹
            if raw.startswith("```"):
                raw = re.sub(r'^```(?:json)?\n?', '', raw)
                raw = re.sub(r'\n?```$', '', raw.strip())

            event = json.loads(raw)

            required = ["month","day","year","title","description","figures","impact","insight","reading"]
            if any(k not in event for k in required):
                raise ValueError(f"缺少字段")

            # 强制修正日期
            event["month"] = month
            event["day"]   = day
            return event

        except Exception as e:
            print(f"  [重试 {attempt+1}/{retry}] 错误: {e}")
            time.sleep(3)
    return None


def js_str(s):
    return s.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n')


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


def inject(html, new_line):
    PRIMARY  = re.compile(r'(\n\];\s*//\s*END_EVENTS\n)', re.MULTILINE)
    FALLBACK = re.compile(r'(\n\];\n\nconst QUOTES)', re.MULTILINE)
    match = PRIMARY.search(html) or FALLBACK.search(html)
    if not match:
        raise RuntimeError("找不到 EVENTS 数组结尾标记")
    pos = match.start() + 1
    return html[:pos] + new_line + ",\n" + html[pos:]


# ── 主流程 ────────────────────────────────────────────────────────────────────
# 生成全年所有日期（以 2024 闰年为准，包含 2/29）
all_dates = []
for m in range(1, 13):
    for d in range(1, calendar.monthrange(2024, m)[1] + 1):
        all_dates.append((m, d))

with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

existing = get_existing_dates(html)
missing  = [(m, d) for m, d in all_dates if (m, d) not in existing]

total   = len(missing)
success = 0
failed  = []

print(f"✅ 已有事件：{len(existing)} 天")
print(f"📋 待生成：{total} 天")
print("─" * 50)

for i, (month, day) in enumerate(missing, 1):
    print(f"[{i}/{total}] 生成 {month}月{day}日 ...", end=" ", flush=True)

    event = generate_event(month, day)
    if not event:
        print("❌ 失败，跳过")
        failed.append((month, day))
        continue

    # 每次注入前重新读文件（确保增量写入正确）
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    new_line = serialize_event(event)
    html = inject(html, new_line)

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    success += 1
    print(f"✅ {event['title'][:30]}...")

    # 避免触发限流，每次间隔 1 秒
    time.sleep(1)

print("─" * 50)
print(f"✅ 成功：{success} 天  ❌ 失败：{len(failed)} 天")
if failed:
    print(f"失败日期：{failed}")

sys.exit(0 if not failed else 1)
