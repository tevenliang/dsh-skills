# 示例 01: 关键字搜索(简单模式)

## 命令

```bash
python3 ~/.agents/skills/xhs-cli/scripts/xhs_search.py search "咖啡拿铁" \
    --limit 5 --sort popular
```

## 实际输出

```markdown
## 🔍 搜索结果(共 5 条)

| # | 标题 | 作者 | 👍 | ⭐ | 💬 |
|---|---|---|---|---|---|
| 1 | 燕麦拿铁第一好喝 | 小黄超自律 | 37,561 | 16,541 | 574 |
| 2 | 當你《天天》生椰拿鐵 | 陶喆 | 36,632 | 3,128 | 3,218 |
| 3 | 早起看球只睡四小时的我be like： | 巧克力枪枪 | 35,175 | 1,739 | 34 |
| 4 | - | 王哈哈 | 34,706 | 21,382 | 421 |
| 5 | 教你拉雪里 | 阿朱咖啡 | 31,822 | 1,518 | 2,589 |
```

## 关键点

- **不加 `--render`**:只输出表格,不下载图片(快)
- **加 `--render`**:会下载封面图到 `~/Documents/agent_spaces/output/xhs_images/`
- `--sort popular`:综合最热排序,适合找热门
- `--sort latest`:按发布时间,适合找新内容
- `--sort general`:默认综合排序

## 跟 Codex 配合

```
用户: 小红书搜"咖啡拿铁"
Codex: 调 xhs_search.py search,把输出直接显示在 chat
```
