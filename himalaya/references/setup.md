# Himalaya 邮件 CLI 在 Linux/VM 的安装与用法

## 安装（x86_64 Linux）
下载预编译二进制（非 brew/cargo，VM 无 brew）：
```bash
VER=v1.2.0
curl -sL "https://github.com/pimalaya/himalaya/releases/download/${VER}/himalaya.x86_64-linux.tgz" -o himalaya.tgz
tar xzf himalaya.tgz
mkdir -p ~/.local/bin && mv himalaya ~/.local/bin/ && chmod +x ~/.local/bin/himalaya
export PATH="$HOME/.local/bin:$PATH"
himalaya --version
```
注意 asset 名是 `himalaya.x86_64-linux.tgz`（不是 `.tar.gz`、不是 `.musl.tar.gz`）。

## 配置（QQ 邮箱）
`~/.config/himalaya/config.toml`：
```toml
[accounts.qq]
email = "15446340@qq.com"
display-name = "Steven Liang"
default = true
backend.type = "imap"
backend.host = "imap.qq.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "15446340@qq.com"
backend.auth.type = "password"
backend.auth.cmd = "echo <授权码>"   # 从 password-manager 查 15446340@qq.com 的邮箱授权码
message.send.backend.type = "smtp"
message.send.backend.host = "smtp.qq.com"
message.send.backend.port = 465
message.send.backend.encryption.type = "tls"
message.send.backend.login = "15446340@qq.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "echo <授权码>"
```

## 常用命令
- 列文件夹：`himalaya folder list`
- 列收件箱：`himalaya envelope list --page-size 10`
- 读邮件：`himalaya message read <ID>`
- **标记已读（v1.2.0 语法）**：`himalaya flag add <ID> seen`（注意：不是 `--flag seen`，否则报 unexpected argument）

## 查未读脚本
`~/.hermes/scripts/check_new_mail.sh`：列收件箱未读邮件，依赖邮箱自身 seen 状态去重（不在本地维护状态文件）。cron 每小时(10-23点)调用，有新未读才汇报；用户回"已读"后由 agent 手动 `flag add <ID> seen`。
