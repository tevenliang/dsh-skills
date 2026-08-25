#!/usr/bin/env python3
"""
企业信息查询脚本
Business Information Query Script

使用腾讯元宝搜索（Tencent Yuanbao Search / 腾讯云 WSA）收集企业相关信息，
对国内企业检索更准。
依赖 tencent-yuanbao-search 技能的 websearch.py 脚本，鉴权靠环境变量
TENCENTCLOUD_WSA_APIKEY（已配置在 ~/.zshrc；本脚本会兜底自动读取）。

用法:
    python business_query.py <公司名称> [--type TYPE] [--count COUNT]

参数:
    公司名称    要查询的企业名称（必填）
    --type     查询类型：basic(默认)|shareholder|risk|finance|news|contact|all
    --count    返回结果数量，默认10条
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Dict, List


class BusinessSearch:
    """商业信息查询类"""

    # 预设的搜索模板
    SEARCH_TEMPLATES = {
        "basic": "{name} 工商信息 注册资本 成立时间 经营状态",
        "shareholder": "{name} 股东 法人代表 大股东 持股比例",
        "risk": "{name} 失信 被执行人 诉讼 行政处罚 经营异常",
        "finance": "{name} 融资 IPO 上市 投资 估值",
        "news": "{name} 最新 新闻 动态 媒体报道",
        "contact": "{name} 联系方式 地址 电话 官网",
    }

    def __init__(self):
        # 跨平台解析元宝搜索脚本路径（不再写死 Windows 路径）
        home = os.path.expanduser("~")
        candidates = [
            os.path.join(home, ".agents/skills/Search/tencent-yuanbao-search/scripts/websearch.py"),
            os.path.join(home, ".workbuddy/skills/Search/tencent-yuanbao-search/scripts/websearch.py"),
        ]
        self.search_script = next((p for p in candidates if os.path.exists(p)), candidates[0])

        # 运行元宝脚本的解释器：优先本机 /usr/bin/python3，回退 python3
        self.python = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else "python3"

        # 确保 API key 在环境中（兜底：从 ~/.zshrc 等读取）
        self._ensure_api_key()

    def _ensure_api_key(self):
        """若环境变量缺失，尝试从常见 rc/env 文件读取 TENCENTCLOUD_WSA_APIKEY。"""
        if os.getenv("TENCENTCLOUD_WSA_APIKEY"):
            return
        home = os.path.expanduser("~")
        for rc in [".zshrc", ".bashrc", ".bash_profile", ".env", ".agents/.env"]:
            path = os.path.join(home, rc)
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        m = re.search(
                            r'TENCENTCLOUD_WSA_APIKEY\s*=\s*["\']?([A-Za-z0-9_\-]+)',
                            line,
                        )
                        if m:
                            os.environ["TENCENTCLOUD_WSA_APIKEY"] = m.group(1)
                            return
            except Exception:
                continue

    @staticmethod
    def _parse_markdown(text: str) -> List[Dict]:
        """解析元宝 websearch.py 的 Markdown 输出为结构化列表。

        输出格式示例:
            N. [标题](url)
                - 摘要: 摘要文本
                - 内容发布时间: ...
                - 网站: ...
        """
        items: List[Dict] = []
        title_re = re.compile(r"^\d+\.\s+\[(?P<title>.+?)\]\((?P<url>.+?)\)\s*$")
        snippet_re = re.compile(r"^\s*-\s*摘要:\s*(?P<snippet>.+)")
        current = None
        for line in text.splitlines():
            mt = title_re.match(line)
            if mt:
                if current:
                    items.append(current)
                current = {"title": mt.group("title"), "url": mt.group("url"), "snippet": ""}
                continue
            if current is not None:
                ms = snippet_re.match(line)
                if ms:
                    current["snippet"] = ms.group("snippet").strip()
        if current:
            items.append(current)
        return items

    def search(self, query: str, count: int = 10) -> List[Dict]:
        """使用腾讯元宝搜索并返回结构化结果"""
        if not os.path.exists(self.search_script):
            print(
                f"未找到元宝搜索脚本: {self.search_script}\n"
                "请先确认 tencent-yuanbao-search 技能已安装。",
                file=sys.stderr,
            )
            return []

        cmd = [self.python, self.search_script, "--query", query]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                msg = result.stderr.strip() or result.stdout.strip()
                print(f"搜索出错: {msg[:300]}", file=sys.stderr)
                return []

            return self._parse_markdown(result.stdout)[:count]

        except subprocess.TimeoutExpired:
            print("搜索超时", file=sys.stderr)
            return []
        except Exception as e:
            print(f"搜索异常: {e}", file=sys.stderr)
            return []

    def query_company(
        self,
        company_name: str,
        query_type: str = "all",
        count: int = 10
    ) -> Dict[str, List]:
        """查询企业信息"""
        results = {}

        if query_type == "all":
            # 查询所有类型
            for qtype, template in self.SEARCH_TEMPLATES.items():
                query = template.format(name=company_name)
                print(f"[{qtype}] 查询: {query}")
                results[qtype] = self.search(query, count)
        else:
            # 查询指定类型
            template = self.SEARCH_TEMPLATES.get(query_type, self.SEARCH_TEMPLATES["basic"])
            query = template.format(name=company_name)
            results[query_type] = self.search(query, count)

        return results

    def format_report(self, company_name: str, results: Dict) -> str:
        """生成结构化报告"""
        report = []
        report.append("=" * 60)
        report.append(f"企业信息查询报告")
        report.append("=" * 60)
        report.append(f"查询对象: {company_name}")
        report.append(f"查询时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        type_names = {
            "basic": "【工商基本信息】",
            "shareholder": "【股东与法人信息】",
            "risk": "【经营风险信息】",
            "finance": "【融资上市信息】",
            "news": "【新闻动态】",
            "contact": "【联系方式】",
        }

        for qtype, data in results.items():
            report.append("")
            report.append(type_names.get(qtype, qtype))
            report.append("-" * 40)

            if not data:
                report.append("未找到相关信息")
                continue

            for item in data[:10]:
                if isinstance(item, dict):
                    title = item.get("title", "")
                    url = item.get("url", "")
                    snippet = item.get("snippet", "")
                    report.append(f"• {title}")
                    if snippet:
                        report.append(f"  {snippet[:200]}...")
                    report.append(f"  来源: {url}")
                else:
                    report.append(f"• {item}")
            report.append("")

        report.append("=" * 60)
        report.append("提示: 以上信息仅供参考，具体信息请以官方渠道为准")
        report.append("=" * 60)

        return "\n".join(report)


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    company_name = sys.argv[1]

    # 解析参数
    query_type = "all"
    count = 10

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--type" and i + 1 < len(sys.argv):
            query_type = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--count" and i + 1 < len(sys.argv):
            count = int(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    # 执行查询
    search = BusinessSearch()
    results = search.query_company(company_name, query_type, count)

    # 生成报告
    report = search.format_report(company_name, results)
    print(report)


if __name__ == "__main__":
    main()
