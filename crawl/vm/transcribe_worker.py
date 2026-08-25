#!/usr/bin/env python3
# transcribe_worker.py -- Bailian FunASR 常驻 worker (Groq fallback)
import os, sys, json, time, tempfile, datetime
from pathlib import Path
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

VAULT = os.environ.get("VAULT", "/home/ubuntu/webdav/steven_vault")
ZHIPU_KEY_FILE = os.environ.get("ZHIPU_KEY_FILE", "/home/ubuntu/crawl-transcribe/zhipu.json")
ZHIPU_MODEL = os.environ.get("ZHIPU_MODEL", "glm-4-flash")

INBOX = Path(BASE) / "inbox"
DONE  = Path(BASE) / "done"
STATUS = Path(BASE) / "status.jsonl"

GROQ_KEY_FILE = os.environ.get("GROQ_KEY_FILE", os.path.expanduser("~/.agents/credentials/ominicrawl/groq.json"))
GROQ_MODEL = os.environ.get("GROQ_MODEL", "whisper-large-v3")
GROQ_MAX_RETRIES = 30       # 最大重试次数（每次等60s，共30分钟）
GROQ_RETRY_INTERVAL = 60    # 额度不足时等待秒数
BAILIAN_MODEL = os.environ.get("BAILIAN_ASR_MODEL", "fun-asr-mtl-2025-08-25")

def _get_groq_key():
    try:
        return json.load(open(GROQ_KEY_FILE))["api_key"]
    except Exception as e:
        print("[worker] Groq key error: %s" % e, flush=True)
        return None

def transcribe(wav_path):
    """主路: Bailian FunASR; fallback: Groq whisper-large-v3"""
    import subprocess as sp
    wav = str(wav_path)
    basename = os.path.basename(wav)

    # -- Main: Bailian FunASR --
    print("[worker] Bailian ASR: %s" % basename, flush=True)
    try:
        result = sp.run([
            "bl", "speech", "recognize",
            "--url", wav,
            "--model", BAILIAN_MODEL,
            "--language", "zh",
        ], capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            text = result.stdout.strip()
            if text:
                print("[worker] Bailian OK: %d chars" % len(text), flush=True)
                return text
            else:
                print("[worker] Bailian empty, Groq fallback", flush=True)
        else:
            print("[worker] Bailian rc=%d: %s" % (result.returncode, result.stderr[:200]), flush=True)
    except sp.TimeoutExpired:
        print("[worker] Bailian timeout, Groq fallback", flush=True)
    except FileNotFoundError:
        print("[worker] bl not found, Groq fallback", flush=True)
    except Exception as e:
        print("[worker] Bailian error: %s" % e, flush=True)

    # -- Fallback: Groq (may be 403) --
    key = _get_groq_key()
    if not key:
        raise RuntimeError("Bailian failed, Groq key not found")
    for attempt in range(1, GROQ_MAX_RETRIES + 1):
        print("[worker] Groq fallback %d/%d: %s" % (attempt, GROQ_MAX_RETRIES, basename), flush=True)
        try:
            result = sp.run([
                "curl", "-s", "-w", "\n%%{http_code}",
                "-X", "POST", "https://api.groq.com/openai/v1/audio/transcriptions",
                "-H", "Authorization: Bearer " + key,
                "-F", "model=" + GROQ_MODEL,
                "-F", "language=zh",
                "-F", "response_format=json",
                "-F", "file=@" + wav + ";type=audio/wav",
            ], capture_output=True, text=True, timeout=300)
            output = result.stdout
            lines2 = output.rsplit("\n", 1)
            body = lines2[0] if len(lines2) > 1 else output
            sc = int(lines2[-1]) if len(lines2) > 1 and lines2[-1].strip().isdigit() else 0
            if sc == 200:
                data = json.loads(body)
                text = data.get("text", "")
                print("[worker] Groq OK: %d chars" % len(text), flush=True)
                return text
            elif sc == 429:
                print("[worker] Groq 429, wait %ds..." % GROQ_RETRY_INTERVAL, flush=True)
                time.sleep(GROQ_RETRY_INTERVAL); continue
            elif sc in (403, 401):
                print("[worker] Groq %d Forbidden" % sc, flush=True); return ""
            elif sc == 413:
                print("[worker] Groq 413 too large"); return ""
            else:
                print("[worker] Groq %d: %s" % (sc, body[:200]), flush=True)
                if sc >= 500: time.sleep(GROQ_RETRY_INTERVAL); continue
                return ""
        except sp.TimeoutExpired:
            print("[worker] Groq timeout, retry..."); time.sleep(GROQ_RETRY_INTERVAL); continue
        except Exception as e:
            print("[worker] Groq exception: %s" % e, flush=True)
            time.sleep(GROQ_RETRY_INTERVAL); continue
    raise RuntimeError("All ASR failed: Bailian + Groq")

def summarize(text):
    print("[worker] summarizing with GLM ...", flush=True)
    t0 = time.time()
    from openai import OpenAI
    key = json.load(open(ZHIPU_KEY_FILE))["api_key"]
    client = OpenAI(api_key=key, base_url="https://open.bigmodel.cn/api/paas/v4")
    prompt = (
        "你是专业内容总结助手。下面是一段视频/音频的完整转录文本（可能口语化、无标点、有错别字，请先理解语义再总结）。\n\n"
        "请对内容做一份高质量、信息密度高的中文总结：\n\n"
        "## 结构要求（自主组织，不要硬套模板）\n"
        "根据内容本身选择最合适的结构，可以参考：\n"
        "- 一句话核心（必须含具体信息，不能是空话）\n"
        "- 关键信息（按逻辑分点，可加小标题、列表、甚至表格）\n"
        "- 核心金句（原文中信息量大的句子，可原样引用）\n"
        "- 关键词（3-8 个）\n"
        "如果内容适合别的结构，就用你觉得最好的。\n\n"
        "## 信息密度优先\n"
        "1. 所有具体数据必须保留：数字、百分比、金额、时间、涨跌幅、基金/股票/产品名称\n"
        "2. 所有专有名词必须保留：人物、公司、机构、板块、地名\n"
        "3. 对比关系、因果链必须保留\n\n"
        "## 禁止\n"
        "- 禁止\"市场存在风险\"\"值得关注\"这类空话\n"
        "- 禁止\"本文认为\"\"博主说\"这类元描述开头\n\n"
        "转录文本：\n" + text[:15000]
    )
    try:
        resp = client.chat.completions.create(
            model=ZHIPU_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000,
        )
        result = resp.choices[0].message.content.strip()
        print("[worker] summary done in %.1fs" % (time.time()-t0), flush=True)
        return "## 总结\n\n" + result + "\n"
    except Exception as e:
        print("[worker] warn GLM error: %s" % e, flush=True)
        return "## 总结\n\n" + text[:500] + "...\n"

def process_one(wav_path, meta_path):
    name = wav_path.stem
    meta = json.loads(meta_path.read_text())
    platform = meta.get("platform", "bilibili")
    author = meta.get("author", "未知作者")
    title = meta.get("title") or name
    source_url = meta.get("source_url", "")
    today_str = time.strftime("%Y-%m-%d")
    desc = meta.get("desc", "") or ""

    t0 = time.time()
    print("[worker] transcribing %s ..." % name, flush=True)
    t1 = time.time()
    text = transcribe(str(wav_path))
    print("[worker] transcript %d chars in %.1fs" % (len(text), time.time()-t1), flush=True)
    if not text:
        print("[worker] empty transcript: %s" % name, flush=True)
        return False

    t2 = time.time()
    summary_section = summarize(text)
    print("[worker] summary in %.1fs" % (time.time()-t2), flush=True)

    desc_block = "## 描述\n\n" + desc + "\n\n" if desc else ""
    body = summary_section + desc_block + "## 转录\n\n" + text + "\n"

    from publish_vault import append_single_to_hot
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    tmp.write("---\n")
    tmp.write("title: \"" + title + "\"\n")
    tmp.write("author: \"" + author + "\"\n")
    tmp.write("platform: \"" + platform + "\"\n")
    tmp.write("publish_date: \"" + today_str + "\"\n")
    tmp.write("created: \"" + datetime.datetime.now().astimezone().isoformat() + "\"\n")
    if source_url:
        tmp.write("source_url: \"" + source_url + "\"\n")
    tmp.write("---\n\n")
    tmp.write(body)
    tmp.close()

    fpath, info = append_single_to_hot(platform, tmp.name,
                                       title=title, author=author, force_overwrite=True)
    os.unlink(tmp.name)

    if fpath:
        print("[worker] published %s (%.0fs)" % (name, time.time()-t0), flush=True)
        try:
            wav_path.unlink()
        except Exception as e:
            print("[worker] delete wav failed: %s" % e, flush=True)
        try:
            shutil.copy2(meta_path, DONE / meta_path.name)
            meta_path.unlink()
        except Exception:
            pass
        return True
    else:
        print("[worker] publish failed: %s" % name, flush=True)
        return False

def find_pairs():
    pairs = []
    for ext in ("*.wav", "*.mp3", "*.m4a", "*.mp4"):
        for wav in INBOX.glob(ext):
            meta = wav.with_suffix(".meta.json")
            if meta.exists():
                pairs.append((wav, meta))
    def _plat(n):
        return "douyin" if n.startswith("douyin_") else "bilibili"
    g = {"bilibili": [], "douyin": []}
    for pw in pairs:
        g[_plat(pw[0].name)].append(pw)
    out = []
    i = j = 0
    while i < len(g["douyin"]) or j < len(g["bilibili"]):
        if i < len(g["douyin"]):
            out.append(g["douyin"][i]); i += 1
        if j < len(g["bilibili"]):
            out.append(g["bilibili"][j]); j += 1
    return out

def write_status(name, platform, ok, detail, dur):
    video_id = name.split("_", 1)[-1] if "_" in name else name
    try:
        with open(STATUS, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "platform": platform, "video_id": video_id,
                "stage": "transcribe+summarize+publish", "ok": ok,
                "detail": detail, "dur": round(dur, 1)
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

def run():
    while True:
        pairs = find_pairs()
        if not pairs:
            time.sleep(10)
            continue
        wav, meta = pairs[0]
        name = wav.stem
        platform = "?"
        try:
            platform = json.loads(meta.read_text()).get("platform", "?")
        except Exception:
            pass
        print("[worker] processing %s" % name, flush=True)
        t0 = time.time()
        try:
            ok = process_one(wav, meta)
            dur = time.time() - t0
            write_status(name, platform, ok, "成功" if ok else "失败", dur)
        except Exception as e:
            print("[worker] exception for %s: %s" % (name, e), flush=True)
            write_status(name, platform, False, str(e)[:200], time.time()-t0)
            time.sleep(5)

if __name__ == "__main__":
    run()
