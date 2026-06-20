"""浏览器仪表盘页面(纯静态 HTML + JS，调用 /api/v1 实时渲染)。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])

PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 鉴股 · 仪表盘</title>
<style>
  :root{--bg:#f6f7f9;--card:#fff;--line:#e6e8eb;--muted:#6b7280;--text:#1f2937;--up:#c0392b;--down:#178a4c;--info:#2563eb}
  *{box-sizing:border-box} body{margin:0;background:#f6f7f9;color:#1f2937;font:15px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,"PingFang SC","Microsoft YaHei",sans-serif}
  .wrap{max-width:1080px;margin:0 auto;padding:20px}
  .row{display:flex;gap:16px;flex-wrap:wrap} .col{flex:1;min-width:300px}
  .card{background:#fff;border:1px solid #e6e8eb;border-radius:12px;padding:16px 18px;margin-bottom:16px}
  h1{font-size:20px;margin:0} h2{font-size:15px;margin:0 0 10px;font-weight:600}
  .muted{color:#6b7280} .pill{display:inline-block;padding:3px 10px;border-radius:8px;font-size:13px;background:#eef2ff;color:#2563eb}
  table{width:100%;border-collapse:collapse;font-size:14px} td,th{padding:7px 6px;border-bottom:1px solid #eef0f2;text-align:left}
  th{color:#6b7280;font-weight:500} tr.clk:hover{background:#f3f4f6;cursor:pointer}
  input,button{font:inherit;padding:8px 12px;border:1px solid #d1d5db;border-radius:8px;background:#fff}
  button{cursor:pointer;background:#2563eb;color:#fff;border-color:#2563eb}
  .eng{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
  .eng .b{background:#f6f7f9;border-radius:8px;padding:8px 10px}
  .big{font-size:22px;font-weight:600} .num{font-variant-numeric:tabular-nums}
  .kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:6px 0}
  .kv .b{background:#f6f7f9;border-radius:8px;padding:8px 10px} .lbl{font-size:12px;color:#6b7280}
  .banner{background:#fff8e6;border:1px solid #f0d58a;border-radius:12px;padding:10px 14px;margin-bottom:16px;font-size:13px;color:#7a5b12}
  .banner b{color:#5c4309}
</style>
</head>
<body>
<div class="wrap">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
    <h1>AI 鉴股 · 仪表盘</h1>
    <span id="regime" class="pill">加载中…</span>
  </div>

  <div class="banner">
    <b>定位:研究 / 筛选 / 监控工具。</b>本系统提供<b>透明可解释的规则评分 + AI 研判 + 行业产业链</b>,
    用于辅助研究与盯盘。经严谨回测与 IC 检验:<b>当前评分没有稳健的截面选股 alpha(IC≈0)</b>,
    评分高 ≠ 更会涨;历史回测的高收益主要来自市场 beta 与样本幸存者偏差。
    本页所有评分、价格、目标位与 AI 分析<b>仅供研究参考,不预测涨跌、不构成投资建议</b>,据此交易风险自负。
  </div>

  <div class="row">
    <div class="col">
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
          <h2 style="margin:0">综合评分 Top 20</h2>
          <a href="/api/v1/ranking/export.csv?top_n=100" style="font-size:13px;color:#2563eb;text-decoration:none">导出 CSV ↓</a>
        </div>
        <table id="rank"><thead><tr><th>#</th><th>代码</th><th>名称</th><th>行业</th><th>综合</th><th></th></tr></thead><tbody><tr><td colspan="6" class="muted">加载中…(需先跑 scan 生成排行)</td></tr></tbody></table>
      </div>
    </div>
    <div class="col">
      <div class="card">
        <h2>个股分析</h2>
        <div style="display:flex;gap:8px;margin-bottom:12px">
          <input id="code" placeholder="股票代码,如 600519" style="flex:1" />
          <button onclick="loadStock()">评分</button>
          <button onclick="loadAI()" style="background:#fff;color:#2563eb">AI 分析</button>
        </div>
        <div id="stock" class="muted">输入代码后查看六引擎评分、交易计划与 AI 研判。</div>
      </div>
    </div>
  </div>
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <h2 style="margin:0">我的自选</h2>
      <span class="muted" style="font-size:12px">点击行评分 · 按分组归类 · ⚙ 设分组/提醒阈值 · 服务端持久化</span>
    </div>
    <div id="alertbar"></div>
    <table id="watch"><thead><tr><th>代码</th><th>名称</th><th>行业</th><th>综合</th><th>提醒</th><th></th></tr></thead><tbody><tr><td colspan="6" class="muted">加载中…</td></tr></tbody></table>
  </div>
  <div class="card">
    <h2>近一年热门行业 + 产业链</h2>
    <div id="hot" class="muted">加载中…(按成分股涨幅中位数排序)</div>
    <div id="chain" style="margin-top:12px"></div>
  </div>
  <p class="muted" style="font-size:12px">排行与市场状态来自最近一次每日扫描(scan)的落库结果;数据每日更新。</p>
</div>
<script>
const API="/api/v1";
const f=(n,d=2)=>(n==null||isNaN(n))?"-":Number(n).toFixed(d);
async function j(u){const r=await fetch(u);if(!r.ok)throw new Error(r.status);return r.json();}

async function init(){
  try{const g=await j(`${API}/regime`);document.getElementById("regime").textContent=`市场状态: ${g.regime} · 置信度 ${Math.round((g.confidence||0)*100)}%`;}catch(e){}
  try{
    const r=await j(`${API}/ranking?top_n=20`);
    const rows=(r.items||[]).map(it=>`<tr class="clk" onclick="document.getElementById('code').value='${it.code}';loadStock()"><td>${it.rank}</td><td>${it.code}</td><td>${it.name||""}</td><td class="muted">${it.industry||""}</td><td class="num">${f(it.composite_score,1)}</td><td><span title="加入自选" style="cursor:pointer;color:#f0a500" onclick="event.stopPropagation();addWatch('${it.code}')">★</span></td></tr>`).join("");
    document.querySelector("#rank tbody").innerHTML=rows||`<tr><td colspan="6" class="muted">暂无排行,请先运行 scan</td></tr>`;
  }catch(e){document.querySelector("#rank tbody").innerHTML=`<tr><td colspan="6" class="muted">排行加载失败</td></tr>`;}
}

async function loadStock(){
  const code=document.getElementById("code").value.trim();if(!code)return;
  const box=document.getElementById("stock");box.innerHTML="加载中…";
  try{
    const d=await j(`${API}/stock/${code}/report`);
    const eng=Object.entries(d.engine_scores||{}).map(([k,v])=>{
      const col=v.score>=65?"#178a4c":v.score<=35?"#c0392b":"#374151";
      return `<div class="b"><div style="display:flex;justify-content:space-between"><span>${k}</span><span class="big num" style="color:${col}">${f(v.score,0)}</span></div><div class="lbl">置信 ${Math.round((v.confidence||0)*100)}% · ${(v.signals||[]).slice(0,1).join("")}</div></div>`;
    }).join("");
    const p=d.trade_plan||{};
    let plan="";
    if(p.available){
      plan=`<h2 style="margin-top:14px">交易计划 (现价 ${f(p.last_close)} · ${p.action})</h2>
      <div class="kv">
        <div class="b"><div class="lbl">建议买入区间</div><div class="num" style="color:#178a4c">${f(p.entry_low)} ~ ${f(p.entry_high)}</div></div>
        <div class="b"><div class="lbl">止损</div><div class="num" style="color:#c0392b">${f(p.stop_loss)}</div></div>
        <div class="b"><div class="lbl">技术目标 (风报比 ${f(p.risk_reward,1)})</div><div class="num">${f(p.target_technical)} (+${f(p.upside_technical_pct,1)}%)</div></div>
        <div class="b"><div class="lbl">价值目标 (PE回归中位)</div><div class="num">${p.target_value!=null?f(p.target_value)+" ("+(p.upside_value_pct>=0?"+":"")+f(p.upside_value_pct,1)+"%)":"-"}</div></div>
      </div>`;
    }
    box.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:baseline"><div><b>${d.name} (${d.code})</b> <span class="muted">${d.industry||""}</span> <span title="加入自选" style="cursor:pointer;color:#f0a500" onclick="addWatch('${d.code}')">★加自选</span></div><div class="big num">${f(d.composite_score,1)}<span class="muted" style="font-size:13px">/100 · 引擎 ${d.available_engines}/${d.total_engines}</span></div></div>
      <div class="eng" style="margin-top:10px">${eng}</div>${plan}
      <div id="ai" class="muted" style="margin-top:12px"></div>`;
  }catch(e){box.innerHTML=`<span class="muted">加载失败(代码无数据?请先 update-data / scan)</span>`;}
}

async function loadAI(){
  const code=document.getElementById("code").value.trim();if(!code)return;
  const ai=document.getElementById("ai");if(ai)ai.textContent="AI 分析中…";
  try{
    const d=await j(`${API}/stock/${code}/ai-analysis`);const a=d.analysis||{};
    if(!a.available){if(ai)ai.textContent="AI 不可用: "+(a.reason||"");return;}
    if(ai)ai.innerHTML=`<b>AI 评级: ${a.rating||"-"}</b> (置信 ${Math.round((a.confidence||0)*100)}%)<br>${a.summary||""}<br><span style="color:#178a4c">看多:</span> ${(a.bull_points||[]).join("；")}<br><span style="color:#c0392b">看空:</span> ${(a.bear_points||[]).join("；")}<br><span class="muted">操作: ${a.suggested_action||""}</span>`;
  }catch(e){if(ai)ai.textContent="AI 分析失败";}
}
async function loadHot(){
  const box=document.getElementById("hot");
  try{
    const r=await j(`${API}/industry/hot?top=8`);
    if(!(r.items||[]).length){box.innerHTML='<span class="muted">暂无行业数据(需先 update-data --include-slow-data 灌行业指数)</span>';return;}
    box.innerHTML=`<div class="eng">`+r.items.map(it=>`<div class="b clk" onclick="loadChain('${it.industry.replace(/'/g,"")}')" style="cursor:pointer"><div style="display:flex;justify-content:space-between"><span>#${it.rank}</span><span class="num" style="color:#178a4c">${it.median_return>=0?'+':''}${f(it.median_return,1)}%</span></div><div class="lbl">${it.industry}</div><div class="lbl">样本 ${it.stock_count} · 均值 ${f(it.mean_return,1)}%</div></div>`).join("")+`</div><div class="muted" style="font-size:12px;margin-top:6px">点击行业查看头部个股与产业链分析</div>`;
  }catch(e){box.innerHTML='<span class="muted">热门行业加载失败</span>';}
}
async function loadChain(industry){
  const box=document.getElementById("chain");box.innerHTML=`产业链分析中(${industry})…`;
  try{
    const d=await j(`${API}/industry/chain?industry=${encodeURIComponent(industry)}&top=12`);
    const stocks=(d.top_stocks||[]).map(s=>`${s.name||s.code}(${s.code}) ${s.return_1y>=0?'+':''}${f(s.return_1y,0)}%`).join(" · ");
    const c=d.chain||{};let chain="";
    if(c.available){
      const bl=(t,k)=>{const a=c[k]||[];return a.length?`<div style="margin-top:4px"><b>${t}:</b> ${a.join("；")}</div>`:"";};
      const ben=(c.chain_beneficiaries||[]).map(b=>typeof b==="object"?`${b.name||""}${b.code?"("+b.code+")":""} [${b.role||""}] ${b.reason||""}`:b).join("<br>");
      chain=`<div style="margin-top:6px"><b>产业链 · ${industry}</b> ${c.summary?("— "+c.summary):""}</div>${bl("上游","upstream")}${bl("下游","downstream")}${bl("合作配套","partners")}${bl("风险","risks")}${ben?`<div style="margin-top:4px"><b>受益标的:</b><br>${ben}</div>`:""}`;
    }else{chain=`<div class="muted" style="margin-top:6px">产业链 AI 不可用: ${c.reason||""}</div>`;}
    box.innerHTML=`<div class="b" style="background:#f6f7f9;border-radius:8px;padding:10px 12px"><div class="lbl">头部个股(按近一年涨幅)</div><div style="margin:4px 0">${stocks}</div>${chain}</div>`;
  }catch(e){box.innerHTML='<span class="muted">产业链加载失败</span>';}
}
function alertCell(it){
  const parts=[];
  if(it.alert_above!=null)parts.push(`≥${f(it.alert_above,0)}`);
  if(it.alert_below!=null)parts.push(`≤${f(it.alert_below,0)}`);
  let txt=parts.length?parts.join(" / "):'<span class="muted">—</span>';
  if(it.alert_triggered==="above")txt+=' <span style="color:#178a4c">▲已触发</span>';
  else if(it.alert_triggered==="below")txt+=' <span style="color:#c0392b">▼已触发</span>';
  return txt;
}
async function loadWatch(){
  const tb=document.querySelector("#watch tbody");
  try{
    const r=await j(`${API}/watchlist`);
    if(!(r.items||[]).length){tb.innerHTML=`<tr><td colspan="6" class="muted">暂无自选。在排行或个股里点 ★ 加入。</td></tr>`;document.getElementById("alertbar").innerHTML="";return;}
    let html="";
    for(const g of (r.groups||[])){
      if((r.groups||[]).length>1||g.name!=="默认")html+=`<tr><td colspan="6" style="background:#f3f4f6;font-weight:600;color:#374151">${g.name} · ${g.items.length}</td></tr>`;
      html+=g.items.map(it=>`<tr class="clk" onclick="document.getElementById('code').value='${it.code}';loadStock()"><td>${it.code}</td><td>${it.name||""}</td><td class="muted">${it.industry||""}</td><td class="num">${f(it.composite_score,1)}</td><td style="font-size:13px">${alertCell(it)}</td><td style="white-space:nowrap"><span title="设分组/提醒" style="cursor:pointer" onclick="event.stopPropagation();editWatch('${it.code}','${(it.group||"").replace(/'/g,"")}')">⚙</span> <span title="移除" style="cursor:pointer;color:#c0392b" onclick="event.stopPropagation();delWatch('${it.code}')">✕</span></td></tr>`).join("");
    }
    tb.innerHTML=html;
    loadAlerts();
  }catch(e){tb.innerHTML=`<tr><td colspan="6" class="muted">自选加载失败</td></tr>`;}
}
async function loadAlerts(){
  try{
    const r=await j(`${API}/watchlist/alerts`);
    const bar=document.getElementById("alertbar");
    if(!(r.alerts||[]).length){bar.innerHTML="";return;}
    bar.innerHTML=`<div style="background:#fff8e6;border:1px solid #f0d58a;border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:13px">🔔 提醒触发(${r.count}):`+r.alerts.map(a=>`${a.name||a.code} 评分 ${f(a.score,1)} ${a.type==="above"?"≥":"≤"} ${f(a.threshold,0)}`).join(" · ")+`</div>`;
  }catch(e){}
}
async function addWatch(code){
  if(!code)return;
  try{await fetch(`${API}/watchlist`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code})});loadWatch();}catch(e){}
}
async function editWatch(code,group){
  const g=prompt("分组名(留空保持不变):",group||"默认");if(g===null)return;
  const ab=prompt("评分≥多少提醒(留空=不改/清除请填 0 以下无效,填数字):","");
  const bl=prompt("评分≤多少提醒(留空跳过):","");
  const body={code};
  if(g.trim())body.group_name=g.trim();
  if(ab!==null&&ab.trim()!=="")body.alert_above=parseFloat(ab);
  if(bl!==null&&bl.trim()!=="")body.alert_below=parseFloat(bl);
  try{await fetch(`${API}/watchlist`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});loadWatch();}catch(e){}
}
async function delWatch(code){
  try{await fetch(`${API}/watchlist/${code}`,{method:"DELETE"});loadWatch();}catch(e){}
}
init();loadHot();loadWatch();
</script>
</body></html>"""


@router.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return PAGE
