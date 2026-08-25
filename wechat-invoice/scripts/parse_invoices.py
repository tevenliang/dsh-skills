"""解析指定目录下所有 dzfp_*.pdf 电子发票（增值税专用发票 / 普通发票）。

支持两种数据格式：
  A. 含 数量+单价（信息技术/技术服务 等专用发票）
  B. 无 数量/单价（餐饮等普通发票，PDF 数量/单价列被压窄为空）

被本 skill 的 build_excel.py 调用，也可单独使用：
    python parse_invoices.py <dir>          # 打印 JSON 到 stdout
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pdfplumber


def parse_invoice(pdf_path: Path) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    lines = [l for l in text.split("\n")]

    out: dict = {"源文件": pdf_path.name}

    # 发票号码 / 开票日期
    for line in lines:
        if "发票号码" in line and "发票号码" not in out:
            m = re.search(r"发票号码[：:]\s*(\d+)", line)
            if m:
                out["发票号码"] = m.group(1)
        if "开票日期" in line and "开票日期" not in out:
            m = re.search(r"开票日期[：:]\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", line)
            if m:
                out["开票日期"] = m.group(1).replace(" ", "")

    # 购买方/销售方名称：行 "购 名称：xxx 销 名称：yyy"
    for line in lines:
        if line.startswith("购 ") and "销 " in line and "名称" in line:
            m = re.search(r"购\s*名称[：:]\s*(.+?)\s*销\s*名称[：:]\s*(.+)$", line)
            if m:
                out["购买方"] = m.group(1).strip()
                out["销售方"] = m.group(2).strip()
                break

    # 税号
    for line in lines:
        if line.startswith("信 ") and "统一社会信用代码" in line:
            m = re.search(
                r"信\s*统一社会信用代码/纳税人识别号[：:]\s*([A-Z0-9]+)\s*信\s*统一社会信用代码/纳税人识别号[：:]\s*([A-Z0-9]+)",
                line,
            )
            if m:
                out["购买方税号"] = m.group(1)
                out["销售方税号"] = m.group(2)
                break

    # 项目行
    for i, line in enumerate(lines):
        if line.startswith("项目名称") and i + 1 < len(lines):
            data_lines: list[str] = []
            for l in lines[i + 1 :]:
                if l.startswith("合"):
                    break
                if l.strip():
                    data_lines.append(l.strip())
            if data_lines:
                first = data_lines[0]
                suffix = "".join(data_lines[1:])
                # 格式 A: 含数量 + 单价
                m = re.match(
                    r"^(.+?)\s+[^\d]*?\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+(\d+%)\s+([\d.]+)$",
                    first,
                )
                if m:
                    out["项目名称"] = (m.group(1) + suffix).strip()
                    out["数量"] = m.group(2)
                    out["单价"] = m.group(3)
                    out["金额(不含税)"] = m.group(4)
                    out["税率"] = m.group(5)
                    out["税额"] = m.group(6)
                else:
                    # 格式 B: 无数量/单价
                    m = re.match(r"^(.+?)\s+([\d.]+)\s+(\d+%)\s+([\d.]+)$", first)
                    if m:
                        out["项目名称"] = (m.group(1) + suffix).strip()
                        out["数量"] = ""
                        out["单价"] = ""
                        out["金额(不含税)"] = m.group(2)
                        out["税率"] = m.group(3)
                        out["税额"] = m.group(4)
                    else:
                        out["项目名称"] = first + suffix
                        for k in ("数量", "单价", "金额(不含税)", "税率", "税额"):
                            out[k] = ""
            break

    # 价税合计
    for line in lines:
        if "价税合计" in line:
            cn = re.search(r"价税合计（大写）\s*([^\n（(]+)", line)
            num = re.search(r"小写[）)]?\s*[¥￥]?\s*([\d.]+)", line)
            if cn:
                out["价税合计(大写)"] = cn.group(1).strip()
            if num:
                out["价税合计(小写)"] = num.group(1)
            break

    # 备注
    for i, line in enumerate(lines):
        if line.startswith("备"):
            tail = " ".join(l for l in lines[i:] if l.strip())
            tail = re.sub(r"^备\s*注\s*", "", tail)
            tail = re.sub(r"^备\s*", "", tail)
            out["备注"] = tail.strip()
            break

    return out


def parse_dir(d: Path) -> list[dict]:
    """解析目录下所有 dzfp_*.pdf，对加密/损坏 PDF 返回含「错误」字段的占位记录。"""
    pdfs = sorted(d.glob("dzfp_*.pdf")) if d.is_dir() else []
    out: list[dict] = []
    for p in pdfs:
        try:
            out.append(parse_invoice(p))
        except Exception as e:
            out.append({"源文件": p.name, "错误": f"{type(e).__name__}: {e}"})
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python parse_invoices.py <dir>")
        return 1
    d = Path(sys.argv[1]).expanduser().resolve()
    rows = parse_dir(d)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())