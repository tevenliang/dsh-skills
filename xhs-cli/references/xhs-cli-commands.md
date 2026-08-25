# xhs CLI 全部子命令参考

`xiaohongshu-cli` v0.6.4 的完整命令清单,从 `xhs --help` 抓取。

## 信息类(只读)

| 命令 | 说明 | 输出 |
|---|---|---|
| `whoami` | 当前账号详情(level, fans, ...) | 用户信息 |
| `status` | 登录状态 + 基本信息 | ok + 昵称 |
| `user <id_or_url>` | 查看用户资料 | 用户信息 |
| `user-posts <user>` | 某博主的所有帖子 | note list (crawl 在用) |
| `feed` | 推荐流 | note list |
| `hot` | 热门分类浏览 | 分类列表 |
| `topics <keyword>` | 搜话题/标签 | topic list |
| `my-notes` | 我发过的笔记 | note list |
| `favorites` | 我收藏的笔记 | note list |
| `notifications` | 评论/点赞通知 | notification list |
| `unread` | 未读通知数量 | count |

## 搜索类

| 命令 | 说明 | crawl 在用 |
|---|---|---|
| **`search <keyword>`** | 按关键字搜索笔记 | ❌ 未用 |
| `search-user <keyword>` | 按关键字搜用户 | ❌ |
| `read <id_or_url>` | 读单条笔记正文+图片 | ❌(改用 xhs-downloader) |

search 子命令参数:
- `--sort`: general / popular / latest
- `--type`: all / video / image
- `--page`: 翻页
- `--json` / `--yaml`: 输出格式

read 子命令参数:
- `--xsec-token`: 安全 token(从 search 拿)
- `--json` / `--yaml`

## 互动类(写操作)

| 命令 | 说明 |
|---|---|
| `like / unlike` | 点赞 / 取消点赞 |
| `favorite / unfavorite` | 收藏 / 取消收藏 |
| `follow / unfollow` | 关注 / 取消关注 |
| `comment <id> --content "..."` | 发表评论 |
| `comments <id>` | 看评论 |
| `reply <comment_id> --content "..."` | 回复评论 |
| `sub-comments <comment_id>` | 看子评论 |
| `delete-comment <id>` | 删除评论 |

## 发布类

| 命令 | 说明 |
|---|---|
| `post` | 发布图文笔记 |
| `delete` | 删除笔记 |

## 登录类

| 命令 | 说明 |
|---|---|
| `login` | 登录(`--cookie-source chrome`) |
| `logout` | 退出登录(清 cookie) |

## 输出格式

所有数据类命令都支持 `--json` 和 `--yaml`。**本 skill 强制用 `--json`**。

## crawl skill 用了哪些?

- ✅ `user-posts`(列表阶段)
- ❌ 其他 23 个命令 crawl 都没用

本 skill 重点包装:
- ✅ `search`(on-demand 搜索)
- ✅ `read`(on-demand 详情)
- ✅ `status` / `whoami`(体检)
