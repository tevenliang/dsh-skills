# patches/client.js.changes.md — client.js 三处改动

`client.js` 是浏览器端 bundle（单行压缩 JS），三处改动全部是**字符串注入**，
用 `./apply.sh` 的 python 正则实现（UTF-8 安全），可手工核对以下内容。

## Patch3 — 硬编码 kind 列表 `bt=[...]`

minimax 不在下拉「选择类型」里，是因为 client.js 有一个**硬编码**的
adapter kind 数组（`bt` 变量），升级后没有包含 minimax。

```
原始: bt=["opencode-go","zai-coding-cn","openrouter","kimi","siliconflow",
         "deepseek","stepfun","stepfun-step-plan","xiaomi-token-plan-cn","cliproxy"];
改后: bt=[...,"cliproxy","minimax"];
```

> ⚠️ 这个数组是升级最容易破坏的地方：新增了其他原生 provider 时，
> 锚点 `bt=[...]` 内容会变。apply.sh 用正则 `bt=\[[^\]]*\]` 找数组并在
> 末尾追加，只要数组里还没有 `"minimax"` 就插入。

## Patch4 — 中文翻译

在中文翻译对象（`e={...}`，含 `quota.kind.xiaomi-token-plan-cn":"小米 MiMo Token Plan"`）
的同一段追加：

```
"quota.kind.minimax":"MiniMax Coding Plan"
```

## Patch5 — 英文翻译

在英文翻译对象（`i={...}`，含 `quota.kind.xiaomi-token-plan-cn":"Xiaomi MiMo Token Plan"`）
的同一段追加：

```
"quota.kind.minimax":"MiniMax Coding Plan"
```

> 中英两段结构几乎相同，区别在中文段的 xiaomi 翻译是「小米 MiMo Token Plan」、
> 英文段是「Xiaomi MiMo Token Plan」，apply.sh 靠这两个不同的锚点区分中英段。

## 为什么改 client.js 后要重启 dsh-web？

`quota-adapters.js`（服务端）被 dsh-service 进程启动时加载，改文件后**下一次
upstream 请求即生效**（无需重启即可重试额度查询）；但 `client.js` 是插件向
浏览器下发的 bundle，dsh-web 进程只在下发时从磁盘读，**必须重启 dsh-web**
（并浏览器硬刷新）才能让浏览器拿到新 bundle。

验证「新 bundle 已生效」的方法：额度面板窗口名应显示翻译 key 对应的中文
（如「5 小时 Token」「本周 Token」或 minimax 新条目），而不是旧硬编码文字。