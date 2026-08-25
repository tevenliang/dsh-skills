"""微信发票整理入口（直接读源文件，不拷贝）。

使用：
    python ingest.py --config config.json
    python ingest.py --config config.json --reparse    # 强制重新解析所有发票
    python ingest.py --config config.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_excel import match_company, write_company_workbook
from manifest import Manifest, resolve_incremental, resolve_source_files
from parse_invoices import parse_invoice


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--reparse", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    project = Path(cfg["project"]).expanduser().resolve()
    records_subdir = cfg.get("records_subdir", "开票记录")
    months = cfg["months"]
    companies = cfg["companies"]
    source_base = Path(cfg["source"]["base"]).expanduser().resolve()
    src_months = cfg["source"].get("months", months)

    manifest = Manifest(project / "manifest.json")
    manifest.set_meta(str(source_base), companies)

    # 1. 扫描源文件，更新 manifest
    print("=== 1. 扫描源文件并更新 manifest ===")
    source_files = resolve_source_files(source_base, src_months)
    new, changed, cached = resolve_incremental(source_files, manifest, args.reparse)
    print(f"  源文件 {len(source_files)} 个 | 新增 {len(new)} | 变更 {len(changed)} | 缓存 {len(cached)}")

    for digest, path, month in new + changed:
        try:
            inv = parse_invoice(path)
            status = "error" if "错误" in inv else "ok"
        except Exception as e:
            inv = {"源文件": path.name, "错误": f"{type(e).__name__}: {e}"}
            status = "error"
        manifest.upsert(digest, {
            "filename": path.name,
            "month": month,
            "status": status,
            "invoice": inv,
        })

    if not args.dry_run:
        manifest.save()
        print(f"  ✓ manifest.json 已保存")
    else:
        print("  [dry-run] manifest 未写入磁盘")

    # 2. 汇总 + 生成 Excel
    print()
    print("=== 2. 按公司+月份汇总并生成 Excel ===")
    processed = manifest._data.get("processed", {})

    # 收集所有 status=ok 的记录
    all_rows = []
    for digest, entry in processed.items():
        if entry.get("status") != "ok":
            continue
        inv = dict(entry.get("invoice", {}))
        inv["_md5"] = digest
        inv["月份"] = entry.get("month", "")
        all_rows.append(inv)

    # 发票号去重
    inv_num_index: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows:
        num = r.get("发票号码", "")
        if num:
            inv_num_index[num].append(r)
    no_num_rows = [r for r in all_rows if not r.get("发票号码", "")]

    deduped: list[dict] = []
    for num, candidates in inv_num_index.items():
        deduped.append(max(candidates, key=lambda x: x["月份"]))
    deduped.extend(no_num_rows)

    print(f"  共 {len(deduped)} 张发票（发票号去重后）")

    # 按公司+月份分组
    skipped, grouped = [], defaultdict(lambda: defaultdict(list))
    for r in deduped:
        ck = match_company(r.get("购买方", ""), companies)
        if not ck:
            skipped.append(r)
        else:
            grouped[ck][r["月份"]].append(r)

    print("  匹配结果：")
    for ck in sorted(grouped.keys()):
        for m in sorted(grouped[ck].keys()):
            print(f"    {ck} | {m} | {len(grouped[ck][m])} 张")
    if skipped:
        print(f"  跳过（{len(skipped)} 张，购买方不在公司列表内）：")
        for r in skipped[:5]:
            buyer = r.get("购买方", "")
            num = r.get("发票号码", "") or r.get("源文件", "")
            print(f"    - {r.get('月份','')} | 购买方「{buyer}」| {num}")
        if len(skipped) > 5:
            print(f"    ... 还有 {len(skipped)-5} 张")

    print("  生成 Excel：")
    for ck in sorted(grouped.keys()):
        months_data = sorted(grouped[ck].items(), key=lambda x: x[0])
        write_company_workbook(ck, months_data, project, records_subdir, args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
