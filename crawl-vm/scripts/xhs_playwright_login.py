#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/xhs_playwright_login.py — 用 Playwright Chromium 完成小红书扫码登录

流程:
  1. 启动 Chromium (带反检测 UA)
  2. 打开小红书 → 点登录 → 切到"小红书扫码"
  3. 提取二维码 → 存 /tmp/xhs_qr.png → 上传图床 (可选)
  4. 保持浏览器打开, 轮询检测登录成功
  5. 登录成功后抓全部 cookie → 存 xhs-cli cookies.json + ominicrawl 文件

用法:
  python xhs_playwright_login.py            # 默认
  python xhs_playwright_login.py --qr-img /tmp/xhs_qr.png   # 指定二维码输出
"""
import argparse
import json
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from playwright.sync_api import sync_playwright

STATUS_LOG = "/tmp/xhs_pw_login.status.log"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def log(msg: str):
    with open(STATUS_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    print(msg, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qr-img", default="/tmp/xhs_qr.png", help="二维码输出路径")
    parser.add_argument("--timeout", type=int, default=300, help="等待扫码秒数")
    parser.add_argument("--upload", action="store_true", help="用 picgo 上传二维码拿公网 URL")
    args = parser.parse_args()

    open(STATUS_LOG, "w", encoding="utf-8").close()
    qr_path = Path(args.qr_img)
    qr_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent=UA,
            locale="zh-CN",
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        log("🚀 启动 Chromium...")

        page.goto("https://www.xiaohongshu.com/explore", timeout=40000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        log("✅ 已打开小红书")

        # 1. 点登录
        try:
            page.locator("text=登录").first.click(timeout=8000)
            page.wait_for_timeout(2500)
            log("✅ 已点击登录")
        except Exception as e:
            log(f"⚠️ 点登录失败: {e}")

        # 2. 切到"小红书扫码" (登录弹窗里有 "小红书 或 微信 扫码" / 切 tab)
        # 尝试点 "小红书" 文字 (tab 切换)
        qr_found = False
        for _ in range(3):
            try:
                # 尝试直接点 "小红书" tab (在登录弹窗里)
                # 登录框通常有 tab: 验证码登录 / 扫码登录
                el = page.locator("text=小红书").nth(1)  # 可能是扫码 tab
                if el.count() > 0:
                    el.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    log("✅ 切换到小红书扫码")
                    qr_found = True
                    break
            except Exception:
                pass
            page.wait_for_timeout(1000)

        if not qr_found:
            # 尝试找二维码容器
            log("尝试直接找二维码 img...")

        # 3. 提取二维码 — 找正方形的 base64 img (XHS 登录二维码是 128x128 方形)
        import base64, re, io
        extracted = False
        for _ in range(8):
            try:
                imgs = page.locator("img")
                for i in range(imgs.count()):
                    try:
                        src = imgs.nth(i).get_attribute("src")
                        if src and src.startswith("data:image/png;base64,"):
                            m = re.match(r"data:image/(\w+);base64,(.+)", src)
                            if m:
                                data = base64.b64decode(m.group(2))
                                # 判断是否方形二维码 (用 PIL 读尺寸)
                                try:
                                    from PIL import Image as _Image
                                    _img = _Image.open(io.BytesIO(data))
                                    w, h = _img.size
                                except Exception:
                                    w, h = 0, 0
                                if w == h and w >= 100:
                                    qr_path.write_bytes(data)
                                    log(f"✅ 二维码已保存: {qr_path} ({w}x{h} {len(data)}B)")
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
            # 兜底: 用 tip 区域 element screenshot
            try:
                tip = page.locator("div.tip")
                if tip.count() > 0:
                    tip.nth(0).screenshot(path=str(qr_path))
                    log(f"⚠️ 未找到方形二维码, 保存扫码区域截图: {qr_path}")
                else:
                    page.screenshot(path=str(qr_path))
                    log(f"⚠️ 未找到二维码, 保存整页截图: {qr_path}")
            except Exception as e:
                page.screenshot(path=str(qr_path))
                log(f"⚠️ 未找到二维码, 保存整页截图: {qr_path} ({e})")

        # 上传二维码 (可选)
        if args.upload and extracted:
            try:
                from picgo_upload import upload
                # 用 picgo_upload 上传
                import subprocess
                r = subprocess.run(
                    ["/home/ubuntu/.dsh/profiles/web/node_modules/picgo/bin/picgo", "upload", str(qr_path)],
                    capture_output=True, text=True, timeout=60,
                )
                log(f"picgo 输出: {r.stdout[-300:]}")
            except Exception as e:
                log(f"上传失败: {e}")

        # 4. 轮询检测登录成功 (URL 变化 / 有用户头像 / cookie 有 web_session)
        log("⏳ 等待扫码 (浏览器保持打开)...")
        start = time.time()
        logged_in = False
        while (time.time() - start) < args.timeout:
            time.sleep(3)
            try:
                # 检查 cookie
                cookies = ctx.cookies("https://www.xiaohongshu.com")
                has_web_session = any(c["name"] == "web_session" and c["value"] for c in cookies)
                has_id_token = any(c["name"] == "id_token" and c["value"] for c in cookies)
                if has_web_session and has_id_token:
                    log("✅ 检测到登录成功! (web_session + id_token)")
                    logged_in = True
                    break
            except Exception as e:
                log(f"⚠️ 检测异常: {e}")

        if not logged_in:
            log("❌ 超时未检测到登录")
            browser.close()
            return 1

        # 5. 抓全部 cookie
        all_cookies = ctx.cookies()
        cookie_dict = {c["name"]: c["value"] for c in all_cookies if c["name"] not in ("saved_at",)}
        log(f"📦 抓取 {len(cookie_dict)} 个 cookie")

        # 存 xhs-cli
        xhs_cookie_path = Path.home() / ".xiaohongshu-cli" / "cookies.json"
        xhs_cookie_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**cookie_dict, "saved_at": time.time()}
        xhs_cookie_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        xhs_cookie_path.chmod(0o600)
        log(f"✅ 已存 xhs-cli: {xhs_cookie_path}")

        # 存 ominicrawl
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        ome_cookie = Path.home() / ".agents" / "credentials" / "ominicrawl" / "xiaohongshu.txt"
        ome_cookie.write_text(cookie_str, encoding="utf-8")
        log(f"✅ 已存 ominicrawl: {ome_cookie}")

        browser.close()
        log("✅ 完成! 浏览器已关闭")
        return 0


if __name__ == "__main__":
    sys.exit(main())
