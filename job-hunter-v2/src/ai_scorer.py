"""
求职雷达 · AI评分模块 (v3.1 - Kimi thinking版)
改动：
  - 评分调用显式开启 thinking 模式（budget_tokens=2000）
  - thinking 模式不与 $web_search 冲突，评分场景可安全使用
  - max_tokens 调高至 6000，为 thinking 推理过程预留空间
  - 其余逻辑（过滤规则、降分策略、白名单加分）保持不变
"""

import os
import re
import json
import time

from openai import OpenAI

KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
MODEL = "kimi-k2.5"
BASE_URL = "https://api.moonshot.cn/v1"

# thinking 模式配置（评分专用，不用于搜索）
THINKING_ENABLED = {"thinking": {"type": "enabled", "budget_tokens": 2000}}

# ---------- 求职者画像 ----------
PROFILE = {
    "education": "英国谢菲尔德大学信息管理硕士（在读，2025-2026）",
    "undergraduate": "河南财经政法大学信息管理与信息系统（专升本）",
    "skills": ["Python", "Tableau", "Excel", "Figma", "JavaWeb", "数据分析", "SQL基础"],
    "languages": "中文母语，英语可沟通（IELTS 5.5）",
    "status": "2026届/2027届应届生，2026年8月可开始实习",
    "target_city": "郑州",
    "focus": "实习岗位优先，全职暂不考虑",
}

# ---------- 白名单公司（定向加分）----------
PRIORITY_COMPANIES = [
    "安永", "EY", "毕马威", "KPMG", "普华永道", "PwC", "德勤", "Deloitte",
    "施耐德", "Schneider", "西门子", "Siemens", "ABB", "博世", "Bosch",
    "飞利浦", "Philips", "强生", "辉瑞", "Pfizer", "阿斯利康", "AstraZeneca",
    "渣打", "华为", "新华三", "H3C", "富士康", "宇通", "蜜雪", "中原银行",
    "美团", "字节跳动", "阿里", "腾讯", "京东", "百度", "中国银行", "工商银行",
    "建设银行", "农业银行", "招商银行", "平安", "中国移动", "中国联通", "中国电信",
    "海尔", "联想", "用友", "金蝶", "华润", "中粮", "牧原", "宇通客车",
]

# ---------- 直接排除的岗位关键词 ----------
EXCLUDE_KEYWORDS = [
    # 体力/现场类
    "工厂实习", "生产实习", "设备巡检", "车间", "流水线", "装配", "生产工人",
    # 中介性质
    "猎头", "HR外包", "招聘实习", "灵活用工",
    # 纯销售类（地推性质，非车企）
    "地推", "BD实习", "业务拓展实习", "扫楼", "陌生拜访",
    # 财务记账类
    "出纳实习", "会计助理", "记账实习", "做账",
    # 法务类
    "法务助理", "法律助理实习",
    # 设计类
    "平面设计", "UI设计实习", "视觉设计实习", "美工实习",
    # 其他明显不符
    "司机", "保安", "厨师", "保洁",
]

# ---------- 车企关键词（命中则销售岗不降分）----------
CAR_COMPANY_KEYWORDS = [
    "汽车", "车", "宇通", "比亚迪", "上汽", "一汽", "吉利", "长安",
    "奔驰", "宝马", "奥迪", "丰田", "本田", "大众", "福特", "沃尔沃",
]

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=KIMI_API_KEY, base_url=BASE_URL)
    return _client


def _is_priority_company(company: str) -> bool:
    company_lower = company.lower()
    for p in PRIORITY_COMPANIES:
        if p.lower() in company_lower:
            return True
    return False


def _is_car_company(company: str) -> bool:
    for kw in CAR_COMPANY_KEYWORDS:
        if kw in company:
            return True
    return False


def _pre_filter(jobs: list) -> list:
    """直接排除明显不符合的岗位。"""
    result = []
    for job in jobs:
        title = job.get("title", "")
        company = job.get("company", "")
        combined = title + company

        if any(kw in combined for kw in EXCLUDE_KEYWORDS):
            print(f"  [过滤] 排除: {title} @ {company}")
            continue

        result.append(job)
    return result


def _pre_score_adjust(job: dict, base_score: int) -> tuple:
    """
    评分前的规则调整，返回 (adjusted_score, adjustment_note)
    """
    title = job.get("title", "")
    company = job.get("company", "")
    apply_type = job.get("apply_type", "")
    note = ""

    # 全职岗位：压低到18分以下
    if apply_type == "fulltime":
        return min(base_score, 18), "全职岗位，当前仅寻找实习"

    # 销售岗 + 非车企 → 降分
    if "销售" in title and not _is_car_company(company):
        base_score = max(0, base_score - 20)
        note = "非车企销售岗，降分处理"

    # 管培生 → 降分并备注
    if any(kw in title for kw in ["管培生", "管理培训生"]):
        base_score = max(0, base_score - 10)
        note = "管培生岗位，需核实是否含数据分析轮岗"

    # 小型会计事务所审计 → 降分
    if "审计" in title and any(kw in company for kw in ["普通合伙", "特殊普通合伙"]):
        base_score = max(0, base_score - 15)
        note = "小型会计事务所审计，含金量相对较低"

    return base_score, note


def _build_scoring_prompt(jobs: list) -> str:
    jobs_text = ""
    for i, job in enumerate(jobs):
        jobs_text += (
            f"\n岗位{i+1}:\n"
            f"  职位: {job.get('title','')}\n"
            f"  公司: {job.get('company','')}\n"
            f"  薪资: {job.get('salary','')}\n"
            f"  地点: {job.get('location','')}\n"
            f"  来源平台: {job.get('source_platform','')}\n"
            f"  经验要求: {job.get('experience','')}\n"
            f"  学历要求: {job.get('education','')}\n"
            f"  类型: {job.get('apply_type','')}\n"
        )

    return f"""你是专业的职业规划顾问。请认真分析以下实习岗位，对候选人进行匹配度评分。

## 候选人画像
- 学历：英国谢菲尔德大学信息管理硕士（在读，2025-2026，2026届毕业）
- 本科：信息管理与信息系统（专升本，河南财经政法大学）
- 技能：Python、Tableau、Excel、Figma、数据分析、SQL基础
- 语言：中文母语，英语可沟通（雅思5.5，不适合全英文工作环境）
- 状态：2026/2027届应届生，2026年8月起可实习
- 目标城市：郑州
- 求职重点：实习岗位为主，全职暂不考虑

## 待评分岗位（共{len(jobs)}个）
{jobs_text}

## 评分标准（0-100分）
- 85-100分：非常匹配，强烈推荐申请
- 70-84分：较好匹配，值得申请
- 55-69分：部分匹配，谨慎考虑
- 0-54分：匹配度低（含全职岗位）

## 评分重点考量
1. 岗位方向是否与数据分析/信息管理/咨询/运营/审计相关
2. 公司知名度、规模和实习学习价值
3. 经验/学历要求是否适合应届硕士生
4. 全职岗位直接低分（<20分）
5. 英语要求高的岗位适当降分（候选人英语为可沟通水平）

请仔细思考每个岗位的匹配情况后再给出评分，评分理由用中文简要说明。

仅返回合法JSON，不要任何其他文字：
{{
  "results": [
    {{
      "index": 1,
      "score": 85,
      "reason": "用中文简要说明评分理由（1-2句话）"
    }}
  ]
}}"""


def score_jobs_with_gemini(jobs: list) -> list:
    """保持函数名不变（被main.py调用），内部已切换为Kimi + thinking模式。"""
    if not jobs:
        return []

    if not KIMI_API_KEY:
        print("[AI评分] 未配置 KIMI_API_KEY，所有岗位默认50分")
        for job in jobs:
            job["score"] = 50
            job["score_reason"] = "未配置AI评分"
        return jobs

    # 预过滤：排除明显不符合的岗位
    jobs = _pre_filter(jobs)
    print(f"[AI评分] 预过滤后剩余 {len(jobs)} 个岗位")

    batch_size = 20
    all_scored = []

    for batch_start in range(0, len(jobs), batch_size):
        batch = jobs[batch_start: batch_start + batch_size]
        print(f"[AI评分] 评分批次 {batch_start // batch_size + 1}，共 {len(batch)} 个岗位（thinking模式）")

        prompt = _build_scoring_prompt(batch)

        try:
            client = _get_client()
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "你是职业规划顾问，请认真分析后只返回JSON，不要任何其他文字。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=6000,            # thinking 推理过程占用额外 token
                extra_body=THINKING_ENABLED,  # 开启 thinking，提升评分质量
            )

            raw = (response.choices[0].message.content or "{}").strip()
            raw = re.sub(r"^```json?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw).strip()

            result = json.loads(raw)
            scores = {r["index"]: r for r in result.get("results", [])}
            print(f"[AI评分] 解析到 {len(scores)} 条评分")

            for i, job in enumerate(batch):
                score_data = scores.get(i + 1, {})
                base_score = score_data.get("score", 50)
                ai_reason = score_data.get("reason", "")

                # 规则调整（全职压分、管培降分等）
                adjusted_score, rule_note = _pre_score_adjust(job, base_score)

                # 白名单公司加分（仅实习岗位）
                bonus = 0
                if job.get("apply_type") != "fulltime" and _is_priority_company(job.get("company", "")):
                    bonus = 10

                final_score = min(100, adjusted_score + bonus)

                reason_parts = []
                if ai_reason:
                    reason_parts.append(ai_reason)
                if rule_note:
                    reason_parts.append(f"[{rule_note}]")
                if bonus:
                    reason_parts.append("[重点目标公司+10分]")

                job["score"] = final_score
                job["score_reason"] = " ".join(reason_parts)
                all_scored.append(job)

        except Exception as e:
            print(f"[AI评分] 评分失败: {e}")
            for job in batch:
                bonus = 10 if _is_priority_company(job.get("company", "")) else 0
                adjusted, rule_note = _pre_score_adjust(job, 50)
                job["score"] = min(100, adjusted + bonus)
                job["score_reason"] = f"评分出错: {str(e)[:60]}"
                all_scored.append(job)

        if batch_start + batch_size < len(jobs):
            time.sleep(5)  # 批次间间隔，避免限流

    all_scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = all_scored[0].get("score", 0) if all_scored else 0
    print(f"[AI评分] ✓ 评分完成（thinking模式），最高分: {top}")
    return all_scored
