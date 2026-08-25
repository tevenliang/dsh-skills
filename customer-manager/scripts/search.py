#!/usr/bin/env python3
from __future__ import annotations
"""
customer-search CLI 主入口。

六种模式:
1. 单客户查询(默认): find-range-data 服务端模糊搜 + get_row 读完整 22 列
2. 列表查询(--list): 走全表缓存 + 多条件筛选
3. 本周安排查询(--this-week): 筛 下一步计划落在本周的客户
4. 外部级联查询(--cascade): Excel 命中 0 行时触发 天眼查 -> 天机商查 自动兜底
   企查查 MCP 无本地 auth 配置,跳过;有需求时用户手动调用 qcc-company skill

辅助 flag:
  --refresh    强制清除缓存
  --verbose    输出完整原文
  --empty      展示空字段
  --cascade    触发外部级联查询
"""

import argparse
import sys
import os
import subprocess
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from kdocs_client import find_customer_rows, get_row, get_file_info, get_full_sheet, FILE_ID
import cache
from formatter import (
    format_search_results,
    format_customer_summary,
    format_row_full,
)


# ─── 外部级联查询 ──────────────────────────────────────────────────────────

def cascade_lookup(keyword: str) -> str:
    results = {}
    errors = {}
    qcc_hit = False

    # Stage 1: qcc
    try:
        qcc_proc = subprocess.run(
            ["qcc", "company", "get_company_registration_info", keyword],
            capture_output=True, text=True, timeout=15,
        )
        if qcc_proc.returncode == 0 and qcc_proc.stdout.strip():
            out_lines = qcc_proc.stdout.strip().split("\n")
            info = {}
            for line in out_lines:
                if ":" in line and line.startswith("* "):
                    parts = line[2:].split(":", 1)
                    k = parts[0].strip()
                    v = parts[1].strip() if len(parts) > 1 else ""
                    if k and v:
                        info[k] = v
            if info:
                results["qcc"] = info
                qcc_hit = True
            elif "未匹配" in qcc_proc.stdout or "未查询到" in qcc_proc.stdout:
                errors["qcc"] = "企业未匹配"
        elif qcc_proc.stderr:
            err = qcc_proc.stderr.strip()
            if any(x in err for x in ["quota", "额度", "次数"]):
                errors["qcc"] = "企查查额度用尽"
            else:
                errors["qcc"] = err[:100]
    except FileNotFoundError:
        errors["qcc"] = "qcc CLI 未安装"
    except subprocess.TimeoutExpired:
        errors["qcc"] = "企查查调用超时"
    except Exception as e:
        errors["qcc"] = str(e)[:100]

    if qcc_hit:
        tr = _tianji_query(keyword)
        if tr:
            results["tianji"] = tr
        return _format_results(results, errors)

    # Stage 2: tyc
    tyc_hit = False
    try:
        sp = subprocess.run(
            ["tyc", "company", "companies", keyword, "--pageNum", "1", "--pageSize", "3"],
            capture_output=True, text=True, timeout=15,
        )
        candidates = []
        if sp.returncode == 0 and sp.stdout.strip():
            try:
                sd = json.loads(sp.stdout)
                for it in sd.get("items", []):
                    n = it.get("name", "")
                    if n:
                        candidates.append({"name": n, "status": it.get("regStatus",""),
                            "legal": it.get("legalPersonName",""), "capital": it.get("regCapital","")})
            except:
                pass
        exact = candidates[0]["name"] if candidates else keyword
        rp = subprocess.run(
            ["tyc", "company", "registration-info", exact],
            capture_output=True, text=True, timeout=15,
        )
        if rp.returncode == 0 and rp.stdout.strip():
            try:
                d = json.loads(rp.stdout)
                base = (d.get("sources", {}) or {}).get("base")
                if base and base.get("name") and not base.get("empty"):
                    results["tyc"] = {
                        "企业名称": base.get("name",""),
                        "统一社会信用代码": base.get("creditCode",""),
                        "法定代表人": base.get("legalPersonName",""),
                        "成立日期": base.get("estiblishTime",""),
                        "注册资本": base.get("regCapital",""),
                        "实缴资本": base.get("actualCapital",""),
                        "经营状态": base.get("regStatus",""),
                        "注册地址": base.get("regLocation",""),
                        "联系电话": base.get("phoneNumber",""),
                        "官网": base.get("websiteList",""),
                        "行业": base.get("industry",""),
                        "公司类型": base.get("companyOrgType",""),
                        "员工人数": base.get("staffNumRange",""),
                        "标签": base.get("tags",""),
                        "经营范围": (base.get("businessScope") or "")[:400],
                    }
                    tyc_hit = True
                    if len(candidates) > 1:
                        results["tyc"]["_candidates"] = candidates[1:]
                elif candidates:
                    results["tyc"] = {"_candidates": candidates, "_note": "详情未直接命中"}
                    tyc_hit = True
            except:
                pass
        elif rp.stderr:
            err = rp.stderr.strip()
            if any(x in err for x in ["quota","额度","次数"]):
                errors["tyc"] = "天眼查额度用尽"
            else:
                errors["tyc"] = err[:100]
    except FileNotFoundError:
        errors["tyc"] = "tyc CLI 未安装"
    except subprocess.TimeoutExpired:
        errors["tyc"] = "天眼查调用超时"
    except Exception as e:
        errors["tyc"] = str(e)[:100]

    if tyc_hit:
        tr = _tianji_query(keyword)
        if tr:
            results["tianji"] = tr
        return _format_results(results, errors)

    # Stage 3: Tianji fallback
    tr = _tianji_query(keyword)
    if tr:
        results["tianji"] = tr
    elif not results:
        errors["tianji"] = "天机商查也未返回结果"

    return _format_results(results, errors)


def _tianji_query(keyword: str):
    try:
        home = os.path.expanduser("~")
        script = os.path.join(home, ".agents/skills/Search/tianji-search/scripts/business_query.py")
        if not os.path.exists(script):
            return None
        py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else "python3"
        env = {**os.environ}
        env.pop("NO_VERBOSE", None)
        r = subprocess.run([py, script, keyword, "--type", "all", "--count", "5"],
                          capture_output=True, text=True, timeout=30, env=env)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()[:2000]
    except Exception:
        pass
    return None


def _format_results(results, errors):
    out = []
    if results:
        out.append("[*] 外部查询结果")
        out.append("")
        if "qcc" in results:
            out.append("**企查查(qcc):**")
            for k, v in results["qcc"].items():
                if v:
                    out.append("  " + k + ": " + v[:200])
            out.append("")
        if "tyc" in results:
            r = results["tyc"]
            if "_candidates" in r and not any(k for k in r if not k.startswith("_")):
                out.append("**天眼查(tyc):** " + r.get("_note",""))
                for i, c in enumerate(r["_candidates"], 1):
                    out.append("  " + str(i) + ". " + c["name"] + " | " + c["status"] + " | " + c.get("legal",""))
                out.append("")
            else:
                out.append("**天眼查(tyc):**")
                for label, val in r.items():
                    if label.startswith("_") or not val:
                        continue
                    out.append("  " + label + ": " + val)
                out.append("")
        if "tianji" in results:
            out.append("**天机商查(补全):**")
            out.append(results["tianji"][:1500])
            out.append("")
        if "shuidi" in results:
            out.append("**水滴信用(shuidi):**")
            for k, v in results["shuidi"].items():
                if v:
                    out.append("  " + k + ": " + v[:200])
            out.append("")
    if errors:
        if not results:
            out.append("[!]  所有渠道均未返回有效结果:")
            for src, err in errors.items():
                out.append("  - " + src + ": " + err)
        else:
            for src, err in errors.items():
                out.append("[W]  " + src + " 失败: " + err)
    txt = "\n".join(out).strip()
    return txt if txt else "[!]  外部查询渠道全部失败"


def search_single(keyword: str, verbose: bool = False, show_empty: bool = False) -> str:
    """
    单客户查询:服务端模糊搜 → 单行读 → 格式化输出。

    命中 0 行 → 提示调 --cascade 触发外部查询
    命中 1 行 → 完整 22 字段
    命中多行 → 列出全部,让用户重新搜
    """
    matches = find_customer_rows(keyword, col=0)

    if not matches:
        return (
            f"❌ 在 Excel 中未找到匹配「{keyword}」的客户。\n\n"
            f"💡 下一步:\n"
            f"   python3 scripts/search.py --cascade \"{keyword}\"\n"
            f"   (企查查 \u2192 天眼查 \u2192 天机商查,自动按序兜底)\n"
            f"   或直接说「帮我查 {keyword}」触发 AI 辅助外部查询"
        )

    if len(matches) == 1:
        row = matches[0]["row"]
        cells = get_row(row, 0, 21)
        name = matches[0]["value"]
        header = f"## ✅ 命中 1 行(行 {row + 1}):{name}\n"
        if verbose:
            return header + "\n" + format_row_full(cells)
        return header + "\n" + format_customer_summary(row, cells)

    # 命中多行(同名 / 共用关键字)
    output = [format_search_results(matches)]
    output.append(
        "\n💡 命中多个客户,请用更精确的关键词重新搜索"
        "\n   例:用全名「跨维（深圳）智能数字科技有限公司」而非简称「跨维」"
    )
    return "\n".join(output)


def _load_rows() -> list[dict]:
    """
    拉全表(优先缓存)+ 按行聚合,返回统一结构:
      [{"row", "name", "industry", "stage", "tag", "cells"}, ...]
    (跳过表头 row=0;cells 为该行全部 22 列的 cell 列表)
    """
    # 1. 取文件元信息
    info = get_file_info()
    current_mtime = info["mtime"]
    current_version = info["version"]

    # 2. 拿 cells(优先缓存)
    cells = cache.get_cells(FILE_ID, current_mtime, current_version)
    if cells is None:
        print(
            f"🔄 缓存失效(mtime={current_mtime}, version={current_version}),重读 Excel...",
            file=sys.stderr,
        )
        cells = get_full_sheet()
        cache.save(FILE_ID, current_mtime, current_version, cells)
        print(f"✅ 已更新缓存({len(cells)} cells)", file=sys.stderr)
    else:
        print(f"✅ 缓存命中({len(cells)} cells,mtime={current_mtime})", file=sys.stderr)

    # 3. 按行聚合
    rows_dict: dict[int, list[dict]] = {}
    for cell in cells:
        rows_dict.setdefault(cell["row"], []).append(cell)

    def get_val(row_cells: list[dict], col: int) -> str:
        for c in row_cells:
            if c["col"] == col:
                return (c.get("value") or "").strip()
        return ""

    # 4. 聚合(跳过表头 row=0)
    rows = []
    for row_idx in sorted(rows_dict.keys()):
        if row_idx == 0:
            continue
        row_cells = rows_dict[row_idx]
        rows.append({
            "row": row_idx,
            "name": get_val(row_cells, 0),
            "industry": get_val(row_cells, 1),
            "stage": get_val(row_cells, 2),
            "tag": get_val(row_cells, 3),
            "cells": row_cells,
        })
    return rows


def search_list(
    filter_industry: str | None = None,
    filter_stage: str | None = None,
    filter_tag: str | None = None,
    verbose: bool = False,
) -> str:
    """
    列表查询:全表缓存 + 多条件筛选。
    """
    rows = _load_rows()

    # 应用 filter
    matches = []
    for r in rows:
        if filter_industry and filter_industry not in r["industry"]:
            continue
        if filter_stage and filter_stage not in r["stage"]:
            continue
        if filter_tag and filter_tag not in r["tag"]:
            continue
        matches.append(r)

    # 输出
    if not matches:
        return "❌ 没有客户匹配筛选条件"

    lines = [f"✅ 找到 {len(matches)} 个客户:\n"]
    for m in matches:
        lines.append(
            f"  - 行 {m['row'] + 1}:{m['name']}\n"
            f"      行业={m['industry'] or '∅'} | "
            f"阶段={m['stage'] or '∅'} | "
            f"标签={m['tag'] or '∅'}"
        )

    if verbose:
        lines.append("\n\n--- 详细 22 字段 ---\n")
        for m in matches:
            lines.append(format_customer_summary(m["row"], m["cells"]))
            lines.append("\n---\n")

    return "\n".join(lines)


def search_this_week(
    week_date: str | None = None,
    verbose: bool = False,
) -> str:
    """
    本周安排查询(只读):筛 下一步计划(col 8, 0-based col 7)落在当周
    (周一~周日)的客户,按日期升序输出 日期 / 客户 / 阶段 / 下一步行动。

    week_date: 指定某天(YYYY-MM-DD),取该天所在周;缺省=本周。
    """
    import datetime

    base = datetime.date.fromisoformat(week_date) if week_date else datetime.date.today()
    # 以周一为一周起点
    monday = base - datetime.timedelta(days=base.weekday())
    sunday = monday + datetime.timedelta(days=6)
    week_start, week_end = monday.isoformat(), sunday.isoformat()

    rows = _load_rows()
    matches = []
    for r in rows:
        due = next((c.get("value", "").strip() for c in r["cells"] if c["col"] == 7), "")
        if not due:
            continue
        try:
            datetime.date.fromisoformat(due)
        except ValueError:
            continue  # 非日期值(如自由文本)跳过
        if not (week_start <= due <= week_end):
            continue
        action = next((c.get("value", "").strip() for c in r["cells"] if c["col"] == 8), "")
        matches.append({**r, "due": due, "action": action})

    if not matches:
        return f"✅ 本周({week_start}~{week_end})没有排客户任务"

    matches.sort(key=lambda m: m["due"])
    lines = [f"📅 本周安排({week_start}~{week_end}) 共 {len(matches)} 个客户任务:\n"]
    for m in matches:
        lines.append(
            f"  - {m['due'][5:]} ({m['due']}) {m['name']}\n"
            f"      阶段={m['stage'] or '∅'} | 下一步行动={m['action'] or '∅'}"
        )

    if verbose:
        lines.append("\n\n--- 详细 22 字段 ---\n")
        for m in matches:
            lines.append(format_customer_summary(m["row"], m["cells"]))
            lines.append("\n---\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="customer-search: 在云端 Excel 中搜索客户并返回完整 22 字段",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 search.py 跨维                       # 模糊搜单个客户
  python3 search.py 路演中 --verbose           # 模糊搜 + 输出完整原文
  python3 search.py --list                     # 列出所有客户
  python3 search.py --list --industry 互联网   # 按行业筛选
        python3 search.py --list --stage 机会        # 按销售阶段筛选
  python3 search.py --refresh --list           # 强制刷新缓存
  python3 search.py --this-week                # 本周安排查询
  python3 search.py --this-week --week 2026-08-17  # 指定某周
        """,
    )
    parser.add_argument(
        "keyword", nargs="?", default="",
        help="客户名关键词(支持模糊匹配)。为空时进入 list 模式",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="列表模式(可配合 --industry/--stage/--tag 筛选)",
    )
    parser.add_argument(
        "--industry", help="按行业筛选(配合 --list,包含匹配)",
    )
    parser.add_argument(
        "--stage", help="按销售阶段筛选(配合 --list,包含匹配)",
    )
    parser.add_argument(
        "--tag", help="按客户标签筛选(配合 --list,包含匹配)",
    )
    parser.add_argument(
        "--this-week", action="store_true",
        help="本周安排查询:筛 下一步计划(col 8)落在本周(周一~周日)的客户",
    )
    parser.add_argument(
        "--week", default=None,
        help="配合 --this-week:指定某天(YYYY-MM-DD)所在周,缺省=本周",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="强制清除缓存(下次 list 模式重读 Excel)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="输出完整原文(每个字段单独一段,便于复制)",
    )
    parser.add_argument(
        "--empty", action="store_true",
        help="展示空字段(默认隐藏)",
    )
    parser.add_argument(
        "--cascade", action="store_true",
        help="外部级联查询:企查查 -> 天眼查 -> 水滴信用 -> 天机商查 按序兜底;"
             "命中即停,Tianji 补全。Excel 有命中时返回本地结果并附外部对照信息。",
    )

    args = parser.parse_args()

    try:
        if args.refresh:
            cache.CACHE_FILE.unlink(missing_ok=True)
            print("🗑️  缓存已清除\n", file=sys.stderr)

        # 模式路由
        if args.cascade:
            matches = find_customer_rows(args.keyword, col=0)
            if matches:
                excel_result = search_single(args.keyword, args.verbose, args.empty)
                print(excel_result)
                print("\n---\n📡 外部渠道对照信息(仅供参考):\n")
                print(cascade_lookup(args.keyword))
            else:
                print(f"❌ Excel 中未找到「{args.keyword}」,触发外部级联查询...\n")
                print(cascade_lookup(args.keyword))
                print("\n💡 如外部命中,告诉用户结果并询问「要不要新增到 Excel」")
            sys.exit(0)

        elif args.this_week:
            result = search_this_week(args.week, args.verbose)
        elif args.list or not args.keyword:
            result = search_list(
                filter_industry=args.industry,
                filter_stage=args.stage,
                filter_tag=args.tag,
                verbose=args.verbose,
            )
        else:
            result = search_single(args.keyword, args.verbose, args.empty)

        print(result)
    except Exception as e:
        print(f"\n❌ 出错了: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
