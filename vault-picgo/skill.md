# vault-picgo

将 Obsidian vault 中的本地图片迁移到在线图床（GitHub/PicGo Cloud），并自动替换 md 文件中的引用。

## 核心概念

| 概念 | 说明 |
|------|------|
| **Obsidian wikilink** | `![[media/xxx.jpg]]` 本地引用格式 |
| **Markdown image** | `![](https://...)` 在线引用格式 |
| **PicGo** | 图床上传工具，支持多种图床 |
| **GitHub 图床** | 存储在 GitHub 仓库，无限容量 |

## 图床配置

### 当前配置（2026-08-31）

- **图床**：GitHub
- **仓库**：`tevenliang/picgo-images`
- **目录**：`images/`
- **Token**：已配置在 `~/.picgo/config.json`

### 查看当前配置

```bash
cat ~/.picgo/config.json
```

### 切换图床

```bash
# 切换到 picgo-cloud
picgo use uploader picgo-cloud

# 切换到 github
picgo use uploader github
```

## 迁移流程

### 1. 查找需要迁移的文件

```bash
cd /Users/tianwenliang/Documents/steven_vault
grep -r "!\[\[" 00_inbox --include="*.md" -l 2>/dev/null | grep -v ".trash"
```

### 2. 统计 wikilink 数量

```bash
grep -r "!\[\[" 00_inbox --include="*.md" 2>/dev/null | wc -l
```

### 3. 提取唯一图片路径

```bash
perl -ne 'while(/\[\[media\/([^\]]+)\]\]/g){print "media/$1\n"}' 文件.md | sort -u
```

### 4. 单个图片上传与替换

```bash
# 上传
URL=$(picgo upload "media/xxx.jpg" 2>&1 | grep "https://" | tr -d ' \n')

# 替换（perl）
perl -i -pe "s|!\[\[media/xxx.jpg\]\]|![]($URL)|g" 文件.md
```

### 5. 批量迁移脚本

```bash
cd /Users/tianwenliang/Documents/steven_vault

find 00_inbox -name "*.md" -type f ! -path "*/.trash/*" | while read MD_FILE; do
  MEDIA_LIST=$(perl -ne "while(/\[\[media\/([^\]]+)\]\]/g){print \"media/\$1\n\"}" "$MD_FILE" 2>/dev/null | sort -u)
  
  for MEDIA_PATH in $MEDIA_LIST; do
    FULL_PATH="/Users/tianwenliang/Documents/steven_vault/$MEDIA_PATH"
    
    if [ -f "$FULL_PATH" ]; then
      RESULT=$(picgo upload "$FULL_PATH" 2>&1)
      
      if echo "$RESULT" | grep -q "SUCCESS"; then
        URL=$(echo "$RESULT" | grep "https://" | tr -d " \n")
        perl -i -pe "s|!\[\[$MEDIA_PATH\]\]|![]($URL)|g" "$MD_FILE"
        echo "OK: $MEDIA_PATH"
      else
        echo "FAIL: $MEDIA_PATH"
      fi
    fi
  done
done
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `picgo upload <path>` | 上传单个文件 |
| `picgo upload <p1> <p2>` | 上传多个文件 |
| `picgo use uploader <name>` | 切换图床 |
| `picgo status` | 查看状态 |
| `picgo login` | 登录 PicGo Cloud |

## GitHub Token 获取

1. 访问 https://github.com/settings/tokens
2. Generate new token (classic)
3. 需要的权限：`repo` (Full repository access)
4. Token 存于 Keychain：安全查找 `security find-internet-password -s github.com -a <username> -w`

## 注意事项

1. **Wikilink 格式**：`![[media/path]]` 需要完整匹配，包括 `media/` 前缀
2. **路径编码**：中文路径需要正确处理
3. **重复上传**：相同文件名会覆盖，适合重命名后重新上传
4. **网络超时**：大量上传时注意网络稳定性
5. **GitHub 仓库**：公共仓库图片可通过 `raw.githubusercontent.com` 访问

## 相关文件

- 仓库地址：https://github.com/tevenliang/picgo-images
- PicGo 配置：`~/.picgo/config.json`
- 迁移日志：`/tmp/migration_log*.txt`
