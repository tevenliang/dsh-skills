#!/usr/bin/env node
/**
 * orchestrate.mjs — Universal Search 全自动编排 v5.3
 *
 * v5.3 改动：
 *   - execSync 串行 → Promise.all + spawn 真正全量并行
 *   - buildCommands 支持 call.kind === 'skill'（读取 SKILL.md 入口脚本）
 *   - anysearch / web-search-exa 等 skill kind 工具现在也被调用
 *   - builtin:web_search / web_fetch 正确输出结构化指令（子进程无法调，agent 补调）
 *   - 工具调用失败独立降级，不阻塞其他工具
 *
 * 用法:
 *   node scripts/orchestrate.mjs "搜索内容"
 *   echo "搜索内容" | node scripts/orchestrate.mjs
 */

import { spawn } from 'child_process';
import { execSync } from 'child_process';
import { readFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = resolve(__dirname, '..');
const WORKSPACE = resolve(SKILL_DIR, '../..');

// ═══════════════════════════════════════════════════════════
//  Discover 缓存 & 工具加载
// ═══════════════════════════════════════════════════════════

let _discoverCache = null;

function getDiscoverOutput(force = false) {
  if (!force && _discoverCache !== null) return _discoverCache;
  try {
    const raw = execSync(`node "${resolve(SKILL_DIR, 'scripts/discover.js')}" --cache --force`, {
      encoding: 'utf-8', timeout: 15000, shell: '/bin/bash', stdio: 'pipe',
    });
    _discoverCache = JSON.parse(raw);
  } catch {
    _discoverCache = null;
  }
  return _discoverCache;
}

// ═══════════════════════════════════════════════════════════
//  API Key 动态加载
// ═══════════════════════════════════════════════════════════

function loadApiKeys(discoverOutput) {
  const keys = {};

  if (discoverOutput) {
    for (const tool of (discoverOutput.tools || [])) {
      if (!tool.skillPath) continue;
      for (const f of [
        resolve(tool.skillPath, '.env'),
        resolve(tool.skillPath, 'config.json'),
        resolve(tool.skillPath, 'scripts', 'config.json'),
      ]) {
        if (!existsSync(f)) continue;
        try {
          if (f.endsWith('.json')) {
            const cfg = JSON.parse(readFileSync(f, 'utf-8'));
            for (const [k, v] of Object.entries(cfg)) {
              if (typeof v === 'string' && (k.endsWith('_KEY') || k.endsWith('_TOKEN') || k.endsWith('_SECRET') || k.endsWith('_API_KEY'))) {
                keys[k] = v;
              }
            }
          } else {
            for (const line of readFileSync(f, 'utf-8').split('\n')) {
              const m = line.match(/^\s*(\w+)\s*=\s*(.+?)\s*$/);
              if (m) keys[m[1]] = m[2];
            }
          }
        } catch { /* skip */ }
      }
    }
  }

  // HOME/.openclaw/.env
  try {
    const homeEnv = resolve(process.env.HOME || '/root', '.openclaw', '.env');
    if (existsSync(homeEnv)) {
      for (const line of readFileSync(homeEnv, 'utf-8').split('\n')) {
        const m = line.match(/^\s*(\w+)\s*=\s*(.+?)\s*$/);
        if (m) keys[m[1]] = m[2];
      }
    }
  } catch { /* skip */ }

  // ~/.agents/credentials/*.json
  try {
    const credsDir = resolve(process.env.HOME || '/root', '.agents', 'credentials');
    if (existsSync(credsDir)) {
      const { readdirSync } = require('fs');
      for (const file of readdirSync(credsDir)) {
        if (!file.endsWith('.json')) continue;
        try {
          const cfg = JSON.parse(readFileSync(resolve(credsDir, file), 'utf-8'));
          if (cfg.api_key) {
            const lower = file.toLowerCase();
            if (lower.includes('tavily') && !keys['TAVILY_API_KEY']) keys['TAVILY_API_KEY'] = cfg.api_key;
            if (lower.includes('metaso') && !keys['METASO_API_KEY']) keys['METASO_API_KEY'] = cfg.api_key;
            if (lower.includes('anysearch') && !keys['ANYSEARCH_API_KEY']) keys['ANYSEARCH_API_KEY'] = cfg.api_key;
            if (lower.includes('exa') && !keys['EXA_API_KEY']) keys['EXA_API_KEY'] = cfg.api_key;
          }
        } catch { /* skip */ }
      }
    }
  } catch { /* skip */ }

  // process.env 补充
  for (const k of ['BAIDU_API_KEY', 'MINIMAX_API_KEY', 'TAVILY_API_KEY', 'METASO_API_KEY', 'AMAP_WEBSERVICE_KEY', 'ANYSEARCH_API_KEY', 'EXA_API_KEY']) {
    if (process.env[k] && !keys[k]) keys[k] = process.env[k];
  }

  return keys;
}

// ═══════════════════════════════════════════════════════════
//  Skill 入口脚本探测（处理 call.kind === 'skill'）
// ═══════════════════════════════════════════════════════════

/**
 * 从 skill 目录找到可执行的入口脚本。
 * 优先级：runtime.conf > SKILL.md Command 节 > scripts/*.py/js/sh
 */
function findSkillEntry(skillPath) {
  // 1. runtime.conf（平台检测后缓存的命令）
  const rtConf = resolve(skillPath, 'runtime.conf');
  if (existsSync(rtConf)) {
    try {
      const lines = readFileSync(rtConf, 'utf-8').split('\n');
      const cmd = lines.find(l => l.startsWith('Command:'));
      if (cmd) {
        return cmd.replace(/^Command:\s*/, '').trim();
      }
    } catch { /* skip */ }
  }

  // 2. SKILL.md 中 # Command Cheat Sheet 里的命令
  const skillMd = resolve(skillPath, 'SKILL.md');
  if (existsSync(skillMd)) {
    try {
      const content = readFileSync(skillMd, 'utf-8');
      // 找 <cmd> search "..." 格式的命令行
      const m = content.match(/<\s*cmd\s*>\s*\S+.*?(?:search|batch_search|get_sub_domains|extract)[^'\n]*'([^']+)'/s);
      if (m) {
        // 提取实际的 python3/node 命令
        const cmdBlock = content.match(/`(python3?|node)\s+[^`]+scripts\/(\w+\.(?:py|js))`/);
        if (cmdBlock) {
          const runtime = cmdBlock[1];
          const script = cmdBlock[2];
          return `${runtime} "${resolve(skillPath, 'scripts', script)}"`;
        }
      }
      // 备选：直接找 python3/node scripts/xxx.py
      const direct = content.match(/`(python3?)\s+([^`]*scripts\/[\w\-]+\.(?:py|js))`/);
      if (direct) {
        return `${direct[1]} "${resolve(skillPath, direct[2])}"`;
      }
      const nodeDirect = content.match(/`(node)\s+([^`]*scripts\/[\w\-]+\.(?:py|js))`/);
      if (nodeDirect) {
        return `${nodeDirect[1]} "${resolve(skillPath, nodeDirect[2])}"`;
      }
    } catch { /* skip */ }
  }

  // 3. scripts/ 目录探测（Python > Node.js > Bash）
  const scriptsDir = resolve(skillPath, 'scripts');
  if (existsSync(scriptsDir)) {
    try {
      const { readdirSync } = require('fs');
      const files = readdirSync(scriptsDir);
      const py = files.find(f => f.endsWith('.py'));
      const js = files.find(f => f.endsWith('.js'));
      if (py) return `python3 "${resolve(scriptsDir, py)}"`;
      if (js) return `node "${resolve(scriptsDir, js)}"`;
    } catch { /* skip */ }
  }

  return null;
}

/**
 * 从 SKILL.md 的 Command Cheat Sheet 推断搜索子命令和参数格式。
 * 返回 { subcmd, argPattern } 或 null。
 */
function inferSkillSubcommand(skillPath, query) {
  const skillMd = resolve(skillPath, 'SKILL.md');
  if (!existsSync(skillMd)) return null;
  try {
    const content = readFileSync(skillMd, 'utf-8');

    // 找 <cmd> search "..." 格式
    const m = content.match(/<\s*cmd\s*>\s*(\S+)\s+(\w+)\s+['"]([^'"]+)['"]/);
    if (m) {
      return { baseCmd: m[1], subcmd: m[2], queryTemplate: m[3] };
    }

    // 备选：通用搜索命令格式 <cmd> search "query"
    const generic = content.match(/`(python3?|node)\s+([^`]+)\s+(\w+)\s+['"]([^'"]+)['"]`/);
    if (generic) {
      return {
        baseCmd: `${generic[1]} "${resolve(skillPath, generic[2])}"`,
        subcmd: generic[3],
        queryTemplate: generic[4]
      };
    }

    // 最简备选：python3 scripts/xxx.py search "query"
    const simple = content.match(/(python3?)\s+([^`\s]+scripts\/[\w\-]+\.(?:py|js))[\s]+(\w+)[\s]+['"]([^'"]+)['"]/);
    if (simple) {
      return {
        baseCmd: `${simple[1]} "${resolve(skillPath, simple[2])}"`,
        subcmd: simple[3],
        queryTemplate: simple[4]
      };
    }
  } catch { /* skip */ }
  return null;
}

// ═══════════════════════════════════════════════════════════
//  命令构建
// ═══════════════════════════════════════════════════════════

function sq(s) {
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

function buildCommandFromTemplate(template, skillPath, qConfig) {
  const rawQuery = qConfig.query || '';
  if (!rawQuery) return null;

  let cmd = template;
  cmd = cmd.replace(/\{skill_dir\}/g, skillPath);

  if (cmd.includes('<JSON>')) {
    const jsonArgs = { q: rawQuery, scope: 'all', limit: 8 };
    if (rawQuery.includes('最新') || rawQuery.includes('新闻') || rawQuery.includes('news')) {
      jsonArgs.scope = 'news';
    }
    cmd = cmd.replace(/<JSON>/g, JSON.stringify(jsonArgs));
  }

  const safeQ = sq(rawQuery);
  const dqQ = rawQuery.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/`/g, '\\`').replace(/\$/g, '\\$');
  cmd = cmd.replace(/"\{query\}"/g, `"${dqQ}"`);
  cmd = cmd.replace(/'\{query\}'/g, safeQ);
  cmd = cmd.replace(/\{query\}/g, safeQ);

  if (cmd.includes('<QUERY>')) {
    cmd = cmd.replace(/'<QUERY>'/g, safeQ);
    cmd = cmd.replace(/"<QUERY>"/g, `"${dqQ}"`);
    cmd = cmd.replace(/<QUERY>/g, safeQ);
  }

  const KNOWN_OPTIONAL = [
    { key: 'location', default: '' }, { key: 'radius', default: '1000' },
    { key: 'offset', default: '10' }, { key: 'count', default: '10' },
    { key: 'page', default: '1' }, { key: 'freshness', default: '' },
    { key: 'options', default: '' }, { key: 'format', default: '' },
    { key: 'type', default: '' },
  ];
  for (const { key, default: def } of KNOWN_OPTIONAL) {
    const re = (d) => new RegExp(`'\\{${key}\\}'|"\\{${key}\\}" |\\{${key}\\}`.replace(' ', '\\s*'), 'g');
    cmd = cmd.replace(re(), def === '' ? "''" : `'${def}'`);
  }

  if (cmd.includes('node -e')) cmd = 'set +B; ' + cmd;
  return cmd;
}

/**
 * 为 call.kind === 'skill' 的工具构建命令。
 * 读取 SKILL.md 找到入口脚本 + 搜索子命令格式。
 */
function buildSkillCommand(tool, qConfig) {
  const skillPath = tool.skillPath;
  const rawQuery = qConfig.query || '';
  if (!rawQuery) return null;

  // 找入口命令
  const entry = inferSkillSubcommand(skillPath, rawQuery);
  if (!entry) return null;

  const { baseCmd, subcmd, queryTemplate } = entry;

  // 替换 query 占位符
  let fullCmd = `${baseCmd} ${subcmd} `;
  if (queryTemplate.includes('<QUERY>') || queryTemplate.includes('{query}') || queryTemplate.includes('<JSON>')) {
    // 直接用模板
    let arg = queryTemplate
      .replace(/<QUERY>/g, sq(rawQuery))
      .replace(/'\{query\}'/g, sq(rawQuery))
      .replace(/"\{query\}"/g, `"${rawQuery.replace(/"/g, '\\"')}"`)
      .replace(/\{query\}/g, sq(rawQuery))
      .replace(/<JSON>/g, JSON.stringify({ q: rawQuery, limit: 8 }));
    fullCmd += arg;
  } else {
    // 通用：子命令后面直接跟 query
    fullCmd += sq(rawQuery);
  }

  return fullCmd;
}

/** 从 toolId 推断解析器 */
function inferParser(toolId) {
  const id = toolId.toLowerCase();
  if (id.includes('baidu')) return 'baidu';
  if (id.includes('tavily')) return 'tavily';
  if (id.includes('amap') || id.includes('gaode')) return 'amap';
  return 'generic';
}

/**
 * 构建所有工具的执行命令（扩展支持 skill kind + 正确处理 builtin）
 */
function buildCommands(toolQueries, discoverOutput) {
  const cmds = {};
  if (!discoverOutput) return cmds;

  const toolsMap = {};
  for (const tool of (discoverOutput.tools || [])) {
    toolsMap[tool.id] = tool;
  }

  const builtinCallMap = {}; // 记录 builtin 工具，供调用方生成 agent 指令

  for (const [toolId, qConfig] of Object.entries(toolQueries)) {
    const tool = toolsMap[toolId];
    if (!tool) continue;

    const call = tool.call;

    // ── kind: shell（有 call.template）── 直接用模板 ──
    if (call?.kind === 'shell' && call.template) {
      const cmd = buildCommandFromTemplate(call.template, tool.skillPath || WORKSPACE, qConfig);
      if (!cmd) continue;
      cmds[toolId] = { cmd, cwd: tool.skillPath || WORKSPACE, parser: inferParser(toolId), kind: 'shell' };

    // ── kind: skill（读取 SKILL.md 找入口）── 核心新增 ──
    } else if (call?.kind === 'skill') {
      const cmd = buildSkillCommand(tool, qConfig);
      if (!cmd) {
        // 备选：尝试 findSkillEntry 找通用入口
        const fallback = findSkillEntry(tool.skillPath);
        if (fallback) {
          cmds[toolId] = { cmd: `${fallback} search ${sq(qConfig.query)}`, cwd: tool.skillPath || WORKSPACE, parser: inferParser(toolId), kind: 'skill' };
        }
        continue;
      }
      cmds[toolId] = { cmd, cwd: tool.skillPath || WORKSPACE, parser: inferParser(toolId), kind: 'skill' };

    // ── kind: system_tool（builtin 工具）── 跳过，子进程调不了 ──
    } else if (call?.kind === 'system_tool') {
      builtinCallMap[toolId] = { tool, qConfig };
    }
  }

  return { cmds, builtinCallMap };
}

// ═══════════════════════════════════════════════════════════
//  结果解析器
// ═══════════════════════════════════════════════════════════

function parseGenericResults(toolId, stdout) {
  const results = [];
  const engineName = toolId.replace(/^skill:/, '');
  try {
    const data = JSON.parse(stdout);
    if (Array.isArray(data)) {
      for (const item of data) {
        results.push({
          engine: engineName,
          url: item.url || item.link || item.href || '',
          title: (item.title || item.name || '').substring(0, 200),
          content: (item.content || item.snippet || item.description || item.summary || item.text || '').substring(0, 500),
          snippet: (item.content || item.snippet || item.description || item.summary || item.text || '').substring(0, 200),
        });
      }
      return results;
    }
    const items = data.results || data.pois || data.data || data.items || data.list || [];
    if (Array.isArray(items) && items.length > 0) {
      for (const item of items) {
        results.push({
          engine: engineName,
          url: item.url || item.link || '',
          title: (item.title || item.name || '').substring(0, 200),
          content: (item.content || item.snippet || item.description || item.address || item.summary || '').substring(0, 500),
          snippet: (item.content || item.snippet || item.description || item.address || item.summary || '').substring(0, 200),
        });
      }
      return results;
    }
    const textFallback = data.answer || data.summary || data.text || '';
    if (textFallback) {
      results.push({
        engine: engineName,
        url: data.url || data.link || '',
        title: (data.title || data.name || `[${engineName}]`).substring(0, 200),
        content: textFallback.substring(0, 500),
        snippet: textFallback.substring(0, 200),
      });
    }
    return results;
  } catch { /* non-JSON */ }

  const lines = stdout.trim().split('\n').filter(l => l.trim());
  for (let i = 0; i < Math.min(lines.length, 20); i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith('🔍') || line.startsWith('✅') || line.startsWith('⚠️')) continue;
    results.push({ engine: engineName, url: '', title: line.substring(0, 200), content: line.substring(0, 500), snippet: line.substring(0, 200) });
  }
  return results;
}

function parseResults(toolId, parser, stdout, stderr) {
  if (!stdout || (stderr && stderr.toLowerCase().includes('error'))) return [];
  const trimmed = stdout.trim();
  if (!trimmed) return [];
  try {
    if (parser === 'baidu') {
      const clean = trimmed.replace(/^[^\[]*(\[)/s, '$1');
      return JSON.parse(clean).map(item => ({
        engine: 'baidu-search', url: item.url || '', title: (item.title || '').substring(0, 200),
        content: (item.content || '').substring(0, 500), snippet: (item.content || '').substring(0, 200),
      }));
    }
    if (parser === 'tavily') {
      const brave = JSON.parse(trimmed);
      const results = [];
      if (brave.results) {
        for (const r of brave.results) {
          results.push({ engine: 'tavily-search', url: r.url || '', title: (r.title || '').substring(0, 200),
            content: (r.snippet || r.title || '').substring(0, 500), snippet: (r.snippet || r.title || '').substring(0, 200) });
        }
      }
      if (brave.answer && results.length === 0) {
        results.push({ engine: 'tavily-search', url: '', title: 'Tavily Answer',
          content: brave.answer.substring(0, 500), snippet: brave.answer.substring(0, 200) });
      }
      return results;
    }
    return parseGenericResults(toolId, stdout);
  } catch (e) {
    if (parser !== 'generic') return parseGenericResults(toolId, stdout);
    return [{ engine: toolId, url: '', title: trimmed.split('\n')[0].substring(0, 200), content: trimmed.substring(0, 500), snippet: trimmed.substring(0, 200) }];
  }
}

// ═══════════════════════════════════════════════════════════
//  并行执行（v5.3 核心改动：Promise.all + spawn）
// ═══════════════════════════════════════════════════════════

/**
 * 用 spawn 执行单条命令，返回 Promise。
 * 超时自动杀孙子进程。
 */
function execOneTool(toolId, cmd, cwd, parser, env, onLog) {
  return new Promise((resolve) => {
    const args = ['-c', cmd];
    const child = spawn('/bin/bash', args, {
      cwd,
      env: { ...process.env, ...env },
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';

    const timer = setTimeout(() => {
      try { process.kill(-child.pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); }
    }, 60000);

    child.stdout.on('data', d => { stdout += d.toString(); });
    child.stderr.on('data', d => { stderr += d.toString(); });
    child.on('close', code => {
      clearTimeout(timer);
      if (code === 0 || stdout.trim()) {
        const results = parseResults(toolId, parser, stdout, stderr);
        onLog(`  ✅ ${toolId}: ${results.length}条`);
        resolve(results);
      } else {
        const msg = (stderr || 'no output').slice(0, 80).replace(/\n/g, ' ');
        onLog(`  ⚠️  ${toolId}: exit=${code} ${msg}`);
        resolve([]);
      }
    });
    child.on('error', e => {
      clearTimeout(timer);
      onLog(`  ❌ ${toolId}: ${e.message.slice(0, 80)}`);
      resolve([]);
    });
  });
}

/**
 * 全量并行执行一轮所有工具。
 * 返回所有工具结果合并数组。
 */
async function execOneRoundParallel(commands, env, onLog) {
  const toolIds = Object.keys(commands);
  if (toolIds.length === 0) return [];

  const promises = toolIds.map(toolId => {
    const { cmd, cwd, parser } = commands[toolId];
    return execOneTool(toolId, cmd, cwd, parser, env, onLog);
  });

  const resultsArrays = await Promise.all(promises);
  return resultsArrays.flat();
}

// ═══════════════════════════════════════════════════════════
//  System Tool 指令生成（builtin 工具由 agent 并行补调）
// ═══════════════════════════════════════════════════════════

function detectLangSys(query) {
  let cjk = 0, ascii = 0;
  for (const ch of query) {
    const code = ch.codePointAt(0);
    if ((code >= 0x4E00 && code <= 0x9FFF) || (code >= 0x3400 && code <= 0x4DBF)) cjk++;
    else if (code < 128) ascii++;
  }
  return cjk > ascii ? 'zh' : (cjk > 0 ? 'mixed' : 'en');
}

function generateSystemToolCalls(query, lang, anchorWords, allResults, totalRounds, builtinCallMap) {
  const calls = { web_search: [], web_fetch: [] };
  const isCN = lang === 'zh' || lang === 'mixed';
  const anchorStr = anchorWords.join(' ');

  // 从 builtinCallMap 生成 web_search 指令
  if (builtinCallMap['builtin:web_search']) {
    // Query 1: 主语言
    calls.web_search.push({
      tool: 'web_search',
      params: {
        query: isCN ? anchorStr : query,
        freshness: 'week',
        count: isCN ? 8 : 10,
      },
      purpose: isCN ? 'R1 中文综合搜索（Brave/英文覆盖国际源）' : 'R1 英文综合搜索',
    });
    // Query 2: 交叉验证
    calls.web_search.push({
      tool: 'web_search',
      params: {
        query: isCN ? query : `${query} latest developments`,
        freshness: 'week',
        count: 8,
      },
      purpose: isCN ? 'R1 英文交叉验证' : 'R1 补充变体搜索',
    });
  }

  // web_fetch 推荐
  if (allResults.length > 0) {
    const seenUrls = new Set();
    const sorted = [...allResults].sort((a, b) => (b._round || 99) - (a._round || 99));
    for (const r of sorted) {
      if (!r.url || seenUrls.has(r.url) || calls.web_fetch.length >= 5) break;
      if (r.url.startsWith('http') && r.title && r.title.length > 5) {
        seenUrls.add(r.url);
        calls.web_fetch.push({
          tool: 'web_fetch',
          params: { url: r.url, extractMode: 'markdown', maxChars: 4000 },
          title: r.title.substring(0, 120),
          purpose: '全文抓取',
        });
      }
    }
  }

  return calls;
}

// ═══════════════════════════════════════════════════════════
//  深度迭代 query 生成（动态，面向全部工具）
// ═══════════════════════════════════════════════════════════

function toolIsChinese(strengths) {
  return (strengths || []).includes('chinese') || (strengths || []).includes('china_coverage');
}
function toolIsEnglish(strengths) {
  return (strengths || []).includes('english') ||
    ((strengths || []).includes('general') && !(strengths || []).includes('chinese') && !(strengths || []).includes('china_coverage'));
}

function generateDeepQueries(auditResult, anchorWords, round, discoverOutput) {
  const anchorStr = anchorWords.join(' ');
  const signals = auditResult?.signals || [];
  const activeIds = signals.filter(s => s.active).map(s => s.id);
  const queries = {};

  const directions = [];
  if (activeIds.includes(1)) directions.push({ zh: `${anchorStr} 最新进展`, en: `${anchorStr} latest update ${new Date().toISOString().slice(0,10)}` });
  if (activeIds.includes(2)) directions.push({ zh: `${anchorStr} 原因 分析 影响`, en: `${anchorStr} cause analysis impact` });
  if (activeIds.includes(3)) directions.push({ zh: `${anchorStr} 详情 背景`, en: `${anchorStr} details background` });
  if (activeIds.includes(4)) directions.push({ zh: `${anchorStr} 数据 核实`, en: `${anchorStr} data verification facts` });
  if (activeIds.includes(5)) directions.push({ zh: `${anchorStr} 核实 辟谣`, en: `${anchorStr} fact check` });
  if (activeIds.includes(7)) directions.push({ zh: `${anchorStr} 更多信息`, en: `${anchorStr} overview comprehensive` });

  if (directions.length === 0) {
    directions.push({ zh: `${anchorStr} 详情 影响 相关`, en: `${anchorStr} details impact related` });
    directions.push({ zh: `${anchorStr} 背景 历史`, en: `${anchorStr} background history` });
  }

  const selected = directions.slice(0, 3);

  // 全部可用搜索工具（shell + skill 两种 kind）
  const searchTools = (discoverOutput?.tools || []).filter(t =>
    t.status === 'ready' && t.id.startsWith('skill:') &&
    (t.call?.kind === 'shell' || t.call?.kind === 'skill')
  );

  if (searchTools.length === 0) return queries;

  const cnTools = searchTools.filter(t => toolIsChinese(t.strengths || []));
  const enTools = searchTools.filter(t => toolIsEnglish(t.strengths || []));
  const otherTools = searchTools.filter(t => !cnTools.includes(t) && !enTools.includes(t));

  for (let i = 0; i < selected.length; i++) {
    if (i < cnTools.length) queries[cnTools[i].id] = { query: selected[i].zh, lang: 'zh' };
    if (i < enTools.length) queries[enTools[i].id] = { query: selected[i].en, lang: 'en' };
  }

  const used = new Set(Object.keys(queries));
  for (const tool of [...cnTools, ...enTools, ...otherTools]) {
    if (used.has(tool.id)) continue;
    const zh = toolIsChinese(tool.strengths || []);
    queries[tool.id] = { query: zh ? selected[0].zh : selected[0].en, lang: zh ? 'zh' : 'en' };
  }

  return queries;
}

// ═══════════════════════════════════════════════════════════
//  主流程
// ═══════════════════════════════════════════════════════════

async function main() {
  const args = process.argv.slice(2);
  let query = args.join(' ') || '';
  if (!query && !process.stdin.isTTY) {
    query = readFileSync(0, 'utf-8').trim();
  }
  if (!query) {
    console.error('Usage: node scripts/orchestrate.mjs "搜索内容"'); process.exit(1);
  }

  const startTime = Date.now();

  // Step 0: discover（强制刷新，确保拿到最新工具列表）
  const discoverOutput = getDiscoverOutput(true);
  if (!discoverOutput) {
    console.error('discover 失败，无法继续'); process.exit(1);
  }
  const totalTools = (discoverOutput.tools || []).filter(t => t.status === 'ready').length;

  // Step 1: api keys
  const apiKeys = loadApiKeys(discoverOutput);

  // Step 2: prepare
  process.stderr.write('🔍 准备中... ');
  let prep;
  try {
    const prepRaw = execSync(
      `node "${resolve(SKILL_DIR, 'scripts/prepare.mjs')}" --query "${query.replace(/"/g, '\\"')}"`,
      { encoding: 'utf-8', cwd: SKILL_DIR, timeout: 15000, shell: '/bin/bash', stdio: 'pipe' }
    );
    prep = JSON.parse(prepRaw);
  } catch (e) {
    console.error('prepare 失败:', e.message); process.exit(1);
  }
  process.stderr.write(`锚点=${prep.anchor_words.join(',')} 复杂度=${prep.complexity}\n`);

  const hasTools = Object.keys(prep.tool_queries || {}).length > 0;
  if (!hasTools) {
    console.log(JSON.stringify({ version: '5.3', query, error: 'no_search_tools', elapsed_seconds: '0', total_rounds: 0 }, null, 2));
    process.exit(0);
  }

  // 扩展 prep.tool_queries 支持 skill kind 工具（prepare.mjs 可能只给了 shell kind 的工具）
  const allReadyTools = (discoverOutput?.tools || []).filter(t =>
    t.status === 'ready' && t.id.startsWith('skill:') &&
    (t.call?.kind === 'shell' || t.call?.kind === 'skill')
  );
  for (const tool of allReadyTools) {
    if (!prep.tool_queries[tool.id]) {
      // 补充未被 prepare 覆盖的 skill kind 工具
      const zh = toolIsChinese(tool.strengths || []);
      prep.tool_queries[tool.id] = {
        query: zh ? prep.anchor_words.join(' ') : query,
        lang: zh ? 'zh' : 'en'
      };
    }
  }

  const minDepth = prep.complexity === 'L0' ? 0 : prep.complexity === 'L1' ? 1 : 2;
  const maxRounds = prep.complexity === 'L0' ? 1 : prep.complexity === 'L1' ? 4 : 5;

  const env = { ...process.env, ...apiKeys };
  let allResults = [];
  const roundLogs = [];
  let finalAudit = null;
  const seenUrls = new Set();
  const allToolsUsed = new Set();
  let builtinCallMap = {};

  for (let round = 1; round <= maxRounds; round++) {
    const isFirst = round === 1;

    const toolQueries = isFirst
      ? prep.tool_queries
      : generateDeepQueries(finalAudit, prep.anchor_words, round, discoverOutput);

    const effectiveQueries = Object.keys(toolQueries).length > 0 ? toolQueries : prep.tool_queries;

    const { cmds, builtinMap } = buildCommands(effectiveQueries, discoverOutput);
    builtinCallMap = builtinMap; // 更新全局 builtinMap

    if (Object.keys(cmds).length === 0) {
      roundLogs.push({ round, label: `R${round}`, error: '无可执行命令', tools_called: [] });
      process.stderr.write(`⚠️  R${round}: 无可执行命令\n`);
      break;
    }

    const label = isFirst ? '广度 R1' : `深度 R${round}`;
    process.stderr.write(`${round > 1 ? '\n' : ''}⚡ ${label}: ${Object.keys(cmds).length} 个工具并行 [${Object.keys(cmds).join(', ')}]\n`);

    Object.keys(cmds).forEach(id => allToolsUsed.add(id));

    // ── v5.3 核心：全量并行执行 ──
    const roundResults = await execOneRoundParallel(cmds, env,
      (msg) => process.stderr.write(msg + '\n'));

    const filtered = roundResults.filter(r => r.title || r.content);

    let newCount = 0;
    for (const r of filtered) {
      const key = r.url || (r.title + (r.snippet || ''));
      if (key && !seenUrls.has(key)) {
        seenUrls.add(key); newCount++;
      } else if (!key) {
        newCount++;
      }
      allResults.push({ ...r, _round: round });
    }

    process.stderr.write(`📦 ${label}: ${filtered.length}条 (${newCount} new, ${allResults.length} total)\n`);

    // Audit
    const auditInput = {
      query, anchor_words: prep.anchor_words,
      round, complexity: prep.complexity, max_depth: maxRounds,
      results: filtered,
    };

    let audit;
    try {
      audit = JSON.parse(execSync(
        `node "${resolve(SKILL_DIR, 'scripts/audit.mjs')}"`,
        { input: JSON.stringify(auditInput), encoding: 'utf-8', cwd: SKILL_DIR, timeout: 10000, env, shell: '/bin/bash', stdio: 'pipe' }
      ));
    } catch (e) {
      audit = { summary: { backlink_passed: 0, total_results: filtered.length, converged: false, convergence_reason: e.message.slice(0, 80) }, signals: [], backlink_details: { passed: [], failed: [] }, recommendations: [] };
    }

    finalAudit = audit;
    const s = audit.summary || {};
    const activeSigs = (audit.signals || []).filter(sig => sig.active).map(sig => sig.name);

    roundLogs.push({
      round, label, tools_called: [...Object.keys(cmds)],
      results_count: filtered.length, new_sources: newCount,
      backlink_passed: s.backlink_passed || 0,
      anchor_relevance_rate: s.anchor_relevance_rate || '0%',
      converged: s.converged || false, active_signals: activeSigs,
      convergence_reason: s.convergence_reason || '',
    });

    process.stderr.write(`🔎 ${label}: passed=${s.backlink_passed}/${filtered.length} rel=${s.anchor_relevance_rate} converged=${s.converged ? '✅' : '❌'}\n`);

    if (round >= minDepth + 1 && s.converged) {
      process.stderr.write(`🏁 收敛 (${round}/${maxRounds})\n`); break;
    }
    if (round >= maxRounds) {
      process.stderr.write(`⚠️  硬上限 ${maxRounds} 轮\n`); break;
    }
  }

  // System tool 指令（agent 补调 builtin 工具）
  const lang = detectLangSys(query);
  // Inline builtin tool instructions (子进程无法调builtin，直接生成agent补调指令)
  const isCN = detectLangSys(query) !== 'en';
  const anchorStr = prep.anchor_words.join(' ');
  const systemToolCalls = {
    web_search: [
      { tool: 'web_search', params: { query: isCN ? anchorStr : query, freshness: 'week', count: isCN ? 8 : 10 }, purpose: isCN ? 'R1 Brave搜索（中文覆盖）' : 'R1 Brave搜索（英文）' },
      { tool: 'web_search', params: { query: isCN ? query : query + " latest developments", freshness: 'week', count: 8 }, purpose: isCN ? 'R1 交叉验证' : 'R1 补充变体' },
    ],
    web_fetch: [],
  };
  // 推荐抓取URL
  const fetchUrls = [];
  const fetchSeen = new Set();
  const sortedResults = allResults.sort((a,b) => (a._round||99)-(b._round||99));
  for (const r of sortedResults) {
    if (fetchUrls.length >= 5) break;
    if (!r.url || fetchSeen.has(r.url) || !r.url.startsWith('http')) continue;
    fetchSeen.add(r.url);
    fetchUrls.push({ title: r.title||'', url: r.url, engine: r.engine||'' });
  }
  systemToolCalls.web_fetch = fetchUrls.map(u => ({ tool: 'web_fetch', params: { url: u.url, extractMode: 'markdown', maxChars: 4000 }, title: u.title, purpose: '全文抓取' }));

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  const s = finalAudit?.summary || {};
  const output = {
    version: '5.3',
    query,
    anchor_words: prep.anchor_words,
    complexity: prep.complexity,
    intent: prep.intent,
    elapsed_seconds: elapsed,
    total_rounds: roundLogs.length,
    tools_available: (discoverOutput?.ready || []).map(t => ({ id: t.id, name: t.name, kind: t.kind, strengths: t.strengths })),
    tools_called_skill: [...allToolsUsed],
    system_tool_calls: systemToolCalls,
    results_total: allResults.length,
    backlink_passed: finalAudit?.backlink_details?.passed?.length || 0,
    anchor_relevance_rate: s.anchor_relevance_rate || '0%',
    converged: s.converged || false,
    convergence_reason: s.convergence_reason || '',
    active_signals: finalAudit?.signals?.filter(sig => sig.active).map(sig => sig.name) || [],
    information_density: s.information_density?.rating || '未知',
    suggested_fetch_urls: fetchUrls,
    round_log: roundLogs,
    all_results: sortedResults.map(r => ({
      engine: r.engine, title: (r.title || '').substring(0, 200),
      url: r.url || '', snippet: (r.snippet || r.content || '').substring(0, 200), round: r._round,
    })),
    gate_checklist: prep.gate_checklist,
  };

  console.log(JSON.stringify(output, null, 2));
  if (!s.converged) process.exit(1);
}

main();
