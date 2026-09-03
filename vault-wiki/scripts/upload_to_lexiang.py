#!/usr/bin/env python3
"""upload_to_lexiang.py — vault-wiki v8 Step 5：把 wiki 笔记上传到乐享知识库。

用法：
    python3 upload_to_lexiang.py --vault "$VAULT" --note "path/to/wiki.md" --l1 "21_ai_agent"

配置：
    需要 LEXIANG_TOKEN 已在 mcp.json 中配置，参见 references/lexiang-setup.md

输出：
    - uploaded/lexiang_uploads.json   成功 entry_id 映射
    - uploaded/lexiang_failures.json  失败项 + 原因
    - uploaded/upload_log.txt         完整日志
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def find_mcp_config():
    """查找已配置的乐享 MCP 配置。"""
    candidates = [
        os.path.expanduser("~/.agents/skills/archive/lexiang-mcp-skill/mcp.json"),
        os.path.expanduser("~/.mcporter/mcporter.json"),
        os.path.expanduser("~/.dsh/mcp.json"),
        os.path.expanduser("~/.workbuddy/mcp.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                cfg = json.load(open(path))
                servers = cfg.get("mcpServers", {})
                if "lexiang" in servers:
                    return servers["lexiang"], path
            except Exception:
                continue
    return None, None


def parse_lexiang_url(url):
    """从 mcp URL 提取 company_from。"""
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return qs.get("company_from", [""])[0]


def curl_mcp(lex_url, token, method, params, session_id, timeout=180):
    """Call MCP endpoint with one JSON-RPC request."""
    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000) % 1000000,
        "method": method,
        "params": params,
    }
    cmd = [
        "curl", "-s", "--max-time", str(timeout),
        "-X", "POST", lex_url,
        "-H", f"Authorization: Bearer {token}",
        "-H", "Content-Type: application/json; charset=utf-8",
        "-H", "Accept: application/json, text/event-stream",
        "-H", f"Mcp-Session-Id: {session_id}",
        "--data-binary", "@-",
    ]
    proc = subprocess.run(cmd, input=json.dumps(payload, ensure_ascii=False),
                          capture_output=True, text=True)
    raw = proc.stdout.strip()
    if not raw or "<!DOCTYPE html>" in raw or "WAF" in raw:
        return None, f"network/waf error: {raw[:200]}"
    try:
        return json.loads(raw), None
    except Exception as e:
        return None, f"json parse error: {e}, raw={raw[:200]}"


def init_session(lex_url, token, sid):
    r, err = curl_mcp(lex_url, token, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "vault-wiki-uploader", "version": "8.0.0"},
    }, sid)
    if err:
        return False, err
    curl_mcp(lex_url, token, "notifications/initialized", {}, sid)
    return True, None


def whoami(lex_url, token, sid):
    r, err = curl_mcp(lex_url, token, "tools/call", {
        "name": "whoami",
        "arguments": {},
    }, sid)
    if err:
        return None, err
    text = r.get("result", {}).get("content", [{}])[0].get("text", "{}")
    try:
        return json.loads(text), None
    except Exception as e:
        return None, f"parse error: {e}"


def create_folder(lex_url, token, sid, space_id, parent_id, name):
    r, err = curl_mcp(lex_url, token, "tools/call", {
        "name": "entry_create_entry",
        "arguments": {
            "entry_type": "folder",
            "parent_entry_id": parent_id,
            "name": name,
        },
    }, sid)
    if err:
        return None, err
    text = r.get("result", {}).get("content", [{}])[0].get("text", "{}")
    try:
        parsed = json.loads(text)
        if parsed.get("code") != 0:
            return None, f"create folder failed: {parsed}"
        return parsed["data"]["entry"]["id"], None
    except Exception as e:
        return None, f"parse error: {e}"


def upload_content(lex_url, token, sid, space_id, parent_id, name, content):
    r, err = curl_mcp(lex_url, token, "tools/call", {
        "name": "entry_import_content",
        "arguments": {
            "content": content,
            "content_type": "markdown",
            "name": name,
            "parent_id": parent_id,
            "space_id": space_id,
        },
    }, sid, timeout=300)
    if err:
        return None, err
    text = r.get("result", {}).get("content", [{}])[0].get("text", "{}")
    try:
        parsed = json.loads(text)
        if parsed.get("code") != 0:
            return None, f"upload failed: {parsed.get('message', parsed)}"
        return parsed["data"]["entry"]["id"], None
    except Exception as e:
        return None, f"parse error: {e}"


def update_frontmatter(note_path, lexiang_url=None, lexiang_status=None):
    """把上传结果写回 wiki frontmatter。"""
    if not os.path.exists(note_path):
        return False, "file not found"

    with open(note_path) as f:
        content = f.read()

    # Find or create frontmatter
    if content.startswith("---"):
        # Has frontmatter
        end = content.find("---", 3)
        if end == -1:
            return False, "frontmatter not closed"
        frontmatter = content[3:end].strip()
        body = content[end+3:]
    else:
        frontmatter = ""
        body = content

    # Parse existing YAML (simple key: value lines)
    lines = frontmatter.split("\n")
    new_lines = []
    has_lexiang_url = False
    has_lexiang_status = False
    has_lexiang_uploaded = False
    for line in lines:
        if line.startswith("lexiang_url:"):
            new_lines.append(f"lexiang_url: \"{lexiang_url or ''}\"")
            has_lexiang_url = True
        elif line.startswith("lexiang_status:"):
            new_lines.append(f"lexiang_status: {lexiang_status or 'unknown'}")
            has_lexiang_status = True
        elif line.startswith("lexiang_uploaded:"):
            has_lexiang_uploaded = True
            new_lines.append(line)
        else:
            new_lines.append(line)

    if not has_lexiang_url and lexiang_url:
        new_lines.append(f"lexiang_url: \"{lexiang_url}\"")
    if not has_lexiang_uploaded and (lexiang_url or lexiang_status):
        new_lines.append(f"lexiang_uploaded: {time.strftime('%Y-%m-%d')}")
    if not has_lexiang_status and lexiang_status:
        new_lines.append(f"lexiang_status: {lexiang_status}")

    new_frontmatter = "\n".join(new_lines)
    new_content = f"---\n{new_frontmatter}\n---{body}"

    with open(note_path, "w") as f:
        f.write(new_content)

    return True, None


def main():
    parser = argparse.ArgumentParser(description="Upload wiki note to Lexiang")
    parser.add_argument("--vault", required=True, help="vault root path")
    parser.add_argument("--note", required=True, help="path to wiki note .md")
    parser.add_argument("--l1", required=True, help="L1 folder name in Lexiang")
    parser.add_argument("--delay", type=float, default=0.6, help="seconds between uploads")
    args = parser.parse_args()

    # Find MCP config
    server, config_path = find_mcp_config()
    if not server:
        print("ERROR: 找不到乐享 MCP 配置。")
        print("请参见 references/lexiang-setup.md 配置 mcp.json。")
        sys.exit(1)

    lex_url = server["url"]
    token = server["headers"]["Authorization"].replace("Bearer ", "")
    company_from = parse_lexiang_url(lex_url)

    print(f"Using config: {config_path}")
    print(f"Company: {company_from}")
    print(f"Note: {args.note}")
    print(f"L1 folder: {args.l1}")

    # Output directory
    uploaded_dir = os.path.join(args.vault, "uploaded")
    os.makedirs(uploaded_dir, exist_ok=True)

    uploads_file = os.path.join(uploaded_dir, "lexiang_uploads.json")
    failures_file = os.path.join(uploaded_dir, "lexiang_failures.json")
    log_file = os.path.join(uploaded_dir, "upload_log.txt")

    # Load existing state
    if os.path.exists(uploads_file):
        with open(uploads_file) as f:
            uploads = json.load(f)
    else:
        uploads = {}
    if os.path.exists(failures_file):
        with open(failures_file) as f:
            failures = json.load(f)
    else:
        failures = {}

    # Init session
    sid = f"vault-wiki-{int(time.time())}"
    ok, err = init_session(lex_url, token, sid)
    if not ok:
        print(f"ERROR: init session failed: {err}")
        sys.exit(1)

    # whoami
    wm, err = whoami(lex_url, token, sid)
    if err:
        print(f"ERROR: whoami failed: {err}")
        sys.exit(1)

    data = wm.get("data", {})
    company = data.get("company", {})
    personal_space = data.get("personal_space", {})

    space_id = personal_space.get("id")
    root_id = personal_space.get("root_entry_id")
    domain = company.get("company_domain", "https://lexiangla.com")
    code = company.get("code", company_from)

    if not space_id or not root_id:
        print("ERROR: 无个人知识库（whoami 未返回 personal_space）")
        sys.exit(1)

    print(f"Personal space: {space_id}")
    print(f"Root: {root_id}")

    # Create or reuse L1 folder
    folder_key = f"__folder__:{args.l1}"
    if folder_key in uploads:
        folder_id = uploads[folder_key]["entry_id"]
        print(f"Reusing folder: {folder_id}")
    else:
        print(f"Creating folder '{args.l1}'...")
        folder_id, err = create_folder(lex_url, token, sid, space_id, root_id, args.l1)
        if err:
            print(f"ERROR: create folder failed: {err}")
            sys.exit(1)
        uploads[folder_key] = {"entry_id": folder_id, "name": args.l1}
        with open(uploads_file, "w") as f:
            json.dump(uploads, f, ensure_ascii=False, indent=2)
        time.sleep(args.delay)
        print(f"Created folder: {folder_id}")

    # Upload note
    name = os.path.basename(args.note)
    if not os.path.exists(args.note):
        print(f"ERROR: note not found: {args.note}")
        sys.exit(1)

    with open(args.note) as f:
        content = f.read()

    if not content.strip():
        print(f"SKIP: note is empty")
        failures[name] = {"error": "content is empty"}
        with open(failures_file, "w") as f:
            json.dump(failures, f, ensure_ascii=False, indent=2)
        sys.exit(0)

    # Skip if already uploaded (check frontmatter or mapping)
    if name in uploads and uploads[name].get("entry_id"):
        print(f"Already uploaded: {uploads[name]['entry_id']}")
        print(f"URL: {uploads[name]['url']}")
        sys.exit(0)

    print(f"Uploading: {name} ({len(content)} bytes)...")
    entry_id, err = upload_content(lex_url, token, sid, space_id, folder_id, name, content)
    if err:
        print(f"FAIL: {err}")
        failures[name] = {"error": err}
        with open(failures_file, "w") as f:
            json.dump(failures, f, ensure_ascii=False, indent=2)

        # Detect WAF block
        if "WAF" in str(err) or "<!DOCTYPE html>" in str(err):
            update_frontmatter(args.note, lexiang_status="waf_blocked")
        else:
            update_frontmatter(args.note, lexiang_status="error")

        sys.exit(1)

    # Build URL
    if "lexiangla.com" in domain and domain.count(".") == 1:
        url = f"{domain}/pages/{entry_id}?company_from={code}"
    else:
        url = f"{domain}/pages/{entry_id}"

    print(f"OK: {url}")
    uploads[name] = {"entry_id": entry_id, "url": url, "name": name}
    with open(uploads_file, "w") as f:
        json.dump(uploads, f, ensure_ascii=False, indent=2)

    # Update frontmatter
    update_frontmatter(args.note, lexiang_url=url)

    # Log
    with open(log_file, "a") as f:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{ts}] OK: {name} -> {url}\n")

    print(f"\nDone. Mapping saved to {uploads_file}")


if __name__ == "__main__":
    main()
