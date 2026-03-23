"""
Gemini AI 评分模块
将所有岗位打包成一个请求批量评分，最大化利用免费额度
每天只需调用1次 API，完全在免费档（250次/天）范围内
"""

import json
import re
import time
import requests
from config import GEMINI_API_KEY, GEMINI_MODEL, PROFILE, PRIORITY_COMPANY_KEYWORDS


def _is_priority_company(company_name: str) -> bool:
    """检查是否是白名单优先公司"""
    return any(kw in company_name for kw in PRIORITY_COMPANY_KEYWORDS)


def _pre_filter(jobs: list[dict]) -> list[dict]:
    """
    在调用 AI 之前先做规则过滤，减少 API 调用量
    过滤掉明显不符合条件的岗位
    """
    filtered = []
    exclude_kws = PROFILE["exclude_keywords"]
    for job in jobs:
        title = job.get("title", "")
        # 排除明确不符合的岗位
        if any(kw in title for kw in exclude_kws):
            continue
        filtered.append(job)
    print(f"[AI筛选] 规则预筛选：{len(jobs)} → {len(filtered)} 个岗位")
    return filtered


def _build_scoring_prompt(jobs: list[dict]) -> str:
    """构建批量评分的 prompt"""
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
        )

    prompt = f"""你是一位专业的职业规划顾问。请根据下面的求职者背景，对每个岗位进行评分和分析。

## 求职者背景
- 学历：{PROFILE['education']}，{PROFILE['undergraduate']}
- 技能：{', '.join(PROFILE['skills'])}
- 语言：{PROFILE['languages']}
- 求职状态：{PROFILE['status']}
- 目标城市：{PROFILE['target_city']}
- 期望开始工作：{PROFILE['available_from']}
- 期望月薪：全职 {PROFILE['min_salary_fulltime']}元+，实习可接受更低
- 不希望的岗位：{', '.join(PROFILE['exclude_keywords'])}

## 待评估岗位列表（共 {len(jobs)} 个）
{jobs_text}

## 评分要求
对每个岗位返回 JSON 格式的评分结果，分数 0-100：
- 80-100：非常匹配，强烈推荐
- 60-79：基本匹配，值得申请
- 40-59：部分匹配，可以考虑
- 0-39：不匹配，跳过

评分考虑因素：
1. 岗位与信息管理/数据分析背景的匹配度
2. 是否适合应届生/实习生申请
3. 薪资是否符合期望（注意郑州薪资水平）
4. 发展前景
5. 是否排除项

请返回以下格式的 JSON（只返回 JSON，不要任何其他文字）：
{{
  "results": [
    {{
      "index": 1,
      "score": 85,
      "reason": "一句话说明评分依据",
      "apply_type": "实习/全职/均可"
    }},
    ...
  ]
}}"""
    return prompt


def score_jobs_with_gemini(jobs: list[dict]) -> list[dict]:
    """
    用 Gemini API 批量评分所有岗位
    将白名单优先公司的岗位额外加10分
    """
    if not jobs:
        return []
    if not GEMINI_API_KEY:
        print("[AI筛选] 未配置 GEMINI_API_KEY，跳过AI评分，所有岗位默认分数50")
        for job in jobs:
            job["score"] = 50
            job["score_reason"] = "未配置AI评分"
            job["apply_type"] = "未知"
        return jobs

    # 规则预筛选
    jobs = _pre_filter(jobs)

    # Gemini API 每次最多处理50个岗位（避免超出token限制）
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

            # 清理 markdown 代码块包裹
            text = re.sub(r"```json\s*|\s*```", "", text).strip()
            result = json.loads(text)
            scores = {r["index"]: r for r in result.get("results", [])}

            for i, job in enumerate(batch):
                idx = i + 1
                score_data = scores.get(idx, {})
                base_score = score_data.get("score", 50)
                # 白名单优先公司额外加分
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
            time.sleep(3)  # 批次间隔，避免触发速率限制

    # 按分数排序
    all_scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    print(f"[AI筛选] 评分完成，最高分: {all_scored[0].get('score', 0) if all_scored else 0}")
    return all_scored
