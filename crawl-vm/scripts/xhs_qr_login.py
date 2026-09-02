#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/xhs_qr_login.py — VM 端小红书扫码登录（给用户看二维码，绕开终端渲染）

纯 HTTP 路径（不需要 camoufox / 浏览器）:
  1. 生成临时 a1+webId → login_activate → 游客 session
  2. create_qr_login → 拿 qr_url
  3. 把 qr_url 渲染成 /tmp/xhs_qr.png (可给用户看/上图床)
  4. 轮询扫码状态 → 确认后保存 cookies 到 ~/.xiaohongshu-cli/cookies.json
  5. 同时同步到 ~/.agents/credentials/ominicrawl/xiaohongshu.txt

用法:
  python xhs_qr_login.py [timeout_s]   # 默认 240s 等待扫码

说明:
 - qrcode 终端渲染对 headless VM 无意义, 改为 PNG 输出
 - on_status 回调把状态信息也写进日志文件, 供外部轮询
"""
import json
import os
import sys
import time
from pathlib import Path

# 允许从任何 cwd 运行
SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(SKILL_DIR / "common"))

from xhs_cli.qr_login import _generate_a1, _generate_webid, QR_WAITING, QR_SCANNED, QR_CONFIRMED
from xhs_cli.client import XhsClient
from xhs_cli.cookies import save_cookies

QR_PNG = "/tmp/xhs_qr.png"
STATUS_LOG = "/tmp/xhs_qr_login.status.log"


def log(msg: str):
    with open(STATUS_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    print(msg, flush=True)


def save_qr_png(qr_url: str) -> str:
    """生成二维码 PNG, 返回路径"""
    import qrcode
    img = qrcode.make(qr_url)
    img.save(QR_PNG)
    return QR_PNG


def main():
    timeout_s = int(sys.argv[1]) if len(sys.argv) > 1 else 240
    # 清空状态日志
    open(STATUS_LOG, "w", encoding="utf-8").close()

    a1 = _generate_a1()
    webid = _generate_webid()
    tmp_cookies = {"a1": a1, "webId": webid}
    log("🔑 启动 QR login (pure HTTP)...")

    with XhsClient(tmp_cookies, request_delay=0, timeout=60.0) as client:
        # 1. activate (游客 session)
        try:
            activate = client.login_activate()
            session = activate.get("session", "")
            secure_session = activate.get("secure_session", "")
            if session:
                client.cookies["web_session"] = str(session)
            if secure_session:
                client.cookies["web_session_sec"] = str(secure_session)
            log("✅ activate 完成 (游客 session 就绪)")
        except Exception as e:
            log(f"⚠️  activate 失败(非致命): {e}")

        # 2. create QR
        qr_data = client.create_qr_login()
        qr_id = qr_data["qr_id"]
        code = qr_data["code"]
        qr_url = qr_data["url"]
        log(f"✅ 二维码已创建: qr_id={qr_id[:12]}.. code={code}")

        # 3. 保存二维码 PNG
        png = save_qr_png(qr_url)
        log(f"📱 二维码 PNG: {png}")
        log(f"🔗 扫码 URL: {qr_url}")

        # 4. 轮询
        start = time.time()
        last_status = -1
        consecutive_errors = 0
        while (time.time() - start) < timeout_s:
            time.sleep(2)
            try:
                status_data = client.check_qr_status(qr_id, code)
            except Exception as e:
                consecutive_errors += 1
                log(f"⚠️  状态查询失败({consecutive_errors}): {e}")
                if consecutive_errors >= 3:
                    log("❌ 连续失败, 退出")
                    return 1
                continue
            consecutive_errors = 0

            code_status = status_data.get("codeStatus", -1)
            if code_status != last_status:
                last_status = code_status
                if code_status == QR_SCANNED:
                    log("📲 已扫码! 等待确认...")
                elif code_status == QR_CONFIRMED:
                    log("✅ 已确认登录!")
                    break
                elif code_status == QR_WAITING:
                    log("⏳ 等待扫码...(二维码已生成)")

        if last_status != QR_CONFIRMED:
            log("❌ 超时未扫码")
            return 1

        # 5. complete login → 拿最终 cookie
        for attempt in range(3):
            try:
                completion = client.complete_qr_login(qr_id, code)
                if completion.get("session") or completion.get("login_info", {}).get("session"):
                    session = completion.get("session") or completion.get("login_info", {}).get("session", "")
                    if session:
                        client.cookies["web_session"] = str(session)
                secure_session = completion.get("secure_session") or completion.get("login_info", {}).get("secure_session", "")
                if secure_session:
                    client.cookies["web_session_sec"] = str(secure_session)
                break
            except Exception as e:
                log(f"⚠️  complete {attempt+1} 失败: {e}")
                time.sleep(2)

        # 6. save
        save_cookies(client.cookies)
        log(f"✅ cookies 已保存: ~/.xiaohongshu-cli/cookies.json ({len(client.cookies)} fields)")
        # 同步到 crawl-vm cookie 文件
        cookie_str = "; ".join(f"{k}={v}" for k, v in client.cookies.items() if "saved_at" not in k)
        ome_cookie = Path.home() / ".agents" / "credentials" / "ominicrawl" / "xiaohongshu.txt"
        ome_cookie.write_text(cookie_str, encoding="utf-8")
        log(f"✅ 已同步: {ome_cookie}")
        return 0


if __name__ == "__main__":
    sys.exit(main())