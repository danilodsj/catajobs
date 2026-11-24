"""Gera dashboard.html (arquivo único, abre direto no navegador) a partir do banco."""
from __future__ import annotations

import json
import os

from .config import RAIZ
from .db import agora, conectar

DESTINO = RAIZ / "dashboard.html"


def _rel(caminho: str | None) -> str | None:
    if not caminho:
        return None
    try:
        return os.path.relpath(caminho, RAIZ).replace("\\", "/")
    except ValueError:
        return None


def gerar() -> str:
    con = conectar()
    linhas = []
    for r in con.execute("SELECT * FROM vagas ORDER BY encontrada_em DESC"):
        linhas.append({
            "id": r["id"], "f": r["fonte"], "t": r["titulo"], "e": r["empresa"], "l": r["local"],
            "m": r["modelo_trabalho"], "u": r["url"], "ua": r["url_aplicacao"], "ap": r["tipo_aplicacao"], "s": r["status"],
            "d": (r["encontrada_em"] or "")[:10], "da": (r["aplicada_em"] or "")[:10], "n": r["nota_fit"],
            "mf": r["motivo_fit"] or r["motivo_regra"], "tr": r["trilha"], "o": r["obs_aplicacao"],
            "cv": _rel(r["cv_pdf"]), "c": r["carta"], "$": round(r["custo_ia_usd"] or 0, 3),
        })
    execs = [dict(r) for r in con.execute("SELECT etapa, inicio, fim, resumo FROM execucoes ORDER BY id DESC LIMIT 20")]
    html = MODELO.replace("__DADOS__", json.dumps(linhas, ensure_ascii=False).replace("</", "<\\/")) \
                 .replace("__EXEC__", json.dumps(execs, ensure_ascii=False).replace("</", "<\\/")) \
                 .replace("__GERADO__", agora().replace("T", " "))
    DESTINO.write_text(html, encoding="utf-8")
    return str(DESTINO)


MODELO = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Catajobs</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#1b1f24;--mut:#5f6b7a;--ln:#e3e7ec;--a:#2f6fdf;--b:#1aa385;--c:#e0892b;--d:#c7473f;--g:#8a94a3;}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--tx:#e8ecf1;--mut:#9aa5b4;--ln:#262c35;--a:#5b8ff0;--b:#2fc39f;--c:#f0a14b;--d:#e0645b;--g:#6b7584;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:16px}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:0 0 12px}.mut{color:var(--mut);font-size:12.5px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.k,.card{background:var(--card);border:1px solid var(--ln);border-radius:10px;padding:14px 16px}
.k .v{font-size:28px;font-weight:650;font-variant-numeric:tabular-nums}.k .l{color:var(--mut);font-size:12.5px}
.k .s{font-size:12px;color:var(--mut);margin-top:2px}
.grid{display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-bottom:16px}@media(max-width:860px){.grid{grid-template-columns:1fr}}
.funil div{display:flex;align-items:center;gap:8px;margin:7px 0}.funil .bar{height:22px;border-radius:5px;background:var(--a);min-width:2px}
.funil .lb{width:120px;font-size:12.5px;color:var(--mut)}.funil .nv{font-variant-numeric:tabular-nums;font-size:12.5px}
.leg{display:flex;gap:14px;font-size:12px;color:var(--mut);margin-bottom:6px}.leg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
svg text{fill:var(--mut);font-size:10.5px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--ln);vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:12px;position:sticky;top:0;background:var(--card);cursor:pointer;white-space:nowrap}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;white-space:nowrap;border:1px solid var(--ln)}
.st-aplicada{background:color-mix(in srgb,var(--b) 18%,transparent);border-color:transparent}
.st-fit,.st-personalizada{background:color-mix(in srgb,var(--a) 16%,transparent);border-color:transparent}
.st-precisa_humano{background:color-mix(in srgb,var(--c) 22%,transparent);border-color:transparent}
.st-falhou,.st-nao_elegivel{background:color-mix(in srgb,var(--d) 18%,transparent);border-color:transparent}
.filtros{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
input,select{background:var(--bg);color:var(--tx);border:1px solid var(--ln);border-radius:7px;padding:7px 9px;font:inherit}
input{flex:1;min-width:180px}a{color:var(--a);text-decoration:none}a:hover{text-decoration:underline}
.tbl{overflow:auto;max-height:70vh}.motivo{color:var(--mut);font-size:12px;max-width:360px}
.acoes{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.acao{border:1px solid var(--ln);border-radius:8px;padding:12px;background:var(--bg)}.acao b{display:block;margin-bottom:2px}
.acao .btns{display:flex;gap:12px;margin-top:8px;font-size:13px;flex-wrap:wrap}.acao .btns a.pri{font-weight:600}
code{font-size:12px;background:var(--bg);padding:1px 5px;border-radius:4px}
details summary{cursor:pointer;color:var(--a);font-size:12px}details p{white-space:pre-wrap;font-size:12.5px;max-width:520px}
</style>
</head>
<body><div class="wrap">
<header><h1>Catajobs</h1><span class="mut">Atualizado em __GERADO__</span></header>
<section class="kpis" id="kpis"></section>
<section class="grid">
  <div class="card"><h2>Por dia (últimos 30 dias)</h2>
    <div class="leg"><span><i style="background:var(--g)"></i>Encontradas (barras, eixo esquerdo)</span><span><i style="background:var(--b);height:3px"></i>Inscritas (linha, eixo direito)</span></div>
    <svg id="dias" width="100%" height="200" role="img" aria-label="Vagas por dia"></svg></div>
  <div class="card"><h2>Funil</h2><div class="funil" id="funil"></div>
    <h2 style="margin-top:18px">Por fonte</h2><table id="fontes"></table></div>
</section>
<section class="card">
  <h2>Vagas</h2>
  <div class="filtros">
    <input id="q" placeholder="Buscar por título, empresa ou motivo">
    <select id="fs"><option value="relevantes">Status: relevantes</option><option value="">Todos</option></select>
    <select id="ff"><option value="">Todas as fontes</option></select>
  </div>
  <div class="tbl"><table id="tab"><thead><tr>
    <th data-k="d">Encontrada</th><th data-k="t">Vaga</th><th data-k="f">Fonte</th><th data-k="n">Fit</th>
    <th data-k="s">Status</th><th>Arquivos</th><th>Detalhes</th></tr></thead><tbody></tbody></table></div>
  <div class="mut" id="cont" style="margin-top:8px"></div>
</section>
<section class="card" id="acoes" style="margin-top:16px;border-color:color-mix(in srgb,var(--c) 55%,var(--ln))">
  <h2>Precisa de você</h2><div class="mut" style="margin-bottom:10px">Vídeo, cadastro, CAPTCHA ou dado que falta. Depois de resolver um dado, rode <code>python -m catajobs reabrir</code>.</div>
  <div id="acoes-lista" class="acoes"></div>
</section>
</div>
<script>
const V=__DADOS__, EX=__EXEC__;
const esc=s=>(s??"").toString().replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
// links só http(s) ou caminho relativo (CV em saida/); bloqueia javascript:, data: etc.
const url=s=>{s=(s??"").toString().trim();return /^https?:\/\//i.test(s)||(s&&!/^[^\/?#]*:/.test(s))?esc(s):"#"};
const ROT={encontrada:"Encontrada",descartada_regra:"Descartada (regra)",triagem:"Em triagem",sem_fit:"Sem fit",fit:"Com fit",personalizada:"CV pronto",aplicada:"Inscrita",precisa_humano:"Precisa de você",falhou:"Falhou",encerrada:"Encerrada",nao_elegivel:"Não elegível",ignorada:"Excluída por você",duplicada:"Duplicada"};
const n=x=>x.toLocaleString("pt-BR"), pct=(a,b)=>b?(100*a/b).toLocaleString("pt-BR",{maximumFractionDigits:1})+"%":"0%";
const hoje=new Date().toISOString().slice(0,10);
const FIT=new Set(["fit","personalizada","aplicada","precisa_humano","falhou","encerrada","nao_elegivel"]);
const TRI=new Set([...FIT,"triagem","sem_fit"]);
const tot=V.length, tri=V.filter(v=>TRI.has(v.s)).length, fit=V.filter(v=>FIT.has(v.s)).length, apl=V.filter(v=>v.s==="aplicada").length;
const hum=V.filter(v=>v.s==="precisa_humano").length, aplHoje=V.filter(v=>v.s==="aplicada"&&v.da===hoje).length, encHoje=V.filter(v=>v.d===hoje).length;
const custo=V.reduce((a,v)=>a+(v["$"]||0),0);
document.getElementById("kpis").innerHTML=[
 ["Vagas encontradas",n(tot),`${n(encHoje)} hoje`],["Passaram nos filtros",n(tri),pct(tri,tot)+" das encontradas"],
 ["Com fit",n(fit),pct(fit,tri)+" das filtradas"],["Inscrições enviadas",n(apl),`${n(aplHoje)} hoje`],
 ["Precisam de você",n(hum),"login, captcha ou cadastro"],["Uso de IA",("US$ "+custo.toLocaleString("pt-BR",{minimumFractionDigits:2,maximumFractionDigits:2})),"equivalente API, sem cobrança (licença Claude)"]
].map(([l,v,s])=>`<div class="k"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
// precisa de você
(function(){
const H=V.filter(v=>v.s==="precisa_humano");const box=document.getElementById("acoes");
if(!H.length){box.style.display="none";return}
document.getElementById("acoes-lista").innerHTML=H.map(v=>`<div class="acao"><b>${esc(v.t)}</b><span class="mut">${esc(v.e)} · ${esc(v.l)}</span>
<p style="margin:8px 0 0;font-size:13px">${esc(v.o)}</p>
<div class="btns"><a class="pri" href="${url(v.ua||v.u)}" target="_blank" rel="noopener">Abrir formulário</a><a href="${url(v.u)}" target="_blank" rel="noopener">Ver vaga</a>${v.cv?`<a href="${url(v.cv)}" target="_blank">CV personalizado</a>`:""}</div>
${v.c?`<details><summary>Carta</summary><p>${esc(v.c)}</p></details>`:""}</div>`).join("")})();
// funil
const F=[["Encontradas",tot],["Filtradas",tri],["Com fit",fit],["CV personalizado",V.filter(v=>["personalizada","aplicada","precisa_humano","falhou"].includes(v.s)).length],["Inscritas",apl]];
document.getElementById("funil").innerHTML=F.map(([l,x])=>`<div><span class="lb">${l}</span><span class="bar" style="width:${tot?Math.max(2,180*x/tot):2}px"></span><span class="nv">${n(x)}</span></div>`).join("");
// fontes
const fs={};V.forEach(v=>{const o=fs[v.f]??={e:0,f:0,a:0};o.e++;if(FIT.has(v.s))o.f++;if(v.s==="aplicada")o.a++;});
document.getElementById("fontes").innerHTML="<tr><th>Fonte</th><th class=num>Encontr.</th><th class=num>Fit</th><th class=num>Inscr.</th></tr>"+Object.entries(fs).sort((a,b)=>b[1].e-a[1].e).map(([k,o])=>`<tr><td>${esc(k)}</td><td class=num>${n(o.e)}</td><td class=num>${n(o.f)}</td><td class=num>${n(o.a)}</td></tr>`).join("");
// por dia
// barras = encontradas (eixo esquerdo); linha = inscritas (eixo direito, escala própria para não sumir perto do zero)
(function(){const svg=document.getElementById("dias"),W=svg.clientWidth||700,H=200,p={l:34,r:30,t:20,b:24};const dias=[];
for(let i=29;i>=0;i--){const d=new Date(Date.now()-i*864e5).toISOString().slice(0,10);dias.push(d)}
const enc=dias.map(d=>V.filter(v=>v.d===d).length), ins=dias.map(d=>V.filter(v=>v.da===d&&v.s==="aplicada").length);
const mxE=Math.max(1,...enc), mxI=Math.max(1,...ins), ah=H-p.t-p.b, bw=(W-p.l-p.r)/dias.length; let g="";
[0,.5,1].forEach(f=>{const y=p.t+ah*(1-f);g+=`<line x1="${p.l}" x2="${W-p.r}" y1="${y}" y2="${y}" stroke="var(--ln)"/><text x="${p.l-4}" y="${y+3}" text-anchor="end">${n(Math.round(mxE*f))}</text><text x="${W-p.r+4}" y="${y+3}" text-anchor="start" style="fill:var(--b)">${Math.round(mxI*f)}</text>`});
enc.forEach((x,i)=>{const h=ah*x/mxE;g+=`<rect x="${p.l+i*bw+bw*.15}" y="${H-p.b-h}" width="${bw*.7}" height="${h}" rx="1.5" fill="var(--g)" opacity=".55"><title>${dias[i]}: ${n(x)} encontradas</title></rect>`});
const pts=ins.map((x,i)=>[p.l+i*bw+bw/2, H-p.b-ah*x/mxI]);
g+=`<polyline points="${pts.map(q=>q.join(",")).join(" ")}" fill="none" stroke="var(--b)" stroke-width="2.25" stroke-linejoin="round"/>`;
pts.forEach(([x,y],i)=>{if(ins[i])g+=`<circle cx="${x}" cy="${y}" r="3.5" fill="var(--b)" stroke="var(--card)" stroke-width="1.5"><title>${dias[i]}: ${ins[i]} inscritas</title></circle><text x="${x}" y="${y-7}" text-anchor="middle" style="fill:var(--b);font-weight:600">${ins[i]}</text>`});
dias.forEach((d,i)=>{if(i%5===4||i===29)g+=`<text x="${p.l+i*bw+bw/2}" y="${H-6}" text-anchor="middle">${d.slice(8)}/${d.slice(5,7)}</text>`});svg.innerHTML=g})();
// tabela
const sel=document.getElementById("fs"),sf=document.getElementById("ff");
Object.entries(ROT).forEach(([k,l])=>sel.insertAdjacentHTML("beforeend",`<option value="${k}">${l}</option>`));
[...new Set(V.map(v=>v.f))].forEach(f=>sf.insertAdjacentHTML("beforeend",`<option>${esc(f)}</option>`));
let ord={k:"d",dir:-1};
function render(){const q=document.getElementById("q").value.toLowerCase(),st=sel.value,fo=sf.value;
 let r=V.filter(v=>(st==="relevantes"?FIT.has(v.s):!st||v.s===st)&&(!fo||v.f===fo)&&(!q||[v.t,v.e,v.mf,v.o].join(" ").toLowerCase().includes(q)));
 r.sort((a,b)=>((a[ord.k]??"")>(b[ord.k]??"")?1:-1)*ord.dir);
 document.querySelector("#tab tbody").innerHTML=r.slice(0,1500).map(v=>`<tr>
  <td>${esc(v.d)}${v.da?`<div class=mut>inscr. ${esc(v.da)}</div>`:""}</td>
  <td><a href="${url(v.u)}" target="_blank" rel="noopener">${esc(v.t)}</a><div class=mut>${esc(v.e)} · ${esc(v.l)}${v.m?" · "+esc(v.m):""}</div></td>
  <td>${esc(v.f)}<div class=mut>${esc(v.ap)}</div></td><td class=num>${esc(v.n)}</td>
  <td><span class="tag st-${esc(v.s)}">${ROT[v.s]||esc(v.s)}</span></td>
  <td>${v.cv?`<a href="${url(v.cv)}" target="_blank">CV</a>`:""}</td>
  <td><div class=motivo>${esc(v.o||v.mf||"")}</div>${v.c?`<details><summary>Carta</summary><p>${esc(v.c)}</p></details>`:""}</td></tr>`).join("");
 document.getElementById("cont").textContent=`${n(r.length)} vagas na lista`}
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{ord={k:th.dataset.k,dir:ord.k===th.dataset.k?-ord.dir:-1};render()});
["q","fs","ff"].forEach(i=>document.getElementById(i).addEventListener("input",render));render();
</script>
</body></html>
"""
