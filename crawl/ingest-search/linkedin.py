#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys
from pathlib import Path
# 切换到 crawl 根目录
_CRAWL_ROOT = str(Path(__file__).resolve().parent.parent)
if _CRAWL_ROOT not in sys.path:
    sys.path.insert(0, _CRAWL_ROOT)
os.chdir(_CRAWL_ROOT)
"""
tools/linkedin.py — 领英职位搜索 (ominicrawl v2, 搜索型工具层)

crawl_batch(date_yymmdd) → 读飞书 Watchlist ## 领英 (linkedin) 关键词,
主路径: opencli 浏览器桥真实渲染 (绕过中文适配器 'Text not found: Jobs' bug),
回退: opencli linkedin search 适配器。写出 notes/linkedin/<mmdd>_<slug>.md,
返回 [(title, author, md_path, None), ...]。

v2 改进 (2026-07-15): 加职位 detail 抓取 — 不再只爬搜索结果列表,
  对前 N 个职位逐个开 detail 页 (`browser eval` JS 抽 DOM 结构化字段),
  每职位带公司/地点/任职要求/职位描述完整正文。ENV:
    LINKEDIN_DETAIL_LIMIT=N  (默认 10, 想快降到 0 就关)
    LINKEDIN_DETAIL_DELAY=S  (默认 2.5, 详情页之间 sleep 防限流)
  opencli 浏览器桥未连时静默软退化, ## 职位详情 段保留但每职位留
  "*未抓取, 待凌晨补*" 占位 (用户原话: clip 抓不到放着我手工处理).
"""
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

SKILL_ROOT = str(Path(__file__).resolve().parent.parent)
for _p in (SKILL_ROOT, str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.paths import notes_dir
# from common.feishu_watchlist import get_linkedin_keywords  # 飞书已弃用
from common.opencli_bridge import fetch_rendered, tab, wait, eval_js, _run, SESSION
from tools._search_common import slugify, mmdd, today_full, search_opencli, write_md
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'common-publish'))



def get_linkedin_keywords_from_vault():
    """从 vault watchlist.md 读取领英关键词"""
    vault = Path("/Users/tianwenliang/Documents/steven_vault/subscription/watchlist.md")
    if not vault.exists():
        return []
    with open(vault, encoding="utf-8") as f:
        content = f.read()
    match = re.search(r"## 领英.*?\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    if not match:
        return []
    keywords = []
    for line in match.group(1).split("\n"):
        line = line.strip()
        if line.startswith("|") and "关键词" not in line and "----" not in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and parts[1]:
                keywords.append({"kw": parts[1], "city": parts[2] if len(parts) > 2 else "", "label": parts[1]})
    return keywords


DEFAULT_KEYWORDS = [
    {"kw": "AIBD", "city": "深圳", "label": "AIBD"},
    {"kw": "AI销售", "city": "深圳", "label": "AI销售"},
]
DELAY = 5.0
DAILY_CAP = 30

# ── 详情抓取配置 (ENV 可覆盖) ─────────────────────────────────
DETAIL_LIMIT = int(os.environ.get("LINKEDIN_DETAIL_LIMIT", "10"))
DELAY_DETAIL = float(os.environ.get("LINKEDIN_DETAIL_DELAY", "2.5"))
DETAIL_WAIT = float(os.environ.get("LINKEDIN_DETAIL_WAIT", "4"))
DETAIL_TIMEOUT = int(os.environ.get("LINKEDIN_DETAIL_TIMEOUT", "300"))


# 详情页 JS: 先滚动加载 lazy 内容，再抽结构化字段
# LinkedIn 详情页的职位描述是 lazy load，必须先滚动才有
DETAIL_JS = r"""(function(){
  // 等待页面 JS 渲染完成（LinkedIn 单页应用需等 React hydrate）
  var _t = Date.now();
  while (document.body.innerText.length < 1000 && Date.now() - _t < 20000) {}

  function pickText(selectors) {
    for (var i=0;i<selectors.length;i++){
      var el=document.querySelector(selectors[i]);
      if (el && el.innerText && el.innerText.trim()) return el.innerText.trim();
    }
    return "";
  }
  // 从 document.title 和 body 文本提取（LinkedIn 用 hash className）
  var title = document.title.split(' | ')[0] || '';
  // 找 STRONG 标签中的 "Job Title: xxx"
  var strongs = document.querySelectorAll('STRONG');
  for (var si = 0; si < strongs.length; si++) {
    var st = (strongs[si].innerText || '').trim();
    if (st.includes('Job Title:')) { title = st.replace('Job Title: ', '').trim(); break; }
  }
  // 公司+地点从 body 第二/三行提取
  var footerIdx = document.body.innerText.indexOf('关于');
  var mainBody = footerIdx >= 0 ? document.body.innerText.substring(0, footerIdx) : document.body.innerText;
  var navIdx = mainBody.indexOf('对于 Business');
  if (navIdx >= 0) mainBody = mainBody.substring(navIdx);
  var lines = mainBody.split(/\n/).filter(function(l){return l.trim().length > 0;});
  var company = (lines[1] || '').trim();
  // lines[2] 格式: "中国 广东省 深圳 · 的时间: 4 个月前 · 90 位申请者"
  var locLine = (lines[2] || '');
  // 取 " · " 前的城市部分
  var dotIdx = locLine.indexOf(' · ');
  var location = dotIdx > 0 ? locLine.substring(0, dotIdx) : locLine;
  // 描述从 P 标签取（排除噪音行）
  var skipKw = ['·','对于 Business','无障碍','人才解决','社区准则','隐私政策',
                 '广告','安全中心','Copyright','管理帐号','推荐透明'];
  var paras = [];
  var allP = document.querySelectorAll('P');
  for (var pi = 0; pi < allP.length; pi++) {
    var pt = (allP[pi].innerText || '').trim();
    if (pt.length > 30 && pt.length < 3000) {
      var skip = false;
      for (var k = 0; k < skipKw.length; k++) {
        if (pt.includes(skipKw[k])) { skip = true; break; }
      }
      if (!skip) paras.push(pt);
    }
  }
  var desc = paras.join('\n');
  var criteria = paras.slice(-6).join('\n');  // 最后几段通常是任职要求
  return JSON.stringify({
    title: title.substring(0, 200),
    company: company.substring(0, 100),
    location: location.substring(0, 100),
    description: desc.substring(0, 8000),
    criteria: criteria.substring(0, 2000),
    desc_len: desc.length
  });
})()"""


def _browser_extract(kw, location, limit=30):
    """opencli 浏览器桥真实渲染领英搜索页, 分步解析职位链接。"""
    safe_kw = quote_plus(kw)
    en_loc = _en_location(location)
    loc = f"&location={quote_plus(en_loc)}" if en_loc else ""
    url = f"https://www.linkedin.com/jobs/search/?keywords={safe_kw}{loc}"
    try:
        md, _ = fetch_rendered(url, wait_secs=8)
    except Exception as e:
        print(f"  [linkedin] 浏览器桥失败: {e}")
        return []
    if not md.strip():
        return []
    
    # 分步提取：先用简单正则匹配所有 [title](url) 对
    link_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    url_set = set()
    results = []
    
    for title_raw, job_url in link_re.findall(md):
        # 只处理 /jobs/view/ 的链接
        if '/jobs/view/' not in job_url:
            continue
        title = re.sub(r'\s*with verification\s*', '', title_raw).strip()
        # 过滤非职位标题
        if not title or title.lower() in ('jobs',) or len(title) < 5:
            continue
        if any(kw in title for kw in ['标志', 'logo', '官网', 'company']):
            continue
        
        # 清理 URL（取 ? 前的部分）
        clean_url = job_url.split('?')[0]
        if clean_url in url_set:
            continue
        url_set.add(clean_url)
        
        results.append({
            "title": title,
            "company": "",
            "location": location or "",
            "url": job_url if job_url.startswith("http") else f"https://www.linkedin.com{job_url}",
            "listed": today_full(),
        })
        if len(results) >= limit:
            break
    return results


def _browser_extract_detail(url):
    """opencli tab + JS eval 抽职位结构化字段.
    LinkedIn 详情页内容通过 DETAIL_JS 内部的 busy wait 等 lazy 渲染.
    整体超时: DETAIL_TIMEOUT (默认180s).
    失败 -> 降级返回 {"title_only": True, "url": url} (保留链接供用户点开).
    """
    try:
        with tab(url, timeout=DETAIL_TIMEOUT) as page:
            wait(page, DETAIL_WAIT)
            raw = eval_js(page, DETAIL_JS)
    except Exception as e:
        print(f"      [detail] 超时/失败 {url[:60]}…: {e}")
        return {"title_only": True, "url": url}
    if not raw:
        return {"title_only": True, "url": url}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {"title_only": True, "url": url}
    if not isinstance(raw, dict):
        return {"title_only": True, "url": url}
    if raw.get("err") or raw.get("desc_len", 0) < 20:
        return {"title_only": True, "url": url}
    return raw


def _fetch_details_for_results(results, max_n=None):
    """对 search 前 N 个职位逐个抓 detail, 给 results[i] 加 'details' 字段.

    不抛异常 — 任一职位失败标 None 跳过; opencli 未连 (extension service worker
    asleep) 时全部 None, ## 职位详情 段保留但每职位给占位说明.
    """
    n = max_n if max_n is not None else DETAIL_LIMIT
    n = max(0, min(n, len(results)))
    if n <= 0:
        # DETAIL_LIMIT=0 → 完全跳过详情抓取 (秒跑模式)
        for p in results:
            p["details"] = None
        return
    print(f"    📋 抓详情: 前 {n}/{len(results)} 个职位")
    ok = 0
    skipped = 0
    for i, p in enumerate(results[:n]):
        url = p.get("url", "")
        if not url:
            p["details"] = None
            continue
        d = _browser_extract_detail(url)
        if d:
            p["details"] = d
            ok += 1
        else:
            p["details"] = None
            skipped += 1
        if i < n - 1:
            time.sleep(DELAY_DETAIL)
    if ok or skipped:
        print(f"    📋 详情: 成功 {ok}, 失败/跳过 {skipped}")


def _format_detail_section(results):
    """格式化 ## 职位详情 段 (markdown), 用于挂在 ## 职位列表 表格之后.

    每个职位:
      ### N. 标题
      🏢 公司 · 📍 地点 · 🔗 原文链接
      **任职要求**:  (criteria)
      **职位描述**:  (description, 截 6000 字)
      ---

    用户授权: 抓不到的职位留着占位, 留手工处理.
    """
    out: list[str] = ["## 职位详情", ""]
    for i, p in enumerate(results, 1):
        d = p.get("details")
        title = p.get("title", "(无标题)")
        company = (p.get("company") or "?").strip()
        loc = p.get("location") or ""
        url = p.get("url", "") or ""
        if not d:
            # 无 detail 数据（降级占位）
            out.append(f"### {i}. {title}")
            out.append("")
            if url:
                out.append(f"🏢 {company} · 📍 {loc or '?'} · 🔗 [原文]({url})")
            else:
                out.append(f"🏢 {company} · 📍 {loc or '?'}")
            out.append("")
            out.append("*(职位详情未抓取。详情页加载超时（opencli 120s 限制）或 LinkedIn "
                       "需要登录验证 — 等凌晨系统自动跑时补，或手工点链接处理)*")
            out.append("")
            out.append("---")
            out.append("")
            continue
        # 检测 title_only 降级模式
        if d.get("title_only"):
            out.append(f"### {i}. {title}")
            out.append("")
            out.append(f"🏢 {company} · 📍 {loc or '?'} · 🔗 [原文]({url})")
            out.append("")
            out.append("*(详情页加载超时（opencli 120s 硬上限）。"
                       "点上方链接查看完整职位描述和任职要求)*")
            out.append("")
            out.append("---")
            out.append("")
            continue
        title_real = d.get("title") or title
        out.append(f"### {i}. {title_real}")
        out.append("")
        company = (d.get("company") or p.get("company") or "?").strip()
        loc_real = (d.get("location") or loc or "?").strip()
        if url:
            meta = f"🏢 **{company}** · 📍 {loc_real} · 🔗 [原文]({url})"
        else:
            meta = f"🏢 **{company}** · 📍 {loc_real}"
        out.append(meta)
        out.append("")
        criteria = (d.get("criteria") or "").strip()
        if criteria:
            out.append("**任职要求**:")
            for ln in criteria.split("\n"):
                ln = ln.strip()
                if ln:
                    out.append(f"> {ln}")
            out.append("")
        description = (d.get("description") or "").strip()
        if description:
            out.append("**职位描述**:")
            desc_text = description[:6000]
            for ln in desc_text.split("\n"):
                ln = ln.strip()
                if ln:
                    out.append(f"> {ln}")
            if len(description) > 6000:
                out.append(f"> *(共 {len(description)} 字, 已截断前 6000 字)*")
            out.append("")
        out.append("---")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _search(kw, location, limit=30):
    results = _browser_extract(kw, location, limit)
    # browser 结果缺 company 时回退到 opencli API（company 字段更完整）
    if not results or not any(r.get("company", "").strip() for r in results):
        en_loc = _en_location(location)
        cmd = ["linkedin", "search", kw, "--limit", str(limit), "-f", "json"]
        if en_loc:
            cmd += ["--location", en_loc]
        data = search_opencli(cmd, retry_empty=False)
        if not isinstance(data, list):
            return results if results else []
        api_results = [{
            "title": (p.get("title") or "").strip(),
            "company": (p.get("company") or p.get("companyName") or "").strip(),
            "location": (p.get("location") or p.get("locationName") or location or "").strip(),
            "url": p.get("url") or p.get("link") or p.get("jobUrl") or "",
            "listed": today_full(),
        } for p in data if (p.get("title") or "").strip()]
        if api_results:
            results = api_results
    return results


def _build_md(kw, location, label, results):
    rows = []
    for i, p in enumerate(results, 1):
        title = p.get("title", "")
        company = p.get("company", "")
        loc = p.get("location", "")
        listed = p.get("listed", "")
        url = p.get("url", "")
        rows.append(f"| {i} | [{title}]({url}) | {company} | {loc} | {listed} |")
    table = (
        "| # | 职位 | 公司 | 地点 | 发布 |\n"
        "|---|---|---|---|---|\n" + "\n".join(rows)
        if rows else "| （无搜索结果） | | | |"
    )
    d = today_full()
    n_details_ok = sum(1 for p in results if p.get("details"))
    detail_section = _format_detail_section(results)
    return (
        f"---\n"
        f'source: linkedin_search\n'
        f'linkedin_type: search\n'
        f'title: "{label} 搜索结果"\n'
        f'linkedin_keyword: "{kw}"\n'
        f'linkedin_location: "{location or ""}"\n'
        f'collected_at: {d}\n'
        f'linkedin_result_count: {len(results)}\n'
        f'linkedin_detail_count: {n_details_ok}\n'
        f"tags:\n  - linkedin\n  - 订阅\n"
        f"---\n\n"
        f"# {label} — 搜索结果\n\n"
        f"| 关键词 | {kw} |\n"
        f"| 城市 | {location or '不限'} |\n"
        f"| 搜索时间 | {d} |\n"
        f"| 结果数 | {len(results)} |\n"
        f"| 详情抓取 | {n_details_ok}/{len(results)} 个职位成功 |\n\n"
        f"## 职位列表\n\n{table}\n\n"
        f"{detail_section}"
    )




def _build_single_job_md(job, kw, location):
    """构建单个职位的 md"""
    title = job.get("title") or job.get("job_title") or "未知职位"
    company = job.get("company", "未知公司")
    loc = job.get("location") or location or "未知"
    url = job.get("url", "")
    desc = job.get("description", "")[:500]
    
    return f"""---
source: linkedin
source_id: "{job.get("id", "")}"
collected_at: {today_full()}
tags:
  - linkedin
  - {kw}
  - {company}

## 岗位信息

| 字段 | 值 |
|---|---|
| 公司 | {company} |
| 职位 | {title} |
| 地点 | {loc} |
| 链接 | {url} |

## 描述

{desc}
"""

def _scan_existing_job_ids():
    """扫描 vault 里已有职位的 job_id，用于全局去重"""
    seen = set()
    vault = Path("/Users/tianwenliang/Documents/steven_vault/subscription/linkedin")
    if vault.exists():
        for f in vault.rglob("*.md"):
            content = f.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'/jobs/view/(\d+)', content):
                seen.add(m.group(1))
            # 也支持 source_id 格式
            for m in re.finditer(r"source_id:\s*[\"']?(\d+)", content):
                seen.add(m.group(1))
    return seen

def crawl_batch(date_yymmdd=None):
    try:
        keywords = get_linkedin_keywords_from_vault()
    except Exception as e:
        print(f"  [warn] 飞书领英关键词读取失败, 用默认: {e}")
        keywords = []
    keywords = keywords or DEFAULT_KEYWORDS

    out_dir = notes_dir() / "linkedin"
    prefix = mmdd(date_yymmdd)
    written = []
    # 全局去重：已存在的 job_id 不再写入
    seen_job_ids = _scan_existing_job_ids()
    n_before = len(seen_job_ids)
    print(f"  [dedup] vault 中已有 {n_before} 个职位，跨关键词去重开启")
    for item in keywords:
        kw = (item.get("kw") or "").strip()
        if not kw:
            continue
        if len(written) >= DAILY_CAP:
            print("  [cap] 达单日上限, 停止")
            break
        location = (item.get("city") or "").strip()
        label = (item.get("label") or kw).strip()
        kw_dir = out_dir / kw
        kw_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"  🔍 领英搜索: {kw} (城市={location or '不限'})")
        results = _search(kw, location)
        if not results:
            print(f"  [skip] {kw} 无结果")
            continue
        _fetch_details_for_results(results)
        
        for i, r in enumerate(results):
            company = (r.get("company") or "").strip() or "未知公司"
            title = (r.get("title") or r.get("job_title") or f"职位{i+1}").strip()
            company_slug = slugify(company, 20)
            title_slug = slugify(title, 40)
            fname = f"{prefix}_{company_slug}_{title_slug}.md"
            out_path = kw_dir / fname
            if out_path.exists():
                continue
            # 跨关键词全局去重：提取 job_id
            job_url = r.get("url", "")
            m = re.search(r'/jobs/view/(\d+)', job_url)
            if m:
                jid = m.group(1)
                if jid in seen_job_ids:
                    print(f"    ⏭️ 跳过重复职位 [{title[:40]}] (job_id={jid})")
                    continue
                seen_job_ids.add(jid)
            elif not title.strip() or title == f"职位{i+1}":
                print(f"    ⏭️ 跳过无标题条目")
                continue
            # 生成单文件内容
            md_content = _build_single_job_md(r, kw, location)
            out_path.write_text(md_content, encoding="utf-8")
            written.append((title, kw, str(out_path), None))
    print(f"  ✅ 领英完成: {len(written)} 个职位")
    return written



# ── 中文→英文城市名映射 (LinkedIn API 不认中文 location) ──────────────────
_CITY_MAP = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "深圳": "Shenzhen",
    "广州": "Guangzhou",
    "杭州": "Hangzhou",
    "成都": "Chengdu",
    "南京": "Nanjing",
    "武汉": "Wuhan",
    "西安": "Xi'an",
    "苏州": "Suzhou",
    "天津": "Tianjin",
    "重庆": "Chongqing",
    "郑州": "Zhengzhou",
    "长沙": "Changsha",
    "东莞": "Dongguan",
    "佛山": "Foshan",
    "宁波": "Ningbo",
    "青岛": "Qingdao",
    "济南": "Jinan",
    "厦门": "Xiamen",
    "福州": "Fuzhou",
    "合肥": "Hefei",
    "沈阳": "Shenyang",
    "大连": "Dalian",
    "无锡": "Wuxi",
    "昆明": "Kunming",
    "香港": "Hong Kong",
    "澳门": "Macau",
    "台北": "Taipei",
    "新一线": "New First-Tier Cities",
}

def _en_location(loc):
    if not loc:
        return loc
    return _CITY_MAP.get(loc.strip(), loc)

if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    count = crawl_batch(date_arg)
    print(f"\n✅ 完成: {count} 个职位")
