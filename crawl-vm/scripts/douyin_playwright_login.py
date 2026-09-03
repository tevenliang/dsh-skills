#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/douyin_playwright_login.py — 抖音扫码登录 (持久化 profile)

关键改进 (2026-09-02):
- 用 launch_persistent_context(user_data_dir) — 登录 cookie 持久化到磁盘,
  即使脚本重跑/关闭, 登录态依然保留; 后续爬取可复用同一 profile
- 检测条件放宽: sessionid_ss / sid_guard / uid_tt 任一生效即登录成功
- 登录成功 → 立即保存 cookie 到 config.yaml

用法:
  python douyin_playwright_login.py
"""
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

STATUS_LOG = "/tmp/douyin_login.status.log"
QR_PATH = "/tmp/douyin_qr.png"
PROFILE_DIR = "/home/ubuntu/.dsh/state/douyin_profile"  # 持久化浏览器 profile
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

DOUYIN_COOKIE_CONFIG = Path.home() / ".dsh" / "skills" / "crawl" / "ingest-douyin" / \
    "douyin_api" / "crawlers" / "douyin" / "web" / "config.yaml"


def log(msg: str):
    with open(STATUS_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    print(msg, flush=True)


def main():
    open(STATUS_LOG, "w", encoding="utf-8").close()
    out_path = Path(QR_PATH)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            user_agent=UA,
            locale="zh-CN",
            viewport={"width": 1280, "height": 900},
            args=["--no-sandbox"],
        )
        page = context.new_page() if context.pages else context.new_page()
        log("🚀 启动 Chromium (持久化 profile)...")
        page.goto("https://www.douyin.com/", timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        # 先检查是否已登录 (持久化 profile 可能已带登录态)
        cookies0 = context.cookies("https://www.douyin.com")
        ck0 = {c["name"]: c["value"] for c in cookies0}
        if ck0.get("sessionid_ss") or ck0.get("sessionid"):
            log("✅ 持久化 profile 已登录! (sessionid 存在)")
            _save_cookie(context, ck0)
            context.close()
            return 0

        log("未登录, 开始扫码流程...")
        # 点登录
        try:
            page.locator("text=登录").last.click(timeout=5000)
            log("✅ 点击登录")
        except Exception:
            pass
        page.wait_for_timeout(4000)

        # 提取二维码
        extracted = False
        for _ in range(12):
            try:
                imgs = page.locator("img")
                for i in range(imgs.count()):
                    try:
                        src = imgs.nth(i).get_attribute("src")
                        if src and src.startswith("data:image/png;base64,"):
                            import base64, io
                            from PIL import Image
                            data = base64.b64decode(src.split(",", 1)[1])
                            img = Image.open(io.BytesIO(data))
                            if img.size[0] == img.size[1] and 100 <= img.size[0] <= 600:
                                ts = time.strftime("%Y%m%d_%H%M%S")
                                ts_out = Path(f"/tmp/douyin_qr_{ts}.png")
                                ts_out.write_bytes(data)
                                out_path.write_bytes(data)
                                log(f"✅ 二维码保存: {ts_out.name} ({img.size[0]}x{img.size[1]} @ {ts})")
                                # 立即同步到 webdav (带时间戳文件名, 用户 Finder 可见)
                                try:
                                    import shutil
                                    webdav_dir = Path('/home/ubuntu/webdav/steven_vault/_tmp_qr_login')
                                    webdav_dir.mkdir(parents=True, exist_ok=True)
                                    shutil.copy(ts_out, webdav_dir / f'douyin_login_{ts}.png')
                                    # 也覆盖最新副本 (固定名)
                                    shutil.copy(ts_out, webdav_dir / 'douyin_login_latest.png')
                                    log(f"✅ 已同步 webdav: _tmp_qr_login/douyin_login_{ts}.png (最新=latest)")
                                except Exception as e:
                                    log(f"⚠️ webdav 同步失败: {e}")
                                extracted = True
                                break
                    except Exception:
                        continue
                if extracted:
                    break
            except Exception:
                pass
            page.wait_for_timeout(1500)

        if not extracted:
            page.screenshot(path=str(out_path))
            log(f"⚠️ 未找到二维码, 保存整页截图")

        # 轮询检测登录 — 注意: 不强制 navigate 刷新 (打断抖音 SPA 异步种 cookie)
        log("⏳ 等待扫码 (原地等待, 不刷新页面)...")
        start = time.time()
        login_ok = False
        while (time.time() - start) < 300:
            time.sleep(3)
            try:
                # 检测1: 页面元素 (不刷新页面)
                login_btns = page.locator('text=登录').count()
                user_avatars = page.locator('[data-e2e*="user"], [class*="user-info"], img[alt*="头像"], [class*="avatar"]').count()
                page_title = page.title()
                
                # 检测2: cookie (也在原地读)
                cookies = context.cookies()
                ck = {c["name"]: c["value"] for c in cookies}
                has_session = bool(ck.get("sessionid") or ck.get("sessionid_ss"))
                
                # 检测3: URL 变化 (登录成功可能跳转到 homefeed 或类似)
                cur_url = page.url
                
                log(f"  扫描: btns={login_btns} avatars={user_avatars} session={has_session} url={cur_url[:60]}")
                
                if login_btns <= 1 and (user_avatars > 0 or has_session):
                    log("✅ 检测到登录迹象, 原地等待 8s 让 SPA 写 cookie...")
                    page.wait_for_timeout(8000)
                    # 再检查 cookie
                    cookies2 = context.cookies()
                    ck2 = {c["name"]: c["value"] for c in cookies2}
                    if ck2.get("sessionid") or ck2.get("sessionid_ss") or ck2.get("sid_guard"):
                        log("✅ cookie 已写入 (sessionid/sid_guard 出现)")
                        login_ok = True
                        break
                    else:
                        log("⚠️ 元素已登录但 cookie 仍未写入, 继续等...")
                        page.wait_for_timeout(5000)
                        cookies3 = context.cookies()
                        ck3 = {c["name"]: c["value"] for c in cookies3}
                        if ck3.get("sessionid") or ck3.get("sessionid_ss") or ck3.get("sid_guard"):
                            log("✅ cookie 终于写入!")
                            login_ok = True
                            break
            except Exception as e:
                log(f"⚠️ 检测异常: {e}")

        if not login_ok:
            log("❌ 超时未检测到登录 (profile 保留, 下次可复用)")
            context.close()
            return 1

        _save_cookie(context, {c["name"]: c["value"] for c in context.cookies()})
        log("✅ 完成! profile 已持久化")
        context.close()
        return 0


def _save_cookie(context, cookie_dict):
    """抓 cookie 写入 config.yaml"""
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items() if v)
    log(f"📦 抓取 {len(cookie_dict)} cookie, sessionid: {cookie_dict.get('sessionid', 'N/A')[:15]}...")

    import yaml
    cfg = yaml.safe_load(DOUYIN_COOKIE_CONFIG.read_text(encoding="utf-8"))
    old = cfg["TokenManager"]["douyin"]["headers"]["Cookie"]
    log(f"旧 cookie 长度: {len(old)}")
    cfg["TokenManager"]["douyin"]["headers"]["Cookie"] = cookie_str
    backup = DOUYIN_COOKIE_CONFIG.with_suffix(".yaml.bak." + time.strftime("%Y%m%d_%H%M%S"))
    DOUYIN_COOKIE_CONFIG.rename(backup)
    DOUYIN_COOKIE_CONFIG.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    log(f"✅ 新 cookie 写入: {DOUYIN_COOKIE_CONFIG} ({len(cookie_str)} chars)")


if __name__ == "__main__":
    sys.exit(main())
