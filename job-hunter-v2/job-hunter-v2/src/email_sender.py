"""
求职雷达 · 邮件发送模块 (v2.0)
============================================================
更新：
  - 前 TOP_DISPLAY 个岗位完整展示（按评分排序）
  - 剩余岗位折叠在 <details> 区域
  - 🟢 有真实链接（已验证来源）/ 🟡 仅有官网链接 / ⚪ 无链接
  - 邮件卡片链接直接跳转到岗位页或公司招聘官网
"""

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")

TOP_DISPLAY = int(os.environ.get("TOP_JOBS_DISPLAY", "30"))


# ============================================================
# 评分标签与颜色
# ============================================================

def _score_label(score: int) -> tuple:
    """返回 (emoji, label, color)"""
    if score >= 85:
        return "⭐", "强烈推荐", "#e8521a"
    elif score >= 70:
        return "👍", "推荐", "#2563eb"
    elif score >= 60:
        return "✅", "值得申请", "#059669"
    else:
        return "📌", "可以考虑", "#64748b"


def _url_badge(job: dict) -> str:
    """根据url_type返回真实性标注HTML"""
    url_type = job.get("url_type", "none")
    has_url = job.get("has_url", False)

    if not has_url:
        return '<span style="background:#f1f5f9;color:#94a3b8;padding:1px 6px;border-radius:4px;font-size:11px;">⚪ 暂无链接</span>'

    if url_type == "job_page":
        return '<span style="background:#dcfce7;color:#16a34a;padding:1px 6px;border-radius:4px;font-size:11px;">🟢 岗位直链</span>'
    elif url_type == "career_page":
        return '<span style="background:#fef9c3;color:#854d0e;padding:1px 6px;border-radius:4px;font-size:11px;">🟡 招聘官网</span>'
    else:  # fallback
        return '<span style="background:#f0f9ff;color:#0369a1;padding:1px 6px;border-radius:4px;font-size:11px;">🔵 公司官网</span>'


def _apply_type_badge(apply_type: str) -> str:
    if apply_type == "internship":
        return '<span style="background:#f0f9ff;color:#0369a1;font-size:11px;padding:1px 6px;border-radius:4px;">实习</span>'
    else:
        return '<span style="background:#f0fdf4;color:#15803d;font-size:11px;padding:1px 6px;border-radius:4px;">全职</span>'


def _source_badge(source: str) -> str:
    if "定向" in source:
        return '<span style="background:#f5f3ff;color:#7c3aed;font-size:11px;padding:1px 6px;border-radius:4px;">定向搜索</span>'
    else:
        return '<span style="background:#fff7ed;color:#c2410c;font-size:11px;padding:1px 6px;border-radius:4px;">关键词搜索</span>'


# ============================================================
# 单个岗位卡片 HTML
# ============================================================

def _render_job_card(job: dict, is_top: bool = True) -> str:
    score = job.get("score", 55)
    emoji, label, color = _score_label(score)
    url = job.get("url", "")
    title = job.get("title", "未知职位")
    company = job.get("company", "未知公司")
    location = job.get("location", "郑州")
    salary = job.get("salary", "面议")
    experience = job.get("experience", "")
    education = job.get("education", "")
    apply_type = job.get("apply_type", "fulltime")
    source = job.get("source", "")
    comment = job.get("score_reason", "")

    border_color = "#e2e8f0" if not is_top else color
    bg_color = "#ffffff" if is_top else "#f8fafc"

    link_btn = ""
    if url:
        url_type = job.get("url_type", "none")
        btn_text = "查看岗位详情 →" if url_type == "job_page" else "公司招聘官网 →"
        link_btn = f'''
        <a href="{url}" style="color:{color};font-size:13px;text-decoration:none;font-weight:500;">
          {btn_text}
        </a>'''

    comment_html = ""
    if comment:
        comment_html = f'''
        <p style="margin:6px 0 0 0;font-size:12px;color:#64748b;font-style:italic;">
          💬 {comment}
        </p>'''

    return f'''
    <div style="background:{bg_color};border:1px solid {border_color};border-left:4px solid {color};
                border-radius:8px;padding:14px 16px;margin-bottom:10px;">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">
        <div style="flex:1;">
          <span style="font-size:15px;font-weight:600;color:#1e293b;">{title}</span>
          &nbsp;{_apply_type_badge(apply_type)}
        </div>
        <div style="text-align:right;flex-shrink:0;margin-left:12px;">
          <span style="font-size:22px;font-weight:700;color:{color};">{score}分</span><br>
          <span style="font-size:11px;color:{color};">{emoji} {label}</span>
        </div>
      </div>
      <p style="margin:0 0 4px 0;font-size:13px;color:#475569;">
        <strong>{company}</strong> · {location} · <strong>{salary}</strong>
      </p>
      <p style="margin:0 0 6px 0;font-size:12px;color:#64748b;">
        经验: {experience or "无要求"} &nbsp;|&nbsp; 学历: {education or "不限"}
      </p>
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        {_url_badge(job)}
        {_source_badge(source)}
        {link_btn}
      </div>
      {comment_html}
    </div>'''


# ============================================================
# 构建完整邮件 HTML
# ============================================================

def build_email_html(jobs: list, run_date: str, total_scraped: int,
                     new_companies: list = None) -> str:

    # 按评分降序排列
    sorted_jobs = sorted(jobs, key=lambda x: x.get("score", 0), reverse=True)
    top_jobs = sorted_jobs[:TOP_DISPLAY]
    rest_jobs = sorted_jobs[TOP_DISPLAY:]

    total = len(jobs)
    highlight_count = sum(1 for j in jobs if j.get("score", 0) >= 60)
    verified_count = sum(1 for j in jobs if j.get("url_type") == "job_page")
    career_count = sum(1 for j in jobs if j.get("url_type") in ("career_page", "fallback"))

    # 顶部统计栏
    stats_html = f'''
    <div style="background:#1e293b;color:#f1f5f9;padding:16px 20px;border-radius:10px;margin-bottom:20px;">
      <h2 style="margin:0 0 8px 0;font-size:18px;">📡 求职雷达日报</h2>
      <p style="margin:0;font-size:13px;color:#94a3b8;">{run_date} &nbsp;·&nbsp;
        共找到 <strong style="color:#fff;">{total_scraped}</strong> 条有搜索证据的岗位 &nbsp;·&nbsp;
        推送 <strong style="color:#fff;">{total}</strong> 个新岗位
      </p>
      <div style="margin-top:10px;display:flex;gap:16px;flex-wrap:wrap;font-size:12px;">
        <span>⭐ 推荐岗位（≥60分）: <strong style="color:#fbbf24;">{highlight_count}</strong></span>
        <span>🟢 岗位直链: <strong style="color:#4ade80;">{verified_count}</strong></span>
        <span>🟡 招聘官网: <strong style="color:#fde68a;">{career_count}</strong></span>
      </div>
    </div>'''

    # 推荐岗位区（≥60分）
    recommended = [j for j in top_jobs if j.get("score", 0) >= 60]
    other_top = [j for j in top_jobs if j.get("score", 0) < 60]

    rec_html = ""
    if recommended:
        rec_html = '<h3 style="color:#1e293b;margin:0 0 10px 0;font-size:15px;">⭐ 推荐岗位（评分 ≥ 60）</h3>'
        for job in recommended:
            rec_html += _render_job_card(job, is_top=True)

    other_top_html = ""
    if other_top:
        other_top_html = '<h3 style="color:#475569;margin:16px 0 10px 0;font-size:15px;">📋 其他岗位</h3>'
        for job in other_top:
            other_top_html += _render_job_card(job, is_top=False)

    # 折叠区（第31名以后）
    fold_html = ""
    if rest_jobs:
        inner = ""
        for job in rest_jobs:
            inner += _render_job_card(job, is_top=False)
        fold_html = f'''
    <details style="margin-top:16px;">
      <summary style="cursor:pointer;font-size:14px;color:#475569;padding:10px 14px;
                      background:#f1f5f9;border-radius:8px;list-style:none;user-select:none;">
        ▶ 查看更多岗位（共 {len(rest_jobs)} 个，评分较低或超出前{TOP_DISPLAY}名）
      </summary>
      <div style="margin-top:10px;">
        {inner}
      </div>
    </details>'''

    # 新发现公司
    new_co_html = ""
    if new_companies:
        items = "".join(
            f'<li style="margin-bottom:4px;font-size:13px;">{c.get("name","")}</li>'
            for c in new_companies
        )
        new_co_html = f'''
    <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
                padding:12px 16px;margin-top:16px;">
      <p style="margin:0 0 6px 0;font-weight:600;font-size:13px;color:#15803d;">
        🏢 自动学习：新加入白名单的公司
      </p>
      <ul style="margin:0;padding-left:18px;">{items}</ul>
    </div>'''

    footer = '''
    <p style="text-align:center;color:#94a3b8;font-size:11px;margin-top:20px;padding-top:12px;
              border-top:1px solid #e2e8f0;">
      由求职雷达自动生成 · 运行于 GitHub Actions<br>
      🟢 岗位直链 = 真实职位页面 &nbsp;|&nbsp; 🟡 招聘官网 = 公司招聘首页（需自行搜索具体职位）<br>
      如需调整筛选条件，请修改 config.py
    </p>'''

    return f'''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             max-width:680px;margin:0 auto;padding:20px;background:#f8fafc;color:#1e293b;">
  <div style="background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
    {stats_html}
    {rec_html}
    {other_top_html}
    {fold_html}
    {new_co_html}
    {footer}
  </div>
</body>
</html>'''


# ============================================================
# 发送邮件
# ============================================================

def send_email(jobs: list, run_date: str, total_scraped: int,
               new_companies: list = None) -> bool:
    """发送求职日报邮件"""
    if not all([GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_RECIPIENT]):
        print("[邮件] 缺少邮件配置，跳过发送")
        return False

    date_str = datetime.now().strftime("%m/%d")
    highlight = sum(1 for j in jobs if j.get("score", 0) >= 60)
    subject = f"📡 求职雷达 {date_str} · {len(jobs)} 个新岗位（{highlight} 个推荐）"

    html_body = build_email_html(
        jobs=jobs,
        run_date=run_date,
        total_scraped=total_scraped,
        new_companies=new_companies or [],
    )

    msg = MIMEMultipart("alternative")
    msg["From"] = GMAIL_USER
    msg["To"] = EMAIL_RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.sendmail(GMAIL_USER, EMAIL_RECIPIENT, msg.as_bytes())
        print(f"[邮件] 发送成功 → {EMAIL_RECIPIENT}")
        return True
    except Exception as e:
        print(f"[邮件] 发送失败: {e}")
        return False
