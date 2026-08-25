#!/bin/bash
# usage-check 统一入口
set -u

if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    SCRIPT_DIR="/Users/tianwenliang/.agents/skills/System/usage-check/scripts"
fi

MODULE="${1:-all}"
MODE="${2:-human}"
VALID_MODULES=("minimax" "tavily" "openrouter" "vm" "all")

[[ ! " ${VALID_MODULES[*]} " =~ " ${MODULE} " ]] && { echo "❌ 未知模块: $MODULE"; exit 2; }
[[ "$MODE" != "human" && "$MODE" != "json" ]] && { echo "❌ 未知模式: $MODE"; exit 2; }

run_module() {
    case $1 in
        minimax)      echo "$SCRIPT_DIR/minimax-check.sh" ;;
        tavily)       echo "$SCRIPT_DIR/tavily-check.sh" ;;
        openrouter)     echo "$SCRIPT_DIR/openrouter-check.sh" ;;
        vm)           echo "$SCRIPT_DIR/vm-check.py" ;;
        *)            echo "" ;;
    esac
}

fmt_minimax_human() {
    python3 -c "
import json,sys
data=json.loads('''$1''')
print('=== MiniMax 用量 ===')
if 'error' in data: print('⚠️  '+data['error']);sys.exit(0)
for m in data.get('models',[]):
    print('【'+m['model']+'】')
    w5=m['5h_window']
    print('  ⏰ 5h窗口: '+w5['start_time']+' ~ '+w5['end_time']+' ('+w5['status_text']+') | 剩余 '+w5['remaining_time'])
    print('  📊 5h用量: '+str(w5['used_percent'])+'% 已用 | '+str(w5['remaining_percent'])+'% 剩 | '+w5['health_emoji']+' '+w5['health'])
    ww=m['weekly_window']
    boost=(' | +'+str(ww['boost_percent'])+'%') if ww.get('boost_percent') else ''
    print('  📅 本周窗口: '+ww['start_time']+' ~ '+ww['end_time']+' ('+ww['status_text']+') | 剩余 '+ww['remaining_time']+boost)
    print('  📈 本周用量: '+str(ww['used_percent'])+'% 已用 | '+str(ww['remaining_percent'])+'% 剩 | '+ww['health_emoji']+' '+ww['health'])
print('  ⏱️ 抓取时间: '+data.get('fetched_at','?'))
"
}

fmt_tavily_human() {
    python3 -c "
import json,sys
data=json.loads('''$1''')
print('=== Tavily 用量 ===')
if 'error' in data: print('⚠️  '+data['error']);sys.exit(0)
print('📡 Tavily ['+data['plan']+']')
print('   已用: '+str(data['used'])+' / '+str(data['limit'])+' ('+str(data['used_percent'])+'%)')
print('   剩余: '+str(data['remaining'])+' credits')
print('   搜索消耗: '+str(data['search_usage'])+' credits')
print('   健康度: '+data['health_emoji']+' '+data['health'])
print('   ⏱️ 抓取时间: '+data.get('fetched_at','?'))
"
}

fmt_openrouter_human() {
    python3 -c "
import json,sys
data=json.loads('''$1''')
print('=== OpenRouter 余额 ===')
if 'error' in data: print('WARNING: '+data['error']);sys.exit(0)
print('OpenRouter [USD]')
print('  total_credits: '+str(data['total_credits']))
print('  total_usage: '+str(data['total_usage']))
print('  remaining: '+str(data['remaining'])+' | '+data['health_emoji']+' '+data['health'])
print('  fetched_at: '+data.get('fetched_at','?'))
"
}





fmt_vm_human() {
    python3 -c "
import json,sys
data=json.loads('''$1''')
print('=== VM (Hermes) 状态 ===')
if 'error' in data: print('⚠️  '+data['error']+' ['+data.get('host','')+']');sys.exit(0)
d=data['disk'];m=data['memory'];c=data['cpu']
print('💾 硬盘 ['+str(d['total_gb'])+'G total]')
print('   已用: '+str(d['used_gb'])+'G / '+str(d['total_gb'])+'G ('+str(d['used_percent'])+'%) | 剩余 '+str(d['avail_gb'])+'G | '+d['health_emoji']+' '+d['health'])
print('🧠 内存 ['+str(m['total_mb'])+'M total]')
print('   已用: '+str(m['used_mb'])+'M / '+str(m['total_mb'])+'M ('+str(m['used_percent'])+'%) | 可用 '+str(m['avail_mb'])+'M | '+m['health_emoji']+' '+m['health'])
print('⚙️  CPU [使用 '+str(c['used_percent'])+'% | load '+c['load_avg']+'] | '+c['health_emoji']+' '+c['health'])
print('   ⏱️ 抓取时间: '+data.get('fetched_at','?'))
"
}

if [[ "$MODULE" == "all" ]]; then
    if [[ "$MODE" == "json" ]]; then
        MINI=$(bash "$(run_module minimax)")
        TAVI=$(bash "$(run_module tavily)")
        OR=$(bash "$(run_module openrouter)" 2>/dev/null || echo '{"error":"openrouter-check failed"}')
        VMRAW=$(python3 "$(run_module vm)" 2>/dev/null || echo '{"error":"vm failed"}')
        python3 -c "
import json
m=json.loads('''$MINI''');t=json.loads('''$TAVI''');o=json.loads('''$OR''');v=json.loads('''$VMRAW''')
print(json.dumps({'minimax':m,'tavily':t,'openrouter':o,'vm':v},ensure_ascii=False,indent=2))
"
    else
        MINI=$(bash "$(run_module minimax)")
        fmt_minimax_human "$MINI"
        echo ''
        VMRAW=$(python3 "$(run_module vm)" 2>/dev/null || echo '{"error":"vm failed"}')
        fmt_vm_human "$VMRAW"
        echo ''
        TAVI=$(bash "$(run_module tavily)")
        fmt_tavily_human "$TAVI"
        echo ''
        OR=$(bash "$(run_module openrouter)" 2>/dev/null || echo '{"error":"openrouter-check failed"}')
        fmt_openrouter_human "$OR"
        echo ''
    fi
else
    if [[ "$MODULE" == "vm" ]]; then
        DATA=$(python3 "$(run_module vm)" 2>/dev/null)
        [[ "$MODE" == "json" ]] && { echo "$DATA"; } || fmt_vm_human "$DATA"
    elif [[ "$MODULE" == "openrouter" ]]; then
        DATA=$(bash "$(run_module openrouter)" 2>/dev/null)
        [[ "$MODE" == "json" ]] && { echo "$DATA"; } || fmt_openrouter_human "$DATA"
    else
        DATA=$(bash "$(run_module $MODULE)" 2>/dev/null)
        [[ "$MODE" == "json" ]] && { echo "$DATA"; } || {
            case $MODULE in
                minimax)  fmt_minimax_human "$DATA" ;;
                tavily)   fmt_tavily_human "$DATA" ;;
            esac
        }
    fi
fi

exit 0
