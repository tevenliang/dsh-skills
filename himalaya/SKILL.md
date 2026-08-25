---
name: himalaya
description: CLI to manage emails via IMAP/SMTP. Use `himalaya` to list, read,
  write, reply, forward, search, and organize emails from the terminal. Supports
  multiple accounts and message composition with MML (MIME Meta Language).
homepage: https://github.com/pimalaya/himalaya
metadata:
  clawdbot:
    emoji: 📧
    requires:
      bins:
        - himalaya
    install:
      - id: brew
        kind: brew
        formula: himalaya
        bins:
          - himalaya
        label: Install Himalaya (brew)
disable-model-invocation: true
---

# Himalaya Email CLI

Himalaya is a CLI email client that lets you manage emails from the terminal using IMAP, SMTP, Notmuch, or Sendmail backends.



## 本地配置

**凭证已配置**：（QQ 邮箱，chmod 600）。

**v1.2.0 配置格式**（IMAP + SMTP 同账号）：


**授权码获取**：QQ 邮箱 → 设置 → 账户 → 开启 IMAP/SMTP → 生成授权码（非登录密码）。

## References

- `references/configuration.md` (config file setup + IMAP/SMTP authentication)
- `references/message-composition.md` (MML syntax for composing emails)

## VM 安装与 QQ 邮箱配置（实测 2026-07-20，追加）

**安装**：用预编译二进制，release asset 名是 `himalaya.x86_64-linux.tgz`（不是 `.tar.gz`/musl）。
```bash
VER=v1.2.0; cd /tmp
curl -sL "https://github.com/pimalaya/himalaya/releases/download/${VER}/himalaya.x86_64-linux.tgz" -o himalaya.tgz
tar xzf himalaya.tgz && mkdir -p ~/.local/bin && mv himalaya ~/.local/bin/ && chmod +x ~/.local/bin/himalaya
export PATH="$HOME/.local/bin:$PATH"; himalaya --version
```
（`cargo install` 太慢；brew 是 Mac 的，VM 不可用。）

**配置** `~/.config/himalaya/config.toml`：QQ 邮箱 IMAP `imap.qq.com:993`(tls) / SMTP `smtp.qq.com:465`(tls)。**密码用授权码不是登录密码**——从 password-manager 查 `QQ 账号1` 条目的 `邮箱授权码:` 字段，填入 `backend.auth.cmd = "echo <授权码>"`。

**验证**：`himalaya folder list` 列文件夹 + `himalaya envelope list --page-size 5` 读收件箱。IMAP 读取已验证通；SMTP 发送待首次实测。

**注意**：`envelope list` 偶发 `WARN imap_codec::response: Rectified missing text` 无害。本 skill 与 `qq-email` skill 功能重叠（都能收发 QQ 邮件），himalaya 更通用（多账户/IMAP/SMTP/MML）。

**工作流**：配邮箱前先查 password-manager 拿授权码，不要问用户要凭证。

## Prerequisites

1. Himalaya CLI installed (`himalaya --version` to verify)
2. A configuration file at `~/.config/himalaya/config.toml`
3. IMAP/SMTP credentials configured (password stored securely)

## Configuration Setup

Run the interactive wizard to set up an account:
```bash
himalaya account configure
```

Or create `~/.config/himalaya/config.toml` manually:
```toml
[accounts.personal]
email = "you@example.com"
display-name = "Your Name"
default = true

backend.type = "imap"
backend.host = "imap.example.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@example.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show email/imap"  # or use keyring

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.example.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show email/smtp"
```

## Common Operations

### List Folders

```bash
himalaya folder list
```

### List Emails

List emails in INBOX (default):
```bash
himalaya envelope list
```

List emails in a specific folder:
```bash
himalaya envelope list --folder "Sent"
```

List with pagination:
```bash
himalaya envelope list --page 1 --page-size 20
```

### Search Emails

```bash
himalaya envelope list from john@example.com subject meeting
```

### Read an Email

Read email by ID (shows plain text):
```bash
himalaya message read 42
```

Export raw MIME:
```bash
himalaya message export 42 --full
```

### Reply to an Email

Interactive reply (opens $EDITOR):
```bash
himalaya message reply 42
```

Reply-all:
```bash
himalaya message reply 42 --all
```

### Forward an Email

```bash
himalaya message forward 42
```

### Write a New Email

Interactive compose (opens $EDITOR):
```bash
himalaya message write
```

Send directly using template:
```bash
cat << 'EOF' | himalaya template send
From: you@example.com
To: recipient@example.com
Subject: Test Message

Hello from Himalaya!
EOF
```

Or with headers flag:
```bash
himalaya message write -H "To:recipient@example.com" -H "Subject:Test" "Message body here"
```

### Move/Copy Emails

Move to folder:
```bash
himalaya message move 42 "Archive"
```

Copy to folder:
```bash
himalaya message copy 42 "Important"
```

### Delete an Email

```bash
himalaya message delete 42
```

### Manage Flags

Add flag:
```bash
himalaya flag add 42 --flag seen
```

Remove flag:
```bash
himalaya flag remove 42 --flag seen
```

## Multiple Accounts

List accounts:
```bash
himalaya account list
```

Use a specific account:
```bash
himalaya --account work envelope list
```

## Attachments

Save attachments from a message:
```bash
himalaya attachment download 42
```

Save to specific directory:
```bash
himalaya attachment download 42 --dir ~/Downloads
```

## Output Formats

Most commands support `--output` for structured output:
```bash
himalaya envelope list --output json
himalaya envelope list --output plain
```

## Debugging

Enable debug logging:
```bash
RUST_LOG=debug himalaya envelope list
```

Full trace with backtrace:
```bash
RUST_LOG=trace RUST_BACKTRACE=1 himalaya envelope list
```

## Tips

- Use `himalaya --help` or `himalaya <command> --help` for detailed usage.
- Message IDs are relative to the current folder; re-list after folder changes.
- For composing rich emails with attachments, use MML syntax (see `references/message-composition.md`).
- Store passwords securely using `pass`, system keyring, or a command that outputs the password.
