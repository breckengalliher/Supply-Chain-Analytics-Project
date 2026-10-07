from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.supply_chain_risk.analytics import RISK_WEIGHTS, build_analysis


_, suppliers, parts, kpis = build_analysis(ROOT / "data" / "raw")

supplier_columns = [
    "supplier_id", "supplier_name", "country", "region", "spend", "risk_score",
    "risk_tier", "delivery_risk", "quality_risk", "lead_time_variability_risk",
    "geographic_risk", "financial_risk", "dependency_risk",
]
part_columns = [
    "part_id", "part_name", "criticality", "days_of_supply", "average_lead_time_days",
    "part_risk_score", "recommended_action",
]

payload = {
    "suppliers": suppliers[supplier_columns].to_dict(orient="records"),
    "parts": parts.loc[parts["recommended_action"] != "Monitor", part_columns].to_dict(orient="records"),
    "kpis": kpis,
    "weights": RISK_WEIGHTS,
}

template = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aerospace Supplier Risk & Resilience</title>
<style>
:root{--ink:#162433;--blue:#315f85;--orange:#b85c38;--gold:#d5a23f;--line:#dbe2e8;--soft:#f4f7f9}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui;background:#fff;color:var(--ink)}
.wrap{max-width:1250px;margin:auto;padding:28px}.eyebrow{color:#526575}.note{color:#5d6b76;margin-top:-10px}
.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:24px 0}.card,.panel{border:1px solid var(--line);border-radius:12px;padding:16px;background:#fff}.value{font-size:28px;font-weight:750}.label{color:#60717f;font-size:13px}
.grid{display:grid;grid-template-columns:1.1fr .9fr;gap:18px}.barrow{display:grid;grid-template-columns:190px 1fr 42px;gap:10px;align-items:center;margin:9px 0}.track{height:14px;background:#e8eef2;border-radius:8px}.bar{height:100%;background:var(--blue);border-radius:8px}.name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px;border-bottom:1px solid var(--line);text-align:left}th{background:var(--soft)}
.controls{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.control{padding:8px 0}.control label{display:flex;justify-content:space-between}.control input{width:100%}
.stable{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:14px 0}.badge{padding:12px;border-radius:10px;background:var(--soft)}
h1{margin-bottom:10px}h2{margin-top:32px}.high{color:var(--orange)}.medium{color:#9a6c00}.low{color:var(--blue)}
@media(max-width:850px){.cards,.controls,.stable{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}.wrap{padding:16px}}
</style></head><body><main class="wrap">
<div class="eyebrow">Synthetic Python portfolio project · Offline preview</div><h1>Aerospace Supplier Risk & Resilience</h1>
<p class="note">Decision-support indicators, not predictions. The publishable Streamlit app uses the same Python calculations.</p>
<section class="cards" id="cards"></section>
<section class="grid"><div class="panel"><h3>Highest baseline supplier risk</h3><div id="bars"></div></div>
<div class="panel"><h3>What this view answers</h3><p>Which suppliers deserve attention first when delivery, quality, lead-time variability, geography, financial health, and dependency are considered together?</p><p><b>How to read it:</b> scores prioritize investigation. They do not prove a supplier will fail.</p><div id="tiers"></div></div></section>
<h2>Parts requiring action</h2><div class="panel" style="overflow:auto"><table><thead><tr><th>Part</th><th>Criticality</th><th>Days supply</th><th>Lead time</th><th>Risk</th><th>Recommended action</th></tr></thead><tbody id="parts"></tbody></table></div>
<h2>Weight sensitivity lab</h2><p class="note">Change the relative priorities. Inputs normalize automatically to 100%.</p><div class="panel"><div class="controls" id="controls"></div><div id="normalized" class="note"></div><div class="stable" id="stability"></div><h3>Scenario ranking</h3><div id="scenarioBars"></div></div>
</main><script>
const DATA=__PAYLOAD__;
const components=Object.keys(DATA.weights);const labels={delivery_risk:'Delivery',quality_risk:'Quality',lead_time_variability_risk:'Lead-time variability',geographic_risk:'Geographic exposure',financial_risk:'Financial health',dependency_risk:'Dependency'};
const money=n=>'$'+(n/1e6).toFixed(1)+'M';
document.getElementById('cards').innerHTML=[['High-risk suppliers',DATA.kpis.high_risk_suppliers],['Critical spend exposed',money(DATA.kpis.critical_spend_exposed)],['Single-source parts',DATA.kpis.single_source_parts],['Potential stockouts',DATA.kpis.potential_stockouts],['On-time delivery',(DATA.kpis.on_time_delivery_rate*100).toFixed(1)+'%']].map(x=>`<div class="card"><div class="value">${x[1]}</div><div class="label">${x[0]}</div></div>`).join('');
function bars(rows,field,target){document.getElementById(target).innerHTML=rows.slice(0,10).map(s=>`<div class="barrow"><div class="name" title="${s.supplier_name}">${s.supplier_name}</div><div class="track"><div class="bar" style="width:${s[field]}%"></div></div><b>${s[field].toFixed(1)}</b></div>`).join('')}
bars(DATA.suppliers,'risk_score','bars');
const counts={High:0,Medium:0,Low:0};DATA.suppliers.forEach(s=>counts[s.risk_tier]++);document.getElementById('tiers').innerHTML=Object.entries(counts).map(([k,v])=>`<p><b class="${k.toLowerCase()}">${k}</b>: ${v} suppliers</p>`).join('');
document.getElementById('parts').innerHTML=DATA.parts.map(p=>`<tr><td>${p.part_id} — ${p.part_name}</td><td>${p.criticality}</td><td>${p.days_of_supply.toFixed(1)}</td><td>${p.average_lead_time_days.toFixed(1)}</td><td>${p.part_risk_score.toFixed(1)}</td><td>${p.recommended_action}</td></tr>`).join('');
document.getElementById('controls').innerHTML=components.map(c=>`<div class="control"><label><span>${labels[c]}</span><b id="v_${c}">${Math.round(DATA.weights[c]*100)}</b></label><input id="w_${c}" type="range" min="0" max="60" step="5" value="${Math.round(DATA.weights[c]*100)}"></div>`).join('');
function rank(values,field){return [...values].sort((a,b)=>b[field]-a[field]).map((x,i)=>({...x,rank:i+1}))}
function update(){let w={};components.forEach(c=>{w[c]=+document.getElementById('w_'+c).value;document.getElementById('v_'+c).textContent=w[c]});let total=Object.values(w).reduce((a,b)=>a+b,0);if(!total){w=Object.fromEntries(components.map(c=>[c,DATA.weights[c]*100]));total=100}
document.getElementById('normalized').textContent='Normalized: '+components.map(c=>labels[c]+' '+Math.round(w[c]/total*100)+'%').join(' · ');
const base=rank(DATA.suppliers,'risk_score');const next=rank(DATA.suppliers.map(s=>({...s,scenario_score:components.reduce((sum,c)=>sum+s[c]*w[c]/total,0)})),'scenario_score');const baseTop=new Set(base.slice(0,10).map(s=>s.supplier_id));const overlap=next.slice(0,10).filter(s=>baseTop.has(s.supplier_id)).length;const rankMap=Object.fromEntries(base.map(s=>[s.supplier_id,s.rank]));let d2=next.reduce((sum,s)=>sum+(rankMap[s.supplier_id]-s.rank)**2,0);let n=next.length;let rho=1-(6*d2)/(n*(n*n-1));let changes=next.filter(s=>{let t=s.scenario_score>=35?'High':s.scenario_score>=25?'Medium':'Low';return t!==s.risk_tier}).length;
document.getElementById('stability').innerHTML=`<div class="badge"><b>${overlap}/10</b><br>Top suppliers retained</div><div class="badge"><b>${rho.toFixed(2)}</b><br>Rank stability</div><div class="badge"><b>${changes}</b><br>Risk-tier changes</div>`;bars(next,'scenario_score','scenarioBars')}
components.forEach(c=>document.getElementById('w_'+c).addEventListener('input',update));update();
</script></body></html>'''

output = ROOT / "dashboard_preview.html"
output.write_text(template.replace("__PAYLOAD__", json.dumps(payload)), encoding="utf-8")
print(output)
