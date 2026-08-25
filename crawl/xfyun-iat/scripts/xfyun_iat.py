#!/usr/bin/env python3
"""讯飞语音听写(iat)流式转写 CLI，支持超长音频自动分段。
凭证从环境变量读：XFYUN_APPID / XFYUN_APIKEY / XFYUN_APISECRET
用法:
  python3 xfyun_iat.py audio.pcm
  python3 xfyun_iat.py audio.wav --auto-resample
  python3 xfyun_iat.py long_audio.wav --chunk-seconds 50   # 50s 分段，留余量防越界
注意：讯飞服务端单次处理约 60s，对真实语音音频 50s 分段足够。
      sine wave 等无语音内容会触发 VAD 超时导致 broken pipe（非代码问题，是音频内容问题）。
"""
import base64, hashlib, hmac, json, os, sys, time, threading, subprocess, tempfile, shutil, argparse, wave

HOST = "iat-api.xfyun.cn"
URI  = f"wss://{HOST}/v2/iat"
MAX_CHUNK_SEC = 50  # 留 10s 余量

def build_url(appid, apikey, apisec):
    date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
    sign_str = f"host: {HOST}\ndate: {date}\nGET /v2/iat HTTP/1.1"
    sig = base64.b64encode(hmac.new(apisec.encode(), sign_str.encode(), hashlib.sha256).digest()).decode()
    auth = (f'api_key="{apikey}", algorithm="hmac-sha256", headers="host date request-line", '
            f'signature="{sig}"')
    return f"{URI}?authorization={base64.b64encode(auth.encode()).decode()}&date={date.replace(' ','%20')}&host={HOST}"

def to_pcm16k(path):
    if path.lower().endswith(".pcm") and not shutil.which("ffmpeg"):
        return path
    if path.lower().endswith(".pcm"):
        return path
    tmp = tempfile.NamedTemporaryFile(suffix=".pcm", delete=False).name
    subprocess.run(["ffmpeg","-y","-i",path,"-ar","16000","-ac","1","-f","s16le",
                    "-acodec","pcm_s16le",tmp], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tmp

import websocket

def _transcribe_one_chunk(pcm_path, appid, apikey, apisec, lang="zh_cn", timeout=65):
    """单次 WebSocket 转录（<=50s 音频）。timeout=65 留 5s 余量。"""
    class _C:
        def __init__(s):
            s.txt=""; s.done=threading.Event(); s.ok=False; s.err=None
        def on_open(s, ws):
            with open(pcm_path,"rb") as f: data=f.read()
            step=1280; st=0
            for i in range(0, len(data), step):
                ch=data[i:i+step]
                st = 2 if (i+step >= len(data)) else (1 if i>0 else 0)
                ws.send(json.dumps({
                    "common":{"app_id":appid},
                    "business":{"language":lang,"domain":"iat","accent":"mandarin"},
                    "data":{"status":st,"format":"audio/L16;rate=16000","encoding":"raw",
                             "audio":base64.b64encode(ch).decode()}
                }))
                if st==0: st=1
                time.sleep(0.04)
        def on_message(s, ws, m):
            d=json.loads(m)
            if d.get("code")!=0: s.err=d.get("message"); s.done.set(); return
            for w in d.get("data",{}).get("result",{}).get("ws",[]):
                for c in w.get("cw",[]): s.txt += c.get("w","")
            if d.get("data",{}).get("status")==2: s.ok=True; s.done.set()
        def on_error(s, ws, e): s.err=str(e); s.done.set()
        def on_close(s, ws, *a): s.done.set()
    c=_C()
    ws=websocket.WebSocketApp(build_url(appid,apikey,apisec),
        on_open=c.on_open, on_message=c.on_message, on_error=c.on_error, on_close=c.on_close)
    threading.Thread(target=ws.run_forever, kwargs={"sslopt":{"cert_reqs":0}}, daemon=True).start()
    c.done.wait(timeout=timeout)
    try: ws.close()
    except Exception: pass
    if c.ok: return c.txt
    raise RuntimeError(c.err or "unknown error")

def transcribe_long(pcm_path, appid, apikey, apisec, lang="zh_cn", max_sec=MAX_CHUNK_SEC):
    """超长音频自动分段转录：按 max_sec 秒切 WAV，逐段调用 xfyun，拼接文本。"""
    # 2026-07-21 fix: wave.open() 只支持 WAV；PCM 需要直接读二进制
    try:
        with wave.open(pcm_path) as wf:
            nchannels, sampwidth, framerate, nframes = wf.getparams()[:4]
    except wave.Error:
        # 原始 PCM：手动计算帧数（16bit mono = 2字节/帧）
        with open(pcm_path, "rb") as f:
            raw_data = f.read()
        framerate = 16000
        sampwidth = 2
        nchannels = 1
        nframes = len(raw_data) // (nchannels * sampwidth)
    if framerate != 16000 or sampwidth != 2:
        raise ValueError(f"需要 16kHz/16bit PCM，当前: {framerate}Hz/{sampwidth*8}bit")
    total_sec = nframes / framerate
    if total_sec <= max_sec:
        return _transcribe_one_chunk(pcm_path, appid, apikey, apisec, lang)

    parts = []
    start = 0.0
    while start < total_sec:
        chunk_sec = min(max_sec, total_sec - start)
        chunk_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            rc = subprocess.run([
                "ffmpeg", "-y",
                "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", pcm_path,
                "-ss", f"{start:.2f}", "-t", f"{chunk_sec:.2f}",
                "-ar", "16000", "-ac", "1", chunk_wav
            ], capture_output=True)
            if rc.returncode != 0:
                raise RuntimeError(f"ffmpeg 切分段失败: {rc.stderr.decode()[:200]}")
            txt = _transcribe_one_chunk(chunk_wav, appid, apikey, apisec, lang)
            parts.append(txt)
        finally:
            try: os.unlink(chunk_wav)
            except Exception: pass
        start += chunk_sec
    return "".join(parts)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--auto-resample", action="store_true")
    ap.add_argument("--lang", default="zh_cn")
    ap.add_argument("--chunk-seconds", type=int, default=MAX_CHUNK_SEC,
                    help=f"分段大小(秒)，默认{MAX_CHUNK_SEC}s，留余量防越界")
    a = ap.parse_args()
    appid   = os.environ["XFYUN_APPID"]
    apikey  = os.environ["XFYUN_APIKEY"]
    apisec  = os.environ["XFYUN_APISECRET"]
    pcm = a.audio if (not a.auto_resample or a.audio.lower().endswith(".pcm")) else to_pcm16k(a.audio)
    try:
        txt = transcribe_long(pcm, appid, apikey, apisec, a.lang, max_sec=a.chunk_seconds)
        print(txt)
    finally:
        if a.auto_resample and pcm != a.audio:
            try: os.unlink(pcm)
            except Exception: pass
