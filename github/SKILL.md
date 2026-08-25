---
name: github
description: GitHub CLI — 仓库/Issue/PR 搜索与查看。基于 gh CLI，已登录账号
  tevenliang。触发词：「搜仓库」「搜 GitHub」「找项目」「GitHub Issue」
version: 1
author: Steven Liang
platforms:
  - macos
  - linux
disable-model-invocation: true
---

# GitHub CLI

基于 `gh` 官方 CLI，本地已安装 v2.95.0，已登录 github.com（账号 tevenliang）。

## 前置条件

```bash
which gh && gh --version  # 验证可用
gh auth status            # 验证登录
```

## 常用命令

### 搜仓库
```bash
gh search repos "关键词" --sort stars --limit 10
gh search repos "openai codex" --sort stars --limit 5
```

### Issue
```bash
# 列出一个仓库的 open issues
gh issue list -R owner/repo --state open --limit 10

# 查看指定 Issue
gh issue view 123 -R owner/repo

# 搜索所有仓库的 issues
gh issue search "关键词" --repo owner/repo --state open
```

### PR
```bash
gh pr list -R owner/repo --state open --limit 10
gh pr view 123 -R owner/repo
```

### 仓库信息
```bash
gh repo view owner/repo
gh repo view owner/repo --json name,description,stars,language
```

## 注意事项

- `gh` 的 `--repo` 参数格式是 `owner/repo`
- 搜索结果默认按相关性排序，加 `--sort stars` 按星标数排序
- `gh issue search` 支持跨仓库搜索，用 `--repo owner/repo` 限定单仓库
