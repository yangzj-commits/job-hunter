"""
状态管理模块
负责读写已推送岗位的历史记录，防止重复推送
数据通过 git commit 持久化到仓库，跨次运行保持记忆
"""

import json
import os
import hashlib
from datetime import datetime, timedelta
from config import SENT_JOBS_FILE, DATA_DIR


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_sent_jobs() -> set:
    """读取历史已推送岗位ID集合"""
    _ensure_data_dir()
    if not os.path.exists(SENT_JOBS_FILE):
        return set()
    try:
        with open(SENT_JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("job_ids", []))
    except Exception:
        return set()


def save_sent_jobs(job_ids: set):
    """保存已推送岗位ID集合，同时清理90天前的旧记录"""
    _ensure_data_dir()
    # 读取现有记录（含时间戳，用于清理旧数据）
    existing = {}
    if os.path.exists(SENT_JOBS_FILE):
        try:
            with open(SENT_JOBS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing = data.get("job_ids_with_time", {})
        except Exception:
            pass

    cutoff = (datetime.now() - timedelta(days=90)).isoformat()
    # 清理超过90天的旧记录
    existing = {k: v for k, v in existing.items() if v >= cutoff}
    # 新增本次推送的记录
    now = datetime.now().isoformat()
    for jid in job_ids:
        existing[jid] = now

    result = {
        "updated_at": now,
        "job_ids": list(existing.keys()),
        "job_ids_with_time": existing,
    }
    with open(SENT_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[状态管理] 已保存 {len(existing)} 条历史记录")


def make_job_id(job: dict) -> str:
    """根据岗位关键字段生成唯一ID（防止因URL变化导致重复推送）"""
    key = f"{job.get('company','')}-{job.get('title','')}-{job.get('source','')}"
    return hashlib.md5(key.encode()).hexdigest()


def filter_new_jobs(jobs: list) -> list:
    """过滤掉已推送过的岗位，返回新岗位列表"""
    sent = load_sent_jobs()
    new_jobs = []
    for job in jobs:
        jid = make_job_id(job)
        job["_id"] = jid
        if jid not in sent:
            new_jobs.append(job)
    print(f"[去重] 共 {len(jobs)} 个岗位，过滤已推送后剩 {len(new_jobs)} 个新岗位")
    return new_jobs
