"""
求职雷达 · AI评分模块
用 Gemini 对每个岗位进行匹配度评分
"""

import os
import re
import json
import time

from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

# 求职者画像
PROFILE = {
    "education": "英国谢菲尔德大学信息管理硕士（在读，2025-2026）",
    "undergraduate": "河南财经政法大学信息管理与信息系统（专升本）",
    "skills": ["Python", "Tableau", "Excel", "Figma", "JavaWeb", "数据分析", "SQL基础"],
    "languages": "中文母语，英语可沟通（IELTS 5.5）",
    "status": "应届硕士，2026年8月可入职",
    "target_city": "郑州",
    "min_salary_fulltime": 5000,
    "exclude_keywords": ["流水线", "装配", "生产工人", "司机", "保安", "厨师"],
}

# 白名单公司（加分）
PRIORITY_COMPANIES = [
    "安永", "EY", "毕马威", "KPMG", "普华永道", "PwC", "德勤", "Deloitte",
    "施耐德", "Schneider", "西门子", "Siemens", "ABB", "博世", "Bosch",
    "飞利浦", "Philips", "强生", "辉瑞", "Pfizer", "阿斯利康", "AstraZeneca",
    "渣打", "华为", "新华三", "H3C", "富士康", "宇通", "蜜雪", "中原银行",
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


def _pre_filter(jobs: list) -> list:
    """规则预筛选：排除明显不匹配的岗位"""
    result = []
    for job in jobs:
        title = job.get("title", "") + job.get("company", "")
        if any(kw in title for kw in PROFILE["exclude_keywords"]):
            continue
        result.append(job)
    return result


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

    return f"""You are a professional career advisor. Score each job for this candidate.

## Candidate Profile
- Education: MSc Information Management, University of Sheffield (2025-2026, graduating 2026)
- Undergraduate: Information Management & Information Systems, China
- Skills: Python, Tableau, Excel, Figma, data analysis, SQL basics
- Language: Native Chinese, conversational English
- Status: Fresh graduate, available August 2026
- Target city: Zhengzhou, China
- Min salary (fulltime): 5000 CNY/month
- Excluded: assembly line, factory worker, driver, security guard

## Jobs to Score ({len(jobs)} total)
{jobs_text}

## Instructions
Score each job 0-100 based on fit:
- 80-100: Excellent match, highly recommended
- 60-79: Good match, worth applying
- 40-59: Partial match, consider carefully
- 0-39: Poor match, skip

Return ONLY valid JSON, no other text:
{{
  "results": [
    {{
      "index": 1,
      "score": 85,
      "reason": "One sentence explaining the score"
    }}
  ]
}}"""


def score_jobs_with_gemini(jobs: list) -> list:
    """用 Gemini API 批量评分所有岗位"""
    if not jobs:
        return []

    if not GEMINI_API_KEY:
        print("[AI评分] 未配置 GEMINI_API_KEY，所有岗位默认50分")
        for job in jobs:
            job["score"] = 50
            job["score_reason"] = "未配置AI评分"
        return jobs

    jobs = _pre_filter(jobs)
    batch_size = 30
    all_scored = []

    for batch_start in range(0, len(jobs), batch_size):
        batch = jobs[batch_start: batch_start + batch_size]
        print(f"[AI评分] 规则筛选: {len(jobs)} → {len(batch)} 个岗位")
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
                base_score = score_data.get("score", 55)
                bonus = 10 if _is_priority_company(job.get("company", "")) else 0
                job["score"] = min(100, base_score + bonus)
                job["score_reason"] = score_data.get("reason", "")
                all_scored.append(job)

        except Exception as e:
            print(f"[AI评分] 评分失败: {e}")
            for job in batch:
                bonus = 10 if _is_priority_company(job.get("company", "")) else 0
                job["score"] = 50 + bonus
                job["score_reason"] = f"评分出错: {str(e)[:40]}"
                all_scored.append(job)

        if batch_start + batch_size < len(jobs):
            time.sleep(3)

    all_scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = all_scored[0].get("score", 0) if all_scored else 0
    print(f"[AI评分] ✓ 评分完成，最高分: {top}")
    return all_scored
