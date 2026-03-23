"""
求职雷达 · 状态管理模块
负责历史记录的加载、去重、保存
"""

import os
import json
import hashlib
from datetime import datetime


def make_job_id(job: dict) -> str:
    """生成岗位唯一ID（公司+职位名的MD5）"""
    key = f"{job.get('company','').strip()}-{job.get('title','').strip()}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def load_history(history_path: str) -> dict:
    """加载已推送的岗位历史记录"""
    if not os.path.exists(history_path):
        return {}
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            # 兼容旧格式（list）
            return {make_job_id(item): item for item in data}
        return data
    except Exception as e:
        print(f"[状态管理] 加载历史记录失败: {e}")
        return {}


def filter_new_jobs(jobs: list, history: dict) -> list:
    """过滤掉已推送过的岗位，返回新岗位列表"""
    new_jobs = []
    for job in jobs:
        jid = make_job_id(job)
        if jid not in history:
            new_jobs.append(job)
    print(f"[去重] 共 {len(jobs)} 个岗位，过滤后剩 {len(new_jobs)} 个新岗位待推送")
    print(f"  ✓ 过滤完成：{len(new_jobs)} 个新岗位待推送")
    return new_jobs


def save_history(new_jobs: list, history: dict, history_path: str) -> dict:
    """将新推送的岗位写入历史记录"""
    updated = dict(history)
    today = datetime.now().strftime("%Y-%m-%d")

    for job in new_jobs:
        jid = make_job_id(job)
        updated[jid] = {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "source": job.get("source", ""),
            "pushed_date": today,
        }

    try:
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(updated, f, ensure_ascii=False, indent=2)
        print(f"[状态管理] 已保存 {len(updated)} 条历史记录，新增 {len(new_jobs)} 条")
    except Exception as e:
        print(f"[状态管理] 保存历史记录失败: {e}")

    return updated
