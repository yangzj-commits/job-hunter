import json
import re
import time
import requests
from config import GEMINI_API_KEY, GEMINI_MODEL, PROFILE, PRIORITY_COMPANY_KEYWORDS


def _is_priority_company(company_name: str) -> bool:
    return any(kw in company_name for kw in PRIORITY_COMPANY_KEYWORDS)


def _pre_filter(jobs: list) -> list:
    exclude_kws = PROFILE["exclude_keywords"]
    filtered = [j for j in jobs if not any(kw in j.get("title", "") for kw in exclude_kws)]
    print(f"[AI筛选] 规则预筛选：{len(jobs)} → {len(filtered)} 个岗位")
    return filtered


def _build_scoring_prompt(jobs: list) -> str:
    jobs_text = ""
    for i, job in enumerate(jobs):
        jobs_text += (
            f"\n岗位{i+1}:\n"
            f"  职位: {job.get('title','')}\n"
            f"  公司: {job.get('company','')}\n"
            f"  薪资: {job.get('salary','')}\n"
            f"  经验要求: {job.get('experience','')}\n"
            f"  学历要求: {job.get('education','')}\n"
        )

    return f"""你是职业规划顾问。根据求职者背景对每个岗位评分（0-100分）。

求职者背景：
- 学历：{PROFILE['education']}
- 技能：{', '.join(PROFILE['skills'])}
- 状态：{PROFILE['status']}，目标城市郑州
- 期望薪资：全职{PROFILE['min_salary_fulltime']}元+
- 排除：{', '.join(PROFILE['exclude_keywords'])}

待评估岗位（共{len(jobs)}个）：
{jobs_text}

评分标准：80-100强烈推荐，60-79值得申请，40-59可以考虑，0-39不匹配。

返回JSON（只返回JSON）：
{{
  "results": [
    {{
      "index": 1,
      "score": 85,
      "reason": "一句话评分依据",
      "apply_type": "实习/全职/均可"
    }}
  ]
}}"""


def score_jobs_with_gemini(jobs: list) -> list:
    if not jobs:
        return []
    if not GEMINI_API_KEY:
        print("[AI筛选] 未配置 GEMINI_API_KEY，默认分数50")
        for job in jobs:
            job["score"] = 50
            job["score_reason"] = "未配置AI评分"
            job["apply_type"] = "未知"
        return jobs

    jobs = _pre_filter(jobs)
    batch_size = 40
    all_scored = []

    for batch_start in range(0, len(jobs), batch_size):
        batch = jobs[batch_start: batch_start + batch_size]
        print(f"[AI筛选] 评分批次 {batch_start//batch_size + 1}，共 {len(batch)} 个岗位")

        prompt = _build_scoring_prompt(batch)
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        }

        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"```json\s*|\s*```", "", text).strip()
            result = json.loads(text)
            scores = {r["index"]: r for r in result.get("results", [])}

            for i, job in enumerate(batch):
                idx = i + 1
                score_data = scores.get(idx, {})
                base_score = score_data.get("score", 50)
                bonus = 10 if _is_priority_company(job.get("company", "")) else 0
                job["score"] = min(100, base_score + bonus)
                job["score_reason"] = score_data.get("reason", "")
                job["apply_type"] = score_data.get("apply_type", "")
                all_scored.append(job)

        except Exception as e:
            print(f"[AI筛选] 评分失败: {e}")
            for job in batch:
                job["score"] = 50
                job["score_reason"] = f"评分出错: {str(e)[:50]}"
                job["apply_type"] = "未知"
                all_scored.append(job)

        if batch_start + batch_size < len(jobs):
            time.sleep(3)

    all_scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    print(f"[AI筛选] 评分完成，最高分: {all_scored[0].get('score', 0) if all_scored else 0}")
    return all_scored
