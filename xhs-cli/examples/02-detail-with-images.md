# 示例 02: 读单条详情(带图)

## 场景

知道 note_id 和 xsec_token(从 search 结果拿到),想看完整正文+图片。

## 命令

```bash
python3 ~/.agents/skills/xhs-cli/scripts/xhs_search.py detail <note_id> \
    --xsec-token "<token>" \
    --render --max-images 3
```

## 实际输出

```markdown
## 📖 Codex 首月免费订阅方案（2026 年 3 月最新

- **作者:** 村长不开车
- **发布时间:** 2026-03-23
- **互动:** 240 赞 / 280 收 / 40 评 / 55 分享
- **note_id:** `69c13d8100000000210127cb`

**🏷️ 话题:** #个人开发者 #软件分享 #openclaw #openclaw飞书 ...

### 📝 正文

最省钱： ChatGPT Free/Go（限时免费 + 2x 速率）
最划算： ChatGPT Plus 首月试用（$20/月，首月免费）
最灵活： API 按量付费（无订阅，按需使用）
推荐你先试 Free/Go 计划，不够用再升级 Plus 首月试用。

### 🖼️ 图片(共 8 张)

![xhs-1](/Users/tianwenliang/.agents/skills/xhs-cli/.../d59530f728970a44_xxx.webp)
![xhs-2](/Users/tianwenliang/.agents/skills/xhs-cli/.../c4c93b95f44ad755_xxx.webp)
![xhs-3](/Users/tianwenliang/.agents/skills/xhs-cli/.../5a55b1441f2481e2_xxx.webp)

_… 还有 5 张未展示,本地缓存路径: `~/Documents/agent_spaces/output/xhs_images/`_
```

## 关键点

- **必须传 `--xsec-token`**:每个 note 有自己的 token,从 search 结果拿
- **`--render`**:下载图片到本地,**这是 Codex 能显示图片的关键**(远程 URL 不渲染)
- **`--max-images N`**:控制展示数量,剩余图片本地缓存(可手动打开)
- 图片 SHA256 命名,同一张图不重复下载

## 怎么拿 note_id 和 token

从 search 输出里直接复制:
```json
{
  "id": "69c13d8100000000210127cb",
  "xsec_token": "ABrGFeEzcpnmVJtaVqPo7xcM_G5rIy_uE4t-j74OytbD0="
}
```
