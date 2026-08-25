# 常见问题排查

## 1. 滑块验证码

**症状**:`xhs read` 第一次 OK,第二次返回空/报错/弹验证码

**解决**:
- 单次手动 OK,不要紧
- 批量触发后:**等 5-10 分钟**再试
- 换 IP / 重新连 VPN
- `--sleep` 加大到 8-10s
- 减少 `--limit`

**原理**:小红书对同一 IP 短时间多次 read 会触发风控。

## 2. `xhs search` 没结果

**症状**:搜中文返回空,但用浏览器搜有结果

**原因**:可能是 IP 被识别为非中国大陆,xhs CLI 默认走国内 API,海外 IP 走不同接口。

**解决**:
- 关 VPN / 切回国内 IP
- 确认 Chrome 在国内能正常访问 xiaohongshu.com
- 检查 `xhs status` 是否正常

## 3. JSON 解析报错

**症状**:`json.decoder.JSONDecodeError`

**原因**:`xhs --json` 输出偶尔有 WARNING 行混在前面

**解决**:本 skill 已自动处理(找第一个 `{` 开始解析)。如果还报错:
```bash
# 直接看原始输出
xhs search "kw" --json 2>&1 | head -5
# 是否有警告/日志混在前面?
```

## 4. 图片下载失败

**症状**:`(下载失败: ...)` 出现在 markdown 里

**原因**:
- URL 过期(小红书图片 CDN 有时效)
- xhs CDN 防盗链(已用 UA + Referer 伪装,通常够用)
- 网络问题

**解决**:
- 重新调一次(URL 可能更新)
- 检查 `~/Documents/agent_spaces/output/xhs_images/` 是否写权限
- 看 stderr 找具体错误

## 5. 登录态失效

**症状**:`xhs status` 返回未登录,或 API 返回 401

**解决**:
```bash
# Chrome 中重新登录 xiaohongshu.com
xhs logout
xhs login --cookie-source chrome
xhs status  # 验证
```

## 6. 图片本地缓存太大

**症状**:`xhs_images/` 文件夹占空间

**清理**:
```bash
# 一次性清空
/usr/bin/trash ~/Documents/agent_spaces/output/xhs_images/*.webp

# 或按时间清理 7 天前的
find ~/Documents/agent_spaces/output/xhs_images/ -name "*.webp" -mtime +7 -delete
```

## 7. `--render` 模式下 Codex 仍不显示图

**可能原因**:
- Codex 的图片渲染对 `.webp` 支持不完善
- 路径权限问题

**解决**:
- 改用 `--render` 后输出格式为绝对路径(本 skill 默认如此)
- 如果 .webp 不显示,可以把图转 jpg:
  ```bash
  for f in ~/Documents/agent_spaces/output/xhs_images/*.webp; do
      sips -s format jpeg "$f" --out "${f%.webp}.jpg" 2>/dev/null
  done
  ```

## 8. 搜索结果少/排序奇怪

**原因**:小红书搜索结果**会因账号/IP/时间漂移**。

**解决**:
- 用 `--sort popular` / `--sort latest` 多试
- `--page 2 3 4` 翻页
- 换关键词(同义词、近义词)

## 9. 报错:`xhs CLI not installed`

**解决**:
```bash
# macOS + uv
uv tool install xiaohongshu-cli

# 验证
xhs --version

# 加 PATH(如果找不到)
export PATH="$HOME/.local/bin:$PATH"
```

## 10. 风控后还是不行?

**最后手段**:
1. 退出 Chrome 登录,重新登录
2. 换 IP(VPN 切节点)
3. 等 30 分钟以上
4. 用 `xiaohongshu-skills`(浏览器方案)替代
