# 常用命令速查

## 搜索类

```bash
# 基础搜索(综合排序,前 10 条)
xhs_search.py search "咖啡"

# 热门排序
xhs_search.py search "咖啡" --sort popular

# 最新排序
xhs_search.py search "咖啡" --sort latest

# 翻页
xhs_search.py search "咖啡" --page 2

# 限制数量
xhs_search.py search "咖啡" --limit 3

# 下载封面图
xhs_search.py search "咖啡" --limit 3 --render

# 自定义输出目录
xhs_search.py search "咖啡" --render --out-dir /tmp/my_images
```

## 详情类

```bash
# 单条详情(只拿元数据)
xhs_search.py detail <note_id> --xsec-token <token>

# 单条详情 + 下载图片(默认 9 张)
xhs_search.py detail <note_id> --xsec-token <token> --render

# 单条详情 + 只展示前 3 张图
xhs_search.py detail <note_id> --xsec-token <token> --render --max-images 3
```

## 一条龙(auto)

```bash
# 搜索 + 取前 3 条详情 + 全部带图
xhs_search.py auto "咖啡" --limit 3

# 控制每条详情图片数
xhs_search.py auto "咖啡" --limit 3 --max-images 4

# 跳过内容,只拿搜索列表
xhs_search.py auto "咖啡" --limit 10 --no-content

# 跳过图片下载
xhs_search.py auto "咖啡" --limit 3 --no-render

# 防风控加间隔
xhs_search.py auto "咖啡" --limit 3 --sleep 5
```

## 维护类

```bash
# 安装体检
bash ~/.agents/skills/xhs-cli/scripts/check_setup.sh

# 清理图片缓存
rm ~/Documents/agent_spaces/output/xhs_images/*.webp

# 看 xhs CLI 版本
xhs --version

# 看登录状态
xhs status
```

## 跟 Codex 对话示例

```
你: 小红书搜"咖啡拿铁"前 5 条热门

Codex: 调 xhs_search.py search "咖啡拿铁" --limit 5 --sort popular
       输出 markdown 表格

你: 第 3 条展开看看

Codex: 调 xhs_search.py detail <note_id> --xsec-token <token> --render

你: "咖啡拿铁"和"美式咖啡"对比下哪个更火

Codex: 并行调 2 次 search,合并表格对比
```

## 高级:管道组合

```bash
# 把搜索结果保存为 JSON,后续处理
xhs_search.py search "咖啡" --limit 20 > /tmp/coffee_search.txt

# 提取所有 note_id 给后续 batch 处理
xhs_search.py search "咖啡" --limit 5 | grep 'note_id' | awk -F'`' '{print $2}' > note_ids.txt
```
