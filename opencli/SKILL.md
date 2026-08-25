---
search: false
name: opencli
description: opencli CLI 交互工具 — 复用 Chrome
  登录态浏览/搜索/抓取B站热门、知乎、微博热搜、Twitter、YouTube、雪球、BOSS直聘等平台，支持发帖、回复、点赞。优先于
  Playwright。触发词：查B站热门、搜知乎、看微博热搜、发推、搜YouTube、查股票行情
disable-model-invocation: true
---

# opencli

CLI tool that turns websites into CLI interfaces, reusing Chrome's login state. Zero credentials needed.

**Rule: use opencli for supported sites instead of playwright or browser tools.**

## Syntax

```bash
opencli <site> <command> [--option value] [-f json]
```

**Common flags (all commands):**
- `-f json` — machine-readable output (preferred for parsing)
- `--limit N` — number of results (default varies, usually 20)
- `-f table|json|yaml|md|csv`

## Quick Examples

```bash
# 读取/浏览
opencli bilibili hot --limit 10 -f json
opencli zhihu hot -f json
opencli weibo hot -f json
opencli twitter timeline -f json
opencli hackernews top --limit 20 -f json
opencli v2ex hot -f json
opencli reddit hot -f json
opencli xiaohongshu feed -f json

# 搜索
opencli bilibili search "AI" -f json
opencli zhihu search "大模型" -f json
opencli twitter search "claude AI" -f json
opencli youtube search "LLM tutorial" -f json
opencli boss search "AI工程师" --city "上海" -f json

# 互动（写操作）
opencli twitter post --text "Hello from CLI!"
opencli twitter reply --url "https://x.com/.../status/123" --text "Great post!"
opencli twitter like --url "https://x.com/.../status/123"

# 个人数据
opencli bilibili history -f json
opencli twitter bookmarks -f json
opencli xueqiu watchlist -f json
```

## Output Formatting Rules

When displaying results to the user:
1. **Always show original title + Chinese translation + clickable link as separate columns**
2. **Table format**: `# | 原标题 | 中文翻译 | 链接 | 关键指标...`
3. **原标题**: plain text, no markdown link — do NOT use `[title](url)` format
4. **中文翻译**: plain Chinese translation text
5. **链接**: `[🔗](url)` — compact clickable icon
6. **Translate all English titles** to Chinese — never show English-only output to the user

Example:
```
| # | 原标题 | 中文翻译 | 链接 | 分 | 评论 |
|---|--------|---------|------|-----|------|
| 1 | The 49MB web page | 那个 49MB 的网页 | [🔗](https://...) | 388 | 196 |
```

## Fallback 策略：opencli 不支持时用 Playwright

**核心原则：永远不说"不支持"，先尝试 opencli，失败或无命令时自动切换 Playwright。**

### 决策流程

```
用户请求
  ↓
opencli 有对应命令？
  ├─ 是 → 执行 opencli
  └─ 否 → 直接用 Playwright MCP 打开对应页面完成任务
              ↓
           Playwright 报错 / 无法连接？
              └─ 引导用户安装桥接插件（见下方）
```

### 常见 opencli 不支持场景 → Playwright 替代

| 场景 | 网址 | Playwright 操作 |
|------|------|----------------|
| 知乎私信 | `https://www.zhihu.com/messages` | navigate → snapshot 读取列表 |
| 知乎通知 | `https://www.zhihu.com/notifications` | navigate → snapshot |
| 微博发帖 | `https://weibo.com` | navigate → 点击输入框 → type → 发送 |
| 小红书私信 | `https://www.xiaohongshu.com/im` | navigate → snapshot |
| B站私信 | `https://message.bilibili.com` | navigate → snapshot |
| Twitter DM | `https://x.com/messages` | navigate → snapshot |

### Playwright 操作标准流程

```
1. mcp__playwright__browser_navigate → 目标 URL
2. mcp__playwright__browser_snapshot → 读取页面结构
3. 根据需要：browser_click / browser_type / browser_scroll
4. 将结果整理后呈现给用户
```

### ⚠️ 写操作风险提示（发帖/回复/点赞前必须告知）

1. **账号安全**：自动化行为可能触发平台风控
2. **不可撤回**：发布后立即公开
3. **最佳实践**：执行前向用户展示将发布的内容，等待确认

### 插件未安装时的引导话术

如果 Playwright 报错（连接失败 / 无法控制浏览器），告知用户：

> "需要在 Chrome 安装 **Playwright MCP Bridge** 插件才能控制浏览器。
> 安装步骤：
> 1. 打开 Chrome，访问 Chrome Web Store
> 2. 搜索 **"Playwright MCP"** 或 **"MCP Bridge"**
> 3. 点击「添加到 Chrome」
> 4. 安装后确保 Chrome 已登录目标网站
> 5. 重新告诉我你的需求，我来帮你完成"

## Requirements

- Chrome browser open with target site logged in
- OpenCLI extension installed in Chrome Profile 1 (`ildkmabpimmkaediidaifkhjpohdnifk`)

### Chrome Profile 1 窗口管理（铁律 — 单窗口，精准操控）

**红线**：
- ❌ 禁止 `osascript quit "Google Chrome"` — 会杀主 profile (Default/Liang)
- ❌ 禁止 `open -na` / `--new-window` — 抢焦点 + 叠窗口 (刷屏)
- ❌ 禁止复用用户手动开的窗口 — 那种窗口没有 `--silent-debugger-extension-api` 参数, 扩展挂调试器会弹"Chrome 正在被调试"横幅
- ✅ 窗口必须【由我打开】并带 `--silent-debugger-extension-api` 参数 (写在 open 命令后面)
- ✅ 用 `open -gj` 后台打开 (不抢焦点); **不带** `--new-window`
- ✅ 只开一个; 重试只重试连接检查, 绝不再开新窗口
- ✅ 按状态文件记录的窗口 ID 精准 `close window id <n>`, 不动用户主 profile

**为什么必须带 `--silent-debugger-extension-api`**：
OpenCLI 扩展用 `chrome.debugger` API 控制页面。若 Chrome 启动时没带此参数, 扩展一附加调试器, 页面顶部就显示"Chrome 正在被调试"横幅, 还可能拦截操作。此参数是**启动参数**, 只能写在 `open` 命令行里, 无法给已开的窗口事后补。所以工作窗口必须由我打开, 不能复用用户手动开的窗口。

**正确流程: 始终只需一个【我打开】的 Profile 1 窗口**：

```bash
OPENCLI="$HOME/.npm-global/bin/opencli"
XHS_WIN_STATE="/tmp/xhs_work_win_id"   # 记录我开的窗口 ID

# === 快照函数 ===
snapshot_win_ids() {
  osascript -e '
  tell application "Google Chrome"
    if (count of windows) is 0 then return ""
    set ids to {}
    repeat with w in windows
      set end of ids to (id of w as string)
    end repeat
    set AppleScripts text item delimiters to ","
    return ids as string
  end tell' 2>/dev/null
}

# === 1. 若之前已开过且还活着, 直接复用 (看状态文件) ===
SAVED=""
[ -f "$XHS_WIN_STATE" ] && SAVED=$(cat "$XHS_WIN_STATE")
if [ -n "$SAVED" ] && osascript -e "tell app \"Google Chrome\" to return exists window id $SAVED" 2>/dev/null | grep -q true; then
  NEW_ID="$SAVED"
else
  # === 2. 新开一个: open -gj 后台(不抢焦点) + 带调试静默参数 (不传 URL, 避免多开空白窗) ===
  BEFORE=$(snapshot_win_ids)
  open -gj -a "Google Chrome" --args --profile-directory="Profile 1" --silent-debugger-extension-api
  sleep 5
  AFTER=$(snapshot_win_ids)
  NEW_ID=$(python3 -c "
before='$BEFORE'.split(',') if '$BEFORE' else []
after='$AFTER'.split(',')
diff=[x for x in after if x not in before]
print(diff[0] if diff else '')
")
  # 兜底: -gj 因 Chrome 在前台未建窗时, 用 osascript 直接建 (仍属 Profile 1)
  [ -z "$NEW_ID" ] && NEW_ID=$(osascript -l JavaScript -e 'var c=Application("Google Chrome"); var w=c.Window().make(); w.tabs[0].url="data:text/html,<title>opencli-worker</title>"; w.id();' 2>/dev/null)
  echo "$NEW_ID" > "$XHS_WIN_STATE"
fi
echo "工作窗口 ID: $NEW_ID"

# === 3. 导航到目标站 (供登录/抓取) ===
osascript -e "tell app \"Google Chrome\" to set URL of tab 1 of window id $NEW_ID to \"https://www.xiaohongshu.com\"" 2>/dev/null

# === 4. 等扩展连接 (重试检查, 不开新窗口) ===
for i in $(seq 1 5); do
  $OPENCLI doctor 2>&1 | grep -q "Extension.*OK" && echo "✅ 扩展已连接" && break
  sleep 3
done

# === 5. 用完关窗 (精准关闭, 不动主 profile) ===
osascript -e "tell application \"Google Chrome\" to close window id $NEW_ID" 2>/dev/null
rm -f "$XHS_WIN_STATE"
```

**常见误区纠正**：
- `open -gj` 本身能用 (创建窗口 + 激活 MV3 Service Worker), 实测有效。失败只在两种情形: ① 带了 `--new-window` (与 `-gj` 冲突不建窗); ② Chrome 已是前台 App 时 `-gj` 不新建。兜底用 osascript `Window().make()` 解决。
- `open -na` 会抢焦点 + `--new-window` 叠窗 → 刷屏, 禁用。
- `osascript quit` 关所有 Chrome → 杀主 profile, 禁用。
- 复用用户手动开的窗口 → 没有 `--silent-debugger-extension-api` → 调试横幅, 禁用。

**Profile 对应关系**：
- **Default = "Liang"** (`teven.liang@gmail.com`) — 用户主 profile，**禁止操作**
- **Profile 1 = "yizhini"** (`yizhini@gmail.com`) — 副 profile，装有 OpenCLI 扩展 v1.0.22
- **Profile 2 = "您的 Chrome"** — 另一个副 profile
- daemon 默认 profile: `dy2s6y2k`, 端口 `19825`
- 扩展 ID: `ildkmabpimmkaediidaifkhjpohdnifk`
- **opencli 二进制必须用 npm 全局版** (`~/.npm-global/bin/opencli`, v1.8.6)，确保 daemon/CLI/扩展版本匹配

### subscription-crawl 管线集成

`crawl_all.sh v5` 已集成上述窗口管理，XHS 抓取自动执行:
1. snapshot 现有窗口 → 打开 Profile 1 单窗口 → 等扩展连接 → 抓取 → 关闭窗口 → 上传飞书
2. 主 profile 窗口全程不受影响
3. 超时 15s 未连上 → 跳过 XHS（不阻塞其他平台）

## 自迭代能力：为新网站创建 CLI

**当 opencli 不支持某个网站时，不要放弃——自己创建！**

### 流程

```
1. opencli <site> --help  →  报错？说明不支持
2. opencli generate <url>  →  尝试自动生成（成功则结束）
3. 自动生成失败 → 手动创建 YAML：
   a. 用 Playwright 打开目标页面
   b. browser_evaluate 探索 DOM 结构（找 data-test 属性、class 规律）
   c. 确认选择器后写入 ~/.opencli/clis/<site>/top.yaml
   d. opencli <site> top -f json  →  验证输出
```

### YAML 格式（DOM 抓取模板）

```yaml
site: <sitename>
name: <command>
description: <描述>
domain: <domain>
strategy: public
browser: true

args:
  limit:
    type: int
    default: 10

pipeline:
  - navigate: https://<url>
  - evaluate: |
      (async () => {
        const limit = ${{ args.limit }};
        // DOM 抓取逻辑
        return results;
      })()

columns: [rank, name, ...]
```

### 已创建的自定义 CLI

| 站点 | 命令 | 文件 | 关键选择器 |
|------|------|------|-----------|
| producthunt | `top` | `~/.opencli/clis/producthunt/top.yaml` | `button[data-test="vote-button"]` → 父容器 → `[data-test^="post-name-"]`，tagline: `nameEl.parentElement.querySelector('span.mt-0\\.5')` |

### 调试技巧

- `browser_evaluate` 先探结构：`document.querySelector('...').innerHTML`
- 找 `data-test` 属性最稳定，其次 class 中的语义词
- tagline 通常是 name 的兄弟元素（`nameEl.parentElement.querySelector('span...')`）
- 去重用 `seen = new Set()`，防止重复产品

## Full Command Reference

See [references/commands.md](references/commands.md) for all 55 commands with complete argument details.
