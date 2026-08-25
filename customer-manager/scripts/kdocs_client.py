"""
封装 kdocs-cli 调用，处理 stdout/stderr 分离、JSON 解析等。

设计原则：
- 单一职责：只负责调 kdocs-cli + 解析响应
- 不做缓存（缓存由 cache.py 管）
- 不做格式化（格式化由 formatter.py 管）
- 失败直接 raise KdocsError，不静默吞
"""

import json
import subprocess
from pathlib import Path

# 云端 Excel 固定参数（v1.0 写死，未来如改路径再改成 config）
FILE_ID = "s5p5NuXrK1MrLbEGE6jurxDp2np4wYpvL"
SHARE_URL = "https://www.kdocs.cn/l/cgoYxmCqc8Ol"
WORKSHEET_ID = 1  # '客户数据表'（0-based index 0，1-based id 1）
WORKSHEET_NAME = "客户数据表"


class KdocsError(RuntimeError):
    """kdocs-cli 调用失败"""
    pass


def _normalize_date(s: str) -> str:
    """
    把 '2026-8-3' / '2026/8/3' / '2026-8-3 0:00:00' 规整成 '2026-08-03'。
    解析失败返回空串（调用方回退到原值）。
    """
    import datetime
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d",
                "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _display_value(raw: dict) -> str:
    """
    从 kdocs 原始 cell 取「给人看」的值。

    ⚠️ 关键修复（v3.1）：日期单元格的 originalCellValue 是 Excel 序列号
    （如 46237），必须改用 understandableType.value（如 '2026-8-3'）
    或 cellText（如 '2026/8/3'），否则读出来是裸数字。
    """
    if not isinstance(raw, dict):
        return str(raw)
    ut = raw.get("understandableType")
    if isinstance(ut, dict) and ut.get("type") == "date":
        val = ut.get("value") or raw.get("cellText") or ""
        norm = _normalize_date(str(val))
        return norm or str(val)
    v = raw.get("originalCellValue", raw.get("cellText", ""))
    if v is None:
        v = ""
    return str(v)


def _run_kdocs(args: list, timeout: int = 60) -> dict:
    """
    调 kdocs-cli 子命令，自动分离 stderr / 解析 stdout JSON。

    关键：kdocs-cli 在 stdout 末尾会有"kdocs-cli v2.6.0 available" 等提示，
    污染 JSON 解析。必须先把 stderr 丢黑洞，只留 stdout 给 json.load。
    """
    try:
        result = subprocess.run(
            ["kdocs-cli", "--silent"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise KdocsError(f"kdocs-cli 超时（>{timeout}s）: {e}") from e
    except FileNotFoundError as e:
        raise KdocsError(
            "kdocs-cli 未安装。\n"
            "安装: bash ~/.agents/skills/CLI/kdocs/scripts/setup.sh"
        ) from e

    # 关键：kdocs-cli 在响应较大 / 含特殊字符时可能返回非 0 exit code,
    # 但 stdout 仍然是有效 JSON({result: ok, ...})。判断成功要看 JSON 内容,
    # 不能光看 returncode。
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise KdocsError(
            f"kdocs-cli 返回非 JSON:\n{result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        ) from e

    # 判断成功:优先看 result=='ok',其次 code==0
    is_ok = (data.get("result") == "ok") or (data.get("code") == 0)
    if not is_ok:
        msg = (data.get("message") or data.get("msg") or
               str(data.get("detail", ""))[:300])
        raise KdocsError(f"kdocs-cli 失败 [exit {result.returncode}]: {msg}")

    return data


def get_file_info(file_id: str = FILE_ID) -> dict:
    """
    取文件元信息（mtime/size/version）。用于缓存失效判断。

    返回示例:
    {
      "code": 0,
      "data": {
        "id": "...",
        "name": "My customer _客户数据表.xlsx",
        "mtime": 1786076213,  # Unix 时间戳
        "size": 989330,
        "version": 40
      }
    }
    """
    response = _run_kdocs([
        "drive", "get-file-info",
        f'{{"file_id":"{file_id}"}}'
    ])
    # _run_kdocs 已校验 result==ok/code==0,这里只需保证有 data 字段
    if "data" not in response:
        raise KdocsError(f"get-file-info 响应无 data: {response}")
    return response["data"]


def find_customer_rows(
    keyword: str,
    col: int = 0,
    file_id: str = FILE_ID,
    max_rows: int = 500,
) -> list[dict]:
    """
    在指定列做模糊搜索，返回匹配的所有行（只含 col 列的值 + 行号）。

    底层用 kdocs-cli sheet find-range-data 的 search 参数。
    搜索是服务端做的,不会拉全表。

    返回示例:
    [
      {
        "row": 2,
        "value": "跨维（深圳）智能数字科技有限公司",
        "col": 0
      }
    ]
    """
    payload = {
        "file_id": file_id,
        "worksheet_id": WORKSHEET_ID,
        "range": {"colFrom": col, "colTo": col, "rowFrom": 0, "rowTo": max_rows},
        "filter": {"search": [{"col": col, "value": [keyword]}]},
        "show_total": True,
    }
    response = _run_kdocs([
        "sheet", "find-range-data",
        json.dumps(payload, ensure_ascii=False)
    ])

    # _run_kdocs 已校验。find-range-data 返回结构:{"data":{"range_data":[...]}, "result":"ok"}
    inner = response.get("data") or {}
    cells = inner.get("range_data", []) or inner.get("rangeData", [])

    result = []
    for cell in cells:
        result.append({
            "row": cell["row_from"],  # 0-based
            "value": cell.get("original_cell_value", cell.get("cell_text", "")),
            "col": col,
        })
    return result


def get_row(
    row_0based: int,
    col_from: int = 0,
    col_to: int = 21,
    file_id: str = FILE_ID,
) -> list[dict]:
    """
    读指定行的指定列范围（默认 col 0-21 即全部 22 列）。

    返回:cell list（已按 col 排序）,每个 cell 含:
      - col (0-based)
      - row (0-based)
      - value (文本)
      - num_format / colors / fonts（不解析,直接透传）
    """
    payload = {
        "file_id": file_id,
        "worksheet_id": WORKSHEET_ID,
        "range": {"colFrom": col_from, "colTo": col_to, "rowFrom": row_0based, "rowTo": row_0based},
    }
    response = _run_kdocs([
        "sheet", "get-range-data",
        json.dumps(payload, ensure_ascii=False)
    ])

    # _run_kdocs 已校验。get-range-data 返回结构:{"detail":{"rangeData":[...]}, "result":"ok"}
    cells = response["detail"]["rangeData"]
    result = []
    for cell in cells:
        result.append({
            "col": cell["colFrom"],
            "row": cell["rowFrom"],
            "value": _display_value(cell),
            "raw": cell,  # 完整原始数据（formatting/colors）
        })
    return sorted(result, key=lambda c: c["col"])


def get_full_sheet(
    col_from: int = 0,
    col_to: int = 21,
    row_from: int = 0,
    row_to: int = 313,
    file_id: str = FILE_ID,
) -> list[dict]:
    """
    读整张工作表的指定范围。返回所有 cell 的扁平列表。
    """
    payload = {
        "file_id": file_id,
        "worksheet_id": WORKSHEET_ID,
        "range": {"colFrom": col_from, "colTo": col_to, "rowFrom": row_from, "rowTo": row_to},
    }
    response = _run_kdocs([
        "sheet", "get-range-data",
        json.dumps(payload, ensure_ascii=False)
    ])

    # _run_kdocs 已校验。直接读 detail.rangeData
    cells = response["detail"]["rangeData"]
    result = []
    for cell in cells:
        result.append({
            "col": cell["colFrom"],
            "row": cell["rowFrom"],
            "value": _display_value(cell),
            "raw": cell,  # 完整原始数据(cellText/numFormat/understandableType)
        })
    return result


# ─────────────────────────────────────────────────────────────
# 写操作(update-range-data / add-row)
# ─────────────────────────────────────────────────────────────

def update_cell(
    row_0based: int,
    col_0based: int,
    value: str,
    file_id: str = FILE_ID,
    worksheet_id: int = WORKSHEET_ID,
) -> dict:
    """
    覆盖写入单个单元格(用 update-range-data, opType=formula)。

    注意:opType='formula' 不是真的写公式,而是 write_text 的语义
    (因为 kdocs 把「写值」和「写公式」统一在 opType='formula' 下,
    区别只在 formula 字段值是否以 = 开头)。

    返回 kdocs 响应 data 字段。
    """
    payload = {
        "file_id": file_id,
        "worksheet_id": worksheet_id,
        "rangeData": [
            {
                "opType": "formula",
                "rowFrom": row_0based,
                "rowTo": row_0based,
                "colFrom": col_0based,
                "colTo": col_0based,
                "formula": value,
            }
        ],
    }
    response = _run_kdocs([
        "sheet", "update-range-data",
        json.dumps(payload, ensure_ascii=False)
    ])
    return response.get("data") or {}


def update_cells(
    cells: list[dict],
    file_id: str = FILE_ID,
    worksheet_id: int = WORKSHEET_ID,
) -> dict:
    """
    批量覆盖写入多个单元格。cells 格式:
      [{"row": 2, "col": 5, "value": "..."}, ...]
    (row/col 都是 0-based)
    """
    range_data = []
    for c in cells:
        range_data.append({
            "opType": "formula",
            "rowFrom": c["row"],
            "rowTo": c["row"],
            "colFrom": c["col"],
            "colTo": c["col"],
            "formula": c.get("value", ""),
        })
    payload = {
        "file_id": file_id,
        "worksheet_id": worksheet_id,
        "rangeData": range_data,
    }
    response = _run_kdocs([
        "sheet", "update-range-data",
        json.dumps(payload, ensure_ascii=False)
    ])
    return response.get("data") or {}


def add_row(
    values: list[str],
    file_id: str = FILE_ID,
    worksheet_id: int = WORKSHEET_ID,
) -> dict:
    """
    在工作表已用区域末尾追加一行(用 add-row)。

    values: 按列顺序的字符串列表(空字符串表示该列不写)。
    例:[客户名称, 行业, 销售阶段, ..., 更新日期] 共 22 个元素。

    返回 kdocs 响应 data 字段。
    """
    range_data = []
    for i, val in enumerate(values):
        if val is None or val == "":
            # 跳过空值(避免触发 cell_operation_type 错误)
            continue
        range_data.append({
            "op_type": "cell_operation_type_formula",
            "col": i,
            "formula": val,
        })
    if not range_data:
        raise KdocsError("add-row: 所有列都为空,无法追加")

    payload = {
        "file_id": file_id,
        "worksheet_id": worksheet_id,
        "range_data": range_data,
    }
    response = _run_kdocs([
        "sheet", "add-row",
        json.dumps(payload, ensure_ascii=False)
    ])
    return response.get("data") or {}
