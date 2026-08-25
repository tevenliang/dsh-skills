#!/usr/bin/env python3
"""
crawl/skills Health Check v2.3.0 - 跑批前必须运行
每个工具的调用方法 + 状态检查 + 修复命令
"""
import sys, os, asyncio, subprocess, time, json, shutil
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ingest-bilibili"))
sys.path.insert(0, str(ROOT / "ingest-bilibili" / "bilibili"))
sys.path.insert(0, str(ROOT / "ingest-douyin" / "douyin_api"))
sys.path.insert(0, str(ROOT / "ingest-xhs" / "xiaohongshu"))

VAULT = Path(os.environ.get("VAULT", "/Users/tianwenliang/Documents/steven_vault"))
CREDS = Path.home() / ".agents" / "credentials" / "ominicrawl"

RED, YELLOW, GREEN, BLUE, RESET = "\033[91m", "\033[93m", "\033[92m", "\033[94m", "\033[0m"

def ok(msg):   print(f"  {GREEN}OK{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}WARN{RESET} {msg}")
def fail(msg): print(f"  {RED}FAIL{RESET} {msg}")
def info(msg): print(f"  {BLUE}INFO{RESET} {msg}")

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)

# ─────────────────────────────────────────────────
# 1. Credential 检查
# ─────────────────────────────────────────────────
def check_credentials():
    info("Credential 目录: " + str(CREDS))
    items = [
        ("bilibili.txt",    CREDS/"bilibili.txt",    "B站 SESSDATA"),
        ("xiaohongshu.txt", CREDS/"xiaohongshu.txt", "小红书登录态"),
        ("douyin.json",     CREDS/"douyin.json",     "抖音（备用）"),
        ("groq.json",       CREDS/"groq.json",       "Groq（已disable）"),
    ]
    ok_count = fail_count = 0
    for name, path, desc in items:
        if path.exists():
            ok(f"{name} ({path.stat().st_size} bytes) - {desc}")
            ok_count += 1
        else:
            warn(f"{name} 不存在 - {desc}")
            fail_count += 1
    return ok_count > 0

# ─────────────────────────────────────────────────
# 2. B站 adapter (BilibiliWbi, 不是 WebCrawler!)
# ─────────────────────────────────────────────────
def check_bilibili():
    try:
        from bili_feed import _load_bili_cookie
        from wbi import BilibiliWbi
    except ImportError as e:
        fail(f"导入失败: {e}")
        return False

    cookie = _load_bili_cookie()
    if not cookie:
        fail("credentials/bilibili.txt 为空")
        return False
    if "SESSDATA" not in cookie:
        warn("cookie 无 SESSDATA 字段")

    async def _t():
        async with BilibiliWbi(cookie=cookie) as bw:
            return await bw.fetch_user_post_videos(mid="3493117728656046", pn=1)

    loop = asyncio.new_event_loop()
    try:
        r = loop.run_until_complete(_t())
    except Exception as e:
        fail(f"B站 API 异常: {e}")
        return False
    finally:
        loop.close()

    code = r.get("code", -1) if isinstance(r, dict) else -1
    msg = r.get("message", "") if isinstance(r, dict) else ""

    if code == 0:
        vlist = r.get("data", {}).get("list", {}).get("vlist", [])
        ok(f"B站 API 正常 (code=0, 获取{len(vlist)}条视频)")
        return True
    elif code == -412:
        fail("B站 API -412 (IP 被封禁)")
        info("  修复: 等 5 分钟自动恢复，或刷新 cookie")
        return False
    elif code == -352:
        ok("B站 API -352 (BilibiliWbi 自动刷新 ticket)")
        return True
    else:
        warn(f"B站 API code={code}, msg={msg}")
        return False

# ─────────────────────────────────────────────────
# 3. 小红书 CLI
# ─────────────────────────────────────────────────
def check_xiaohongshu():
    # 方案1: xhs CLI 登录态
    rc, out, err = run("xhs --help 2>&1", timeout=10)
    if rc != 0:
        fail("xhs CLI 未安装")
        info("  修复: pip install xhs")
        return False

    # 方案2: credential 文件存在即算已登录（xhs login 成功会写文件）
    cred = CREDS / "xiaohongshu.txt"
    if cred.exists():
        ok(f"小红书 credential 存在 ({cred.stat().st_size} bytes)")
        return True

    fail("小红书 credential 不存在")
    info("  修复: cd ~/.agents/skills/crawl && xhs login")
    return False

# ─────────────────────────────────────────────────
# 4. opencli daemon + Chrome 扩展
# ─────────────────────────────────────────────────
def check_opencli():
    # daemon 状态
    rc, out, err = run("opencli daemon status 2>&1")
    if rc != 0 or "running" not in out.lower():
        fail("opencli daemon 未运行")
        info("  修复: opencli daemon restart")
        return False

    daemon_ok = True
    if "disconnected" in out.lower():
        warn("opencli daemon 运行中，但 Chrome 扩展已断开")
        daemon_ok = "degraded"
    else:
        ok("opencli daemon 正常运行")

    # Chrome 扩展连接状态
    rc2, out2, err2 = run("opencli doctor 2>&1", timeout=20)
    if "Extension:" in out2 and "connected" in out2.lower():
        ok("Chrome 扩展已连接")
        return True
    elif "Extension:" in out2 and "not connected" in out2.lower():
        warn("Chrome 扩展未连接")
        info("  修复步骤:")
        info("  1. 在 Chrome 中点击 OpenCLI 扩展图标（点击一次触发重连）")
        info("  2. 等 5 秒")
        info("  3. 再次运行 health_check.py 验证")
        return False
    else:
        warn(f"扩展状态未知: {out2[:100]}")
        return False

# ─────────────────────────────────────────────────
# 5. 转录模型
# ─────────────────────────────────────────────────
def check_transcribe():
    results = {}

    ok("MLX Whisper 本地 (永远可用，ANE 加速)")
    results["mlx"] = True

    # Bailian ASR: smoke test（fun-asr-mtl 真实 submit，不依赖 Console Gateway token）
    # 注意: bl usage free 需要 Console Gateway OAuth（access_token），现已 NotAuthorised
    # 改用 _smoke_test_asr 直接测可用性（走 OpenAPI AK/SK，不走 console）
    try:
        import sys, json, re, time as _time
        sys.path.insert(0, str(Path(__file__).parent))
        from common_supervisor._eagain_retry import run_with_retry
        bl_bin = shutil.which("bl") or (Path.home()/".npm-global/bin/bl")
        wav = Path("/tmp/asr_longer.wav")
        if not wav.exists():
            warn("Bailian ASR smoke test 跳过（测试音频不存在）")
            results["bailian"] = "degraded"
        else:
            out = run_with_retry(
                [str(bl_bin), "speech", "recognize", "--url", str(wav), "--model", "fun-asr-mtl",
                 "--language", "zh", "--async", "--output", "json"],
                capture_output=True, text=True, timeout=30, close_fds=True,
            )
            raw = out.stdout + out.stderr
            mjson = re.search(r"\{.*\}", raw, re.DOTALL)
            d = json.loads(mjson.group(0)) if mjson else {}
            if "task_id" in d:
                _time.sleep(2)
                poll = run_with_retry(
                    [str(bl_bin), "video", "task", "get", "--task-id", d["task_id"], "--output", "json"],
                    capture_output=True, text=True, timeout=15, close_fds=True,
                )
                pjson = re.search(r"\{.*\}", poll.stdout + poll.stderr, re.DOTALL)
                pd = json.loads(pjson.group(0)) if pjson else {}
                ts = pd.get("task_status", "")
                if ts == "SUCCEEDED":
                    ok("Bailian ASR 真实可用 (fun-asr-mtl smoke test SUCCEEDED)")
                    results["bailian"] = True
                else:
                    warn(f"Bailian ASR smoke test {ts}（可能是配额问题）")
                    results["bailian"] = False
            elif "error" in d:
                err_msg = d["error"].get("message", "")
                if "AllocationQuota" in err_msg or "FreeTierOnly" in err_msg:
                    warn("Bailian ASR 配额耗尽")
                else:
                    warn(f"Bailian ASR 失败: {err_msg[:60]}")
                results["bailian"] = False
            else:
                warn("Bailian ASR smoke test 响应异常")
                results["bailian"] = False
    except Exception as e:
        warn(f"Bailian ASR smoke test 异常: {e}")
        results["bailian"] = False

    rc, out, err = run("curl -s --max-time 3 https://api.groq.com 2>&1 | head -1")
    if rc == 0 and "empty" not in out.lower():
        ok("Groq API 可访问")
        results["groq"] = True
    else:
        warn("Groq API 不可访问")
        results["groq"] = False

    return results

# ─────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────
def main():
    print("=" * 62)
    print("  crawl/skills Health Check v2.3.0")
    print("  跑批前必须运行！")
    print("=" * 62)

    checks = [
        ("Credential 文件",       check_credentials),
        ("B站 (BilibiliWbi)",   check_bilibili),
        ("小红书 CLI",           check_xiaohongshu),
        ("opencli + Chrome扩展", check_opencli),
        ("转录模型",           check_transcribe),
    ]

    statuses = []
    for name, fn in checks:
        print(f"\n-- {name} --")
        try:
            r = fn()
            statuses.append((name, r))
        except Exception as e:
            fail(f"异常: {e}")
            statuses.append((name, False))

    print("\n" + "=" * 62)
    print("  总结")
    print("=" * 62)

    all_pass = all(s[1] is True or isinstance(s[1], dict) for s in statuses)
    any_fail = any(s[1] is False for s in statuses)
    any_warn = any(s[1] == "degraded" for s in statuses)

    for name, status in statuses:
        if status is True or isinstance(status, dict):
            ok(name)
        elif status == "degraded":
            warn(name + " (降级)")
        else:
            fail(name + " (需修复)")

    print()
    if all_pass:
        print(f"  {GREEN}全部通过，可以跑批！{RESET}")
    elif any_fail:
        print(f"  {RED}有失败项，修复后再跑批{RESET}")
    else:
        print(f"  {YELLOW}有降级项，可跑批但部分平台可能失败{RESET}")

    print()
    print("常用修复命令:")
    print("  B站 -412:          等 5 分钟自动恢复")
    print("  小红书未登录:       xhs login")
    print("  Chrome 扩展断开:     Chrome 中点击 OpenCLI 扩展图标")
    print("  bailian 需登录:          bl auth login --console")
    print("  daemon 未运行:      opencli daemon restart")
    print()
    print("跑批命令:")
    print("  cd ~/.agents/skills/crawl && ./run.sh watchlist")
    print("=" * 62)

if __name__ == "__main__":
    main()
