# vault-wiki TODO

## 改进方向

### 1. 生成质量提升
- 参考 ima 的 wiki 格式，优化 LLM 生成 prompt
- 改进 wiki 页面的视觉结构和内容组织
- 目标：生成和 ima 同等质量的 wiki 页面

### 2. 来源
- 用户会发送 ima 做的 wiki 示例
- 分析其格式、结构、内容组织方式
- 整合到 skill 的 prompt 和模板中

## 参考项目（已调研）
- AgriciDaniel/claude-obsidian (wiki-ingest skill) — 基于 Karpathy LLM Wiki 模式
- M31-Labs/hyphae — federated knowledge graph for agents
- pburney/Markdown-Graph-MCP — MCP server for Logseq

## NotebookLM POC 结果
- ❌ 直接上传 md 文件：文件太大，全部 error
- ❌ Drive URL 添加源：Google bot 检测，读取到 captcha 页面
- 结论：NotebookLM 方案不可行

## 下一步
等待用户提供 ima wiki 示例
