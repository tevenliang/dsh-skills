// patches/catalog-entry.js
// 插入位置: quota-adapters.js 的 catalog 数组（buildQuotaCatalog 内）
// 在 `createComposedAdapter({ kind: 'stepfun-step-plan', ... }),` 条目之后、数组闭合 `])` 之前

    createComposedAdapter({
      kind: 'minimax',
      fetch: fetchMiniMaxUsage,
      keyHints: ['MINIMAX_API_KEY'],
      includeProfileHint: false,
      format: 'bearer',
      hosts: ['minimaxi.com', 'minimax.io'],
      usageUrl: 'https://www.minimaxi.com/coding-plan',
    }),