"""
求职雷达 - 全局配置
所有可调整的参数集中在这里，部署后只需改这一个文件
"""

# ── 求职画像（AI评分依据）──────────────────────────────────────────────
PROFILE = {
    "name": "杨振京",
    "education": "英国谢菲尔德大学 信息管理 硕士在读（2025-2026），预计2027年初拿证",
    "undergraduate": "信息管理与信息系统 本科",
    "skills": ["数据分析", "Tableau", "Excel", "Figma", "信息管理", "项目协调",
               "JavaWeb", "HTML/CSS", "Python基础", "信息系统", "ERP基础"],
    "languages": "英语日常交流，不支持纯英文面试",
    "status": "在读硕士，可接受实习 + 应届全职",
    "available_from": "2026年8月",
    "target_city": "郑州",
    "min_salary_fulltime": 5000,  # 全职最低月薪（元）
    "min_salary_intern": 2000,    # 实习最低月薪（元，可适当放宽）
    "exclude_keywords": ["流水线", "工厂操作工", "普工", "车间工人", "生产线"],
}

# ── 搜索关键词 ──────────────────────────────────────────────────────────
SEARCH_KEYWORDS = [
    # 实习类
    "数据分析实习", "信息管理实习", "运营实习", "咨询实习",
    "项目助理实习", "管培生实习", "业务分析实习",
    # 全职类
    "数据分析师", "业务分析", "信息化专员", "ERP实施",
    "IT支持", "运营专员", "项目助理", "供应链运营",
    "管理培训生", "数字化运营", "系统分析",
]

# 郑州城市代码（前程无忧）
CITY_CODE_51JOB = "101180100"
# 郑州城市名（猎聘）
CITY_LIEPIN = "郑州"

# ── 公司白名单（优先推送这些公司的岗位）──────────────────────────────
# 完整白名单在 data/company_whitelist.json，这里是关键词快速匹配列表
PRIORITY_COMPANY_KEYWORDS = [
    # 外企
    "富士康", "鸿海", "施耐德", "西门子", "飞利浦", "ABB", "博世",
    "麦当劳", "百胜", "肯德基", "必胜客", "可口可乐",
    "辉瑞", "阿斯利康", "强生", "拜耳", "诺华", "赛诺菲",
    "渣打", "汇丰", "三星", "IBM", "惠普", "HP",
    # 四大
    "普华永道", "PwC", "德勤", "Deloitte", "毕马威", "KPMG", "安永", "EY",
    # 国内大厂
    "华为", "新华三", "H3C", "阿里", "菜鸟", "京东", "字节", "美团", "海康",
    # 郑州本土优质
    "宇通", "牧原", "蜜雪", "中原银行", "郑州银行", "中铁装备",
]

# ── GitHub Actions 定时设置 ────────────────────────────────────────────
# UTC时间，北京时间 = UTC+8
# 周二、三、四的北京时间9:00 = UTC 01:00
CRON_SCHEDULE = "0 1 * * 2,3,4"

# ── 邮件配置（从环境变量读取，不要硬写在这里）─────────────────────────
import os
GMAIL_USER = os.environ.get("GMAIL_USER", "")          # 你的Gmail地址
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")  # App专用密码
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", GMAIL_USER)  # 收件人，默认自己

# ── Gemini API ──────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"  # 免费档，每天250次足够

# ── 数据文件路径 ────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SENT_JOBS_FILE = os.path.join(DATA_DIR, "sent_jobs.json")
COMPANY_WHITELIST_FILE = os.path.join(DATA_DIR, "company_whitelist.json")
DISCOVERED_COMPANIES_FILE = os.path.join(DATA_DIR, "discovered_companies.json")
