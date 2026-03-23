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
            f"\nJob{i+1}: title={job.get('title','')}, "
            f"company={job.get('company','')}, "
            f"salary={job.get('salary','')}, "
            f"exp={job.get('experience','')}, "
            f"edu={job.get('education','')}\n"
        )

    return f"""Score these jobs for this candidate. Return ONLY a JSON array, no other text.

Candidate: Sheffield MSc Information Management student (2025-2026), skills: data analysis, Tableau, Excel, Figma, project coordination. Seeking internship or graduate jobs in Zhengzhou. Min salary 5000 CNY/month for fulltime.

Jobs to score:
{jobs_text}

Return this exact JSON format with no extra text:
[
  {{"index": 1, "score": 85, "reason": "good match", "apply_type": "internship"}},
  {{"index": 2, "score": 60, "reason": "ok match", "apply_type": "fulltime"}}
]

Score 80-100=strongly recommend, 60-79=worth applying, 40-59=consider, 0-39=skip."""


def _parse_score_response(text: str, batch_size: int) -> dict:
    """多层容错解析，尽力从响应中提取评分"""
    text = text.strip()

    # 尝试1: 直接解析
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return {item["index"]: item for item in data if "index" in item}
    except Exception:
        pass

    # 尝试2: 提取 [...] 部分
    try:
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if isinstance(data, list):
                return {item["index"]: item for item in data if "index" in item}
    except Exception:
        pass

    # 尝试3: 用正则逐条提取 index 和 score
    scores = {}
    pattern = r'"index"\s*:\s*(\d+).*?"score"\s*:\s*(\d+).*?"reason"\s*:\s*"([^"]*)".*?"apply_type"\s*:\s*"([^"]*)"'
    for m in re.finditer(pattern, text, re.DOTALL):
        idx = int(m.group(1))
        scores[idx] = {
            "index": idx,
            "score": int(m.group(2)),
            "reason": m.group(3),
            "apply_type": m.group(4),
        }
    if scores:
        return scores

    # 尝试4: 只提取 index 和 score
    scores = {}
    for m in re.finditer(r'"index"\s*:\s*(\d+)[^}]*"score"\s*:\s*(\d+)', text):
        idx = int(m.group(1))
        scores[idx] = {"index": idx, "score": int(m.group(2)), "reason": "", "apply_type": ""}
    return scores


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
    batch_size = 30
    all_scored = []

    for batch_start in range(0, len(jobs), batch_size):
        batch = jobs[batch_start: batch_start + batch_size]
        print(f"[AI筛选] 评分批次 {batch_start//batch_size + 1}，共 {len(batch)} 个岗位")

        prompt = _build_scoring_prompt(batch)
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 3000},
        }

        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            scores = _parse_score_response(text, len(batch))
            print(f"[AI筛选] 解析到 {len(scores)} 条评分")

            for i, job in enumerate(batch):
                idx = i + 1
                score_data = scores.get(idx, {})
                base_score = score_data.get("score", 55)
                bonus = 10 if _is_priority_company(job.get("company", "")) else 0
                job["score"] = min(100, base_score + bonus)
                job["score_reason"] = score_data.get("reason", "")
                job["apply_type"] = score_data.get("apply_type", "")
                all_scored.append(job)

        except Exception as e:
            print(f"[AI筛选] 评分失败: {e}")
            for job in batch:
                job["score"] = 55
                job["score_reason"] = ""
                job["apply_type"] = ""
                all_scored.append(job)

        if batch_start + batch_size < len(jobs):
            time.sleep(3)

    all_scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = all_scored[0].get("score", 0) if all_scored else 0
    print(f"[AI筛选] 评分完成，最高分: {top}")
    return all_scored
