"""
求职雷达 · AI评分模块 (v2.2 - 实习专项版)
改动：
  - 排除列表扩充（纯销售/体力/中介/财务记账/法务/设计）
  - 车企销售保留（不在黑名单）
  - 全职岗位直接压低到20分以下
  - 管培生/小型会计事务所审计降分处理
  - 评分profile更新为实习导向
"""

import os
import re
import json
import time

from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

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
]

# ---------- 直接排除的岗位关键词 ----------
# 注意：不包含"销售"本身，车企销售保留
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

# ---------- 降分场景关键词 ----------
# 匹配到这些词时基础分减15（不直接排除）
DOWNGRADE_KEYWORDS = [
    "管培生", "管理培训生",           # 需核实是否含数据轮岗
    "小型会计事务所", "普通合伙",     # 小所审计含金量低
    "销售",                            # 非车企销售降分（车企后续靠AI区分）
]

# ---------- 车企关键词（命中则销售岗不降分）----------
CAR_COMPANY_KEYWORDS = [
    "汽车", "车", "宇通", "比亚迪", "上汽", "一汽", "吉利", "长安",
    "奔驰", "宝马", "奥迪", "丰田", "本田", "大众", "福特", "沃尔沃",
]

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
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

        # 命中排除关键词 → 直接丢弃
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
    combined = title + company
    note = ""

    # 全职岗位：压低到20分以下（只搜实习，全职属漏网）
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
            f"  经验要求: {job.get('experience','')}\n"
            f"  学历要求: {job.get('education','')}\n"
            f"  类型: {job.get('apply_type','')}\n"
        )

    return f"""You are a professional career advisor. Score each internship opportunity for this candidate.

## Candidate Profile
- Education: MSc Information Management, University of Sheffield (2025-2026, graduating 2026)
- Undergraduate: Information Management & Information Systems, China
- Skills: Python, Tableau, Excel, Figma, data analysis, SQL basics
- Language: Native Chinese, conversational English (IELTS 5.5)
- Status: 2026/2027 fresh graduate, available for internship from August 2026
- Target city: Zhengzhou, China
- Priority: INTERNSHIP positions only. Full-time roles are not currently sought.

## Scoring Criteria
- Internship relevance to data analysis / information management / consulting / operations
- Company reputation and learning value
- Skill match with candidate profile
- Entry-level / no experience requirements preferred

## Jobs to Score ({len(jobs)} total)
{jobs_text}

## Instructions
Score each job 0-100:
- 85-100: Excellent internship match, highly recommended
- 70-84: Good match, worth applying
- 55-69: Partial match, consider carefully  
- 0-54: Poor match or full-time role

Return ONLY valid JSON, no other text:
{{
  "results": [
    {{
      "index": 1,
      "score": 85,
      "reason": "One sentence explaining the score in Chinese"
    }}
  ]
}}"""


def score_jobs_with_gemini(jobs: list) -> list:
    if not jobs:
        return []

    if not GEMINI_API_KEY:
        print("[AI评分] 未配置 GEMINI_API_KEY，所有岗位默认50分")
        for job in jobs:
            job["score"] = 50
            job["score_reason"] = "未配置AI评分"
        return jobs

    # 预过滤：排除明显不符合的岗位
    jobs = _pre_filter(jobs)
    print(f"[AI评分] 预过滤后剩余 {len(jobs)} 个岗位")

    batch_size = 30
    all_scored = []

    for batch_start in range(0, len(jobs), batch_size):
        batch = jobs[batch_start: batch_start + batch_size]
        print(f"[AI评分] 评分批次 {batch_start//batch_size + 1}，共 {len(batch)} 个岗位")

        prompt = _build_scoring_prompt(batch)

        try:
            client = _get_client()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

            raw = (response.text or "{}").strip()
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

                # 合并评分理由
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
                job["score_reason"] = f"评分出错: {str(e)[:40]}"
                all_scored.append(job)

        if batch_start + batch_size < len(jobs):
            time.sleep(3)

    all_scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = all_scored[0].get("score", 0) if all_scored else 0
    print(f"[AI评分] ✓ 评分完成，最高分: {top}")
    return all_scored
