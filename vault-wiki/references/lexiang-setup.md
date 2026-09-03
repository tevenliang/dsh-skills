# 乐享知识库 MCP 配置说明

> 本文档说明如何配置乐享（Lexiang）MCP，让 vault-wiki 的 Step 5 上传环节可用。

---

## 什么是乐享

乐享（lexiangla.com）是腾讯的企业知识管理平台，支持 Markdown 导入、可访问的 web URL、多用户协作。每个上传的文档都会获得一个 `https://lexiangla.com/pages/{entry_id}` 形式的稳定 URL（需要公司 SSO 登录访问）。

---

## 配置方式

### 方式 1：使用已归档 skill 中的 mcp.json

如果你之前在 `~/.agents/skills/archive/lexiang-mcp-skill/` 装过该 skill，那里已有可用的 mcp.json：

```bash
cat ~/.agents/skills/archive/lexiang-mcp-skill/mcp.json
```

应该看到：
```json
{
  "mcpServers": {
    "lexiang": {
      "enabled": true,
      "url": "https://mcp.lexiang-app.com/mcp?company_from=<YOUR_COMPANY_FROM>",
      "transportType": "streamable-http",
      "headers": {
        "Authorization": "Bearer lxmcp_<YOUR_TOKEN>"
      }
    }
  }
}
```

### 方式 2：从乐享获取新 token

1. 打开 https://lexiangla.com/mcp
2. 登录你的企业账号
3. 复制 `COMPANY_FROM` 和 `LEXIANG_TOKEN`（格式 `lxmcp_xxx`）
4. 写入你客户端的 mcp.json：
   - **mcporter（通用）**: `~/.mcporter/mcporter.json`
   - **DSH/WorkBuddy**: 当前 dsh 配置目录

### 方式 3：通过 dsh 的 MCP 注册

如果你用 dsh，可以注册 MCP server：

```bash
# 编辑 mcp.json
cat > ~/.dsh/mcp.json <<EOF
{
  "mcpServers": {
    "lexiang": {
      "url": "https://mcp.lexiang-app.com/mcp?company_from=YOUR_COMPANY_FROM",
      "transportType": "streamable-http",
      "headers": {
        "Authorization": "Bearer YOUR_LEXIANG_TOKEN"
      }
    }
  }
}
EOF
```

---

## 验证连接

配置后调用 `whoami()` 测试：

```bash
curl -s -X POST "https://mcp.lexiang-app.com/mcp?company_from=YOUR_COMPANY_FROM" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

成功响应会返回 `serverInfo: {"name": "Lexiang-AI-Knowledge"}` 和 `instructions` 字段。

---

## Token 生命周期

| 阶段 | 表现 | 处理 |
|:--|:--|:--|
| 正常 | 调用成功 | 直接用 |
| 即将过期 | 返回正常但带预警信息 | 提醒用户续期，URL： `https://lexiangla.com/mcp?company_from=xxx` |
| 已过期 | 401 响应 | 不要重试，引导用户续期 |

**续期流程**：打开 `https://lexiangla.com/mcp?company_from=YOUR_COMPANY_FROM` → 点"续期"按钮 → 同一 token 恢复，无需重新配置。

---

## 上传流程（核心）

### 1. 身份与空间

```python
# whoami() 返回:
# - company.company_domain: 如 "https://lexiangla.com"
# - company.code: 如 "764076a061d311f1b78a4652da89b347"
# - personal_space.id: 个人知识库 ID
# - personal_space.root_entry_id: 根节点 ID
```

### 2. URL 拼接规则

| 域名类型 | 链接格式 | 示例 |
|:--|:--|:--|
| 顶级域名（如 `lexiangla.com`） | `{domain}/pages/{entry_id}?company_from={code}` | `https://lexiangla.com/pages/abc?company_from=csig` |
| 三级域名（如 `csig.lexiangla.com`） | `{domain}/pages/{entry_id}` | `https://csig.lexiangla.com/pages/abc` |

### 3. 上传操作

**创建文件夹**（首次上传某个 L1 时）：
```python
entry_create_entry(
  space_id="<personal_space_id>",
  parent_entry_id="<root_entry_id>",
  entry_type="folder",
  name="21_ai"  # L1 目录名
)
# → 返回 folder_id
```

**上传 wiki 内容**：
```python
entry_import_content(
  space_id="<space_id>",
  parent_id="<folder_id>",
  name="AI-Agent知识库（蒸馏版）.md",
  content_type="markdown",
  content="<wiki 文件完整内容>"
)
# → 返回 entry_id
```

**生成 URL**：
```
https://lexiangla.com/pages/{entry_id}?company_from={company_code}
```

---

## 已知问题

### 1. WAF 拦截

腾讯云 WAF 对部分内容敏感（特定字符/格式组合），会上传失败并返回 HTML 拦截页而非 JSON。

**处理**：
- 标记为 `⚠️ 需手动上传`
- 重试无效（WAF 持续拦截）
- 让用户手动从乐享网页端上传

### 2. 内容过大

`entry_import_content` 实际有长度限制（具体值需以 `get_tool_schema` 返回为准）。超大文件需先拆分。

### 3. 并发限制

不要并发 >5，否则会被 WAF/rate limit。建议 3 并行 + 0.6s 间隔。

---

## 相关资源

- 乐享平台: https://lexiangla.com
- MCP 配置入口: https://lexiangla.com/mcp
- 归档 skill: `~/.agents/skills/archive/lexiang-mcp-skill/`
- MCP 协议: https://modelcontextprotocol.io
