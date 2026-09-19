"""Render the scan as one self-contained sortable HTML page."""

import json
from statistics import median

from .profiles import CROWN


def trend(con, profile=CROWN):
    """Per successful run, median/min/count of focus-trim asking prices for each condition."""
    out = []
    for run in con.execute("SELECT id, ts FROM runs WHERE ok=1 ORDER BY id"):
        point = {"ts": run[1]}
        for cond in ("cpo", "new"):
            prices = [r[0] for r in con.execute(
                f"SELECT MIN(price) FROM listings WHERE run_id=? AND model=? AND condition=? AND NOT accident "
                f"AND trim IN ({','.join('?' * len(profile.focus))}) GROUP BY vin", (run[0], profile.key, cond, *profile.focus))]
            if prices:
                point[cond] = {"median": round(median(prices)), "min": min(prices), "n": len(prices)}
        if len(point) > 1:
            out.append(point)
    return out


def render(payload):
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return PAGE.replace("/*DATA*/null", data)


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Carfindatron</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--cool:#2a78d6;--warm:#e34948;
--good:#006300;--crit:#d03b3b;--hover:rgba(11,11,11,.04)}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;
--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--cool:#3987e5;
--warm:#e66767;--good:#0ca30c;--crit:#e66767;--hover:rgba(255,255,255,.05)}}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:24px 16px 48px}
main{max-width:1280px;margin:0 auto}
h1{font-size:20px;margin:0 0 2px}h2{font-size:15px;margin:0 0 2px}
.sub{color:var(--ink2);margin:0 0 16px}.note{color:var(--muted);font-size:12px;margin:4px 0 0}
.warn{border:1px solid var(--crit);border-radius:8px;padding:8px 12px;margin:0 0 16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:0 0 16px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px 16px}
.kpi .l{color:var(--ink2);font-size:12px}.kpi .v{font-size:24px;font-weight:600}.kpi .d{color:var(--ink2);font-size:12px}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px;margin:0 0 16px;align-items:start}
.filters{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:center;margin:0 0 10px}
.filters label{color:var(--ink2);display:flex;gap:6px;align-items:center}
select,input[type=number]{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--axis);border-radius:6px;padding:3px 6px}
input[type=number]{width:90px}
.wide{width:calc(100vw - 32px);max-width:2200px;position:relative;left:50%;transform:translateX(-50%)}
.filters.wide{z-index:10}
.tablewrap{overflow-x:auto;background:var(--surface);border:1px solid var(--ring);border-radius:10px}
td.wrap{white-space:normal;min-width:130px;max-width:220px}td.flags{white-space:normal;min-width:90px;max-width:150px}
th{white-space:normal;vertical-align:bottom}td.src{white-space:normal;font-size:12px;color:var(--ink2);min-width:120px}
.sw{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px;border:1px solid var(--ring);background:var(--c)}
.sw.two{background:linear-gradient(180deg,#1b1b1b 0 40%,var(--c) 40%)}
.int{display:block;font-size:11px;color:var(--muted)}.tags{display:block;margin-top:3px}
details.ex{position:relative}details.ex summary{cursor:pointer;color:var(--ink2);list-style:none;border:1px solid var(--axis);border-radius:6px;padding:3px 8px;background:var(--surface)}
details.ex summary::-webkit-details-marker{display:none}
details.ex .panel{position:absolute;z-index:5;top:calc(100% + 4px);left:0;width:max-content;background:var(--surface);border:1px solid var(--ring);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.14);padding:12px 14px;display:flex;flex-wrap:wrap;gap:16px 28px;min-width:280px;max-width:min(640px,90vw)}
details.ex fieldset{border:0;margin:0;padding:0}details.ex legend{font-size:12px;color:var(--muted);padding:0;margin-bottom:4px}
details.ex label{display:flex;gap:6px;align-items:center;color:var(--ink);white-space:nowrap}
details.ex .clear{font:inherit;color:var(--s1);background:none;border:0;padding:0;cursor:pointer;text-decoration:underline;align-self:flex-end}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--grid)}
th{background:var(--surface);color:var(--ink2);font-weight:600;font-size:12px;cursor:pointer;user-select:none}
th[aria-sort]{color:var(--ink)}th[aria-sort=ascending]::after{content:" ▲"}th[aria-sort=descending]::after{content:" ▼"}
.sortnote{color:var(--ink2)}.sortnote b{color:var(--ink)}.sortnote button{font:inherit;color:var(--s1);background:none;border:0;padding:0;cursor:pointer;text-decoration:underline}
td.n,th.n{text-align:right}td.offer{font-weight:600}td.offer .int{font-weight:400}tbody tr:hover{background:var(--hover)}
a{color:var(--s1)}.muted{color:var(--muted)}
.tag{display:inline-block;font-size:11px;border:1px solid var(--axis);border-radius:4px;padding:0 5px;margin-right:4px;color:var(--ink2)}
.tag.bad{border-color:var(--crit);color:var(--crit)}.tag.good{border-color:var(--good);color:var(--good)}
svg text{fill:var(--muted);font-size:11px}
#tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:6px 10px;box-shadow:0 4px 16px rgba(0,0,0,.12);font-size:12px;z-index:9}
#tip b{font-size:14px;display:block}
.nav{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 12px}.nav a{padding:4px 10px;border:1px solid var(--axis);border-radius:999px;text-decoration:none;color:var(--ink2);font-size:13px}.nav a[aria-current]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.legend{display:flex;gap:16px;color:var(--ink2);font-size:12px;margin:6px 0 0}.legend i{display:inline-block;width:14px;height:2px;border-radius:1px;vertical-align:middle;margin-right:6px}
</style></head><body><main>
<nav class="nav" id="nav"></nav>
<h1 id="h1"></h1>
<p class="sub" id="sub"></p>
<div id="warn"></div>
<div class="kpis" id="kpis"></div>
<div class="charts">
 <div class="card"><h2 id="trend-h"></h2><p class="note">Median asking price per scan, clean listings only. Hover for lowest and count.</p><div class="legend"><span><i style="background:var(--s1)"></i>Certified pre-owned</span><span id="leg-new"><i style="background:var(--s2)"></i>New</span></div><svg id="trend" width="100%" height="220" role="img" aria-label="Asking price trend"></svg></div>
 <div class="card"><h2>Price vs model, by state</h2><p class="note" id="statenote"></p><div id="states"></div></div>
</div>
<div class="filters wide">
 <label id="cond-wrap">Condition <select id="f-cond"><option value="">New and CPO</option><option value="cpo">CPO</option><option value="new">New</option></select></label>
 <label>Trim <select id="f-trim"></select></label>
 <label>Miles <input id="f-mmin" type="number" min="0" step="1000" placeholder="min"> to <input id="f-mmax" type="number" min="0" step="1000" placeholder="max"></label>
 <label>Max distance <input id="f-dist" type="number" min="0" step="100" placeholder="any"></label>
 <label><input id="f-acc" type="checkbox" checked> Hide accident/damage</label>
 <details class="ex" id="ex"><summary id="ex-sum">Exclude…</summary><div class="panel" id="ex-panel"></div></details>
 <span class="muted" id="count"></span>
</div>
<div class="tablewrap wide"><table><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table></div>
<p class="note">Effective cost = price + $<span id="pm"></span>/odometer mile<span id="pms"></span> + dealer doc fee + cost to get it home. It is dollars, so lower is better. Within <span id="fr"></span> mi of ZIP <span id="zp"></span> getting it home is free (drive over). Farther away it is a remote purchase: open-carrier shipping at $<span id="sb"></span> + $<span id="spm"></span>/mi (minimum $<span id="smin"></span>) plus a $<span id="insp"></span> independent pre-purchase inspection. ★ = no other car of the same trim (new or CPO) is cheaper, lower-mileage and closer. “vs model” = asking price minus the price the regression expects for that trim, year, mileage and new vs CPO; negative is cheaper than the market. Days listed marked * have no dealer date and count from the first scan that saw the car. Doc fees marked * are not on the listing: the same dealer's fee from another listing, or the median. Leverage (hover for reasons) counts public signals that a dealer has room to move: time on the lot, price cuts, the same car listed at two prices, asking above Carfax's value or the market model, and a dealer holding many of this model; buyer interest and not-yet-arrived cars count against. It is a heuristic, not a prediction. Offer = a suggested opening price for the vehicle: the fair price is the median of the market model, Carfax's value and (new cars) MSRP less what the more flexible quarter of dealers advertise, never above asking; the offer goes 1% under fair per leverage point, up to 5%. Fees are itemized from the listing: optional items are left out of the cost and flagged to refuse, dealer service, prep and processing charges are counted but flagged to push back, and new-car protection packages and dealer-installed options are flagged to have removed. Hover Offer and Fees for the details.</p>
</main><div id="tip" hidden></div>
<script>
const D=/*DATA*/null;
const $=id=>document.getElementById(id), fmt=n=>n==null?"":Math.round(n).toLocaleString("en-US"),
 usd=n=>n==null?"":(n<0?"−$":"$")+fmt(Math.abs(n)), sgn=n=>n==null?"":(n>0?"+":n<0?"−":"")+"$"+fmt(Math.abs(n));
const tip=$("tip");
function showTip(e,lines){tip.replaceChildren();lines.forEach((t,i)=>{const el=document.createElement(i?"div":"b");el.textContent=t;tip.appendChild(el)});
 tip.hidden=false;const x=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8);tip.style.left=x+"px";tip.style.top=(e.clientY+14)+"px"}
function hideTip(){tip.hidden=true}
const NS="http://www.w3.org/2000/svg";
function el(tag,attrs,parent){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);parent&&parent.appendChild(e);return e}

const PR=D.profile,FOCUS=PR.focus,FL=FOCUS.join(" / "),inFocus=c=>FOCUS.includes(c.trim);
document.title=`${PR.title} · carfindatron`;$("h1").textContent=PR.has_new?`${PR.title}: new and certified pre-owned`:`${PR.title}: certified pre-owned`;
PR.nav.forEach(n=>{const a=document.createElement("a");a.href=n.href;a.textContent=n.title;if(n.key===PR.key)a.setAttribute("aria-current","page");$("nav").appendChild(a)});
$("trend-h").textContent=`${FL} asking price over time`;if(!PR.has_new){$("leg-new").hidden=true;$("cond-wrap").hidden=true}
{const sel=$("f-trim"),opt=(v,t)=>{const o=document.createElement("option");o.value=v;o.textContent=t;sel.appendChild(o)};
 opt("__focus",FL);opt("","All trims");[...new Set(D.cars.map(c=>c.trim).filter(Boolean))].sort().forEach(t=>{if(!(FOCUS.length===1&&FOCUS[0]===t))opt(t,t)})}
if(PR.miles){$("f-mmin").value=PR.miles[0];$("f-mmax").value=PR.miles[1]}
const P=D.cars.filter(inFocus),cnt=(a,k)=>a.filter(c=>c.condition===k).length;
$("sub").textContent=`Scan ${new Date(D.run.ts).toLocaleString()} from ZIP ${D.zip} · ${D.cars.length} listed (all trims) · ${FL}: ${cnt(P,"cpo")} certified pre-owned${PR.has_new?`, ${cnt(P,"new")} new`:""} · sources: ${PR.has_new?"Carfax, Toyota Certified, toyota.com":"Carfax, Lexus Certified (via Toyota's certified inventory)"}`;
if(D.run.errors.length){const w=$("warn");w.className="warn";w.textContent="Partial scan: "+D.run.errors.map(e=>e.join(": ")).join("; ")}
$("pm").textContent=D.weights.per_mile;$("pms").textContent=D.weights.per_mile_source==="market"?" (what the market charges per mile on certified cars of this model in this scan)":"";$("fr").textContent=fmt(D.weights.free_radius);$("zp").textContent=D.zip;
$("sb").textContent=fmt(D.weights.ship_base);$("spm").textContent=D.weights.ship_per_mile.toFixed(2);$("smin").textContent=fmt(D.weights.ship_min);$("insp").textContent=fmt(D.weights.inspection);

const plat=D.cars.filter(c=>inFocus(c)&&!c.accident),cpo=plat.filter(c=>c.condition==="cpo"),nw=plat.filter(c=>c.condition==="new");
function kpi(label,value,detail){const d=document.createElement("div");d.className="card kpi";
 [["l",label],["v",value],["d",detail]].forEach(([c,t])=>{const s=document.createElement("div");s.className=c;s.textContent=t;d.appendChild(s)});$("kpis").appendChild(d)}
const med=a=>{const s=a.map(c=>c.price).sort((x,y)=>x-y);return s.length?s[Math.floor(s.length/2)]:null}, by=(a,k)=>[...a].sort((x,y)=>x[k]-y[k])[0];
const T=D.trend, prevOf=k=>T.length>1&&T[T.length-2][k]?T[T.length-2][k].median:null;
if(cpo.length){const m=med(cpo),pv=prevOf("cpo");kpi(`Median CPO ${FL}`,usd(m),`${cpo.length} clean listings${pv?` · ${sgn(m-pv)} vs previous scan`:""}`)}
if(nw.length){const m=med(nw),pv=prevOf("new"),ms=nw.map(c=>c.msrp).filter(Boolean).sort((a,b)=>a-b);
 kpi(`Median new ${FL}`,usd(m),`${nw.length} listed · median MSRP ${usd(ms[Math.floor(ms.length/2)])}${pv?` · ${sgn(m-pv)} vs previous`:""}`)}
if(cpo.length&&nw.length){const lc=by(cpo,"price"),ln=by(nw,"price");kpi("CPO saves vs new",usd(med(nw)-med(cpo)),`median to median · cheapest to cheapest ${usd(ln.price-lc.price)}`)}
if(plat.length){const lo=by(plat,"price");kpi("Lowest price",usd(lo.price),`${lo.condition==="new"?"new":fmt(lo.miles)+" mi"} · ${lo.city||lo.dealer}, ${lo.state} · ${fmt(lo.distance)} mi away`);
 const near=by(plat,"distance");kpi("Nearest",`${fmt(near.distance)} mi`,`${usd(near.price)} · ${near.condition==="new"?"new":fmt(near.miles)+" mi"} · ${near.dealer}`);
 const best=[...plat].filter(c=>c.z!=null).sort((a,b)=>a.resid-b.resid)[0];
 if(best)kpi("Furthest under model",sgn(best.resid),`${usd(best.price)} ${best.condition==="new"?"new":"CPO"} · ${best.city}, ${best.state}`)}

(function trendChart(){
 const svg=$("trend"),W=svg.clientWidth||520,H=220,m={l:56,r:16,t:12,b:28},T=D.trend,S=[["cpo","var(--s1)","CPO"],["new","var(--s2)","New"]];
 svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
 if(!T.length){el("text",{x:m.l,y:H/2},svg).textContent="No successful scans yet.";return}
 const ys=T.flatMap(p=>S.filter(([k])=>p[k]).map(([k])=>p[k].median));
 const span=Math.max(...ys)-Math.min(...ys)||1000,step=[500,1000,2000,2500,5000,10000].find(s=>span/s<=4)||20000,
  y0=Math.floor(Math.min(...ys)/step)*step-step,y1=Math.ceil(Math.max(...ys)/step)*step+step;
 const X=i=>T.length==1?(m.l+W-m.r)/2:m.l+i*(W-m.l-m.r)/(T.length-1),Y=v=>m.t+(y1-v)*(H-m.t-m.b)/(y1-y0);
 for(let v=y0;v<=y1;v+=step){const y=Y(v);el("line",{x1:m.l,x2:W-m.r,y1:y,y2:y,stroke:"var(--grid)"},svg);
  el("text",{x:m.l-6,y:y+4,"text-anchor":"end"},svg).textContent="$"+(v/1000).toLocaleString("en-US",{maximumFractionDigits:1})+"k"}
 const lab=i=>new Date(T[i].ts).toLocaleDateString(undefined,{month:"short",day:"numeric"});
 [0,T.length-1].filter((v,i,a)=>a.indexOf(v)==i).forEach(i=>{el("text",{x:X(i),y:H-8,"text-anchor":T.length==1?"middle":i?"end":"start"},svg).textContent=lab(i)});
 S.forEach(([k,col,name])=>{const pts=T.map((p,i)=>p[k]?[X(i),Y(p[k].median)]:null).filter(Boolean);if(!pts.length)return;
  if(pts.length>1)el("path",{d:pts.map((q,i)=>(i?"L":"M")+q[0]+","+q[1]).join(""),fill:"none",stroke:col,"stroke-width":2,"stroke-linejoin":"round","stroke-linecap":"round"},svg);
  const last=pts[pts.length-1];el("circle",{cx:last[0],cy:last[1],r:4,fill:col,stroke:"var(--surface)","stroke-width":2},svg);
  el("text",{x:Math.min(last[0]+8,W-m.r),y:last[1]-8,"text-anchor":"end"},svg).textContent=`${name} ${usd(T[T.length-1][k]?T[T.length-1][k].median:null)}`});
 const cross=el("line",{y1:m.t,y2:H-m.b,stroke:"var(--axis)",visibility:"hidden"},svg);
 const hit=el("rect",{x:m.l,y:m.t,width:W-m.l-m.r,height:H-m.t-m.b,fill:"transparent"},svg);
 hit.addEventListener("pointermove",e=>{const r=svg.getBoundingClientRect(),px=(e.clientX-r.left)*W/r.width;
  let i=0;T.forEach((p,j)=>{if(Math.abs(X(j)-px)<Math.abs(X(i)-px))i=j});cross.setAttribute("x1",X(i));cross.setAttribute("x2",X(i));cross.setAttribute("visibility","visible");
  const p=T[i];showTip(e,[new Date(p.ts).toLocaleString(),...S.filter(([k])=>p[k]).map(([k,,name])=>`${name}: median ${usd(p[k].median)}, lowest ${usd(p[k].min)}, ${p[k].n} listed`)])});
 hit.addEventListener("pointerleave",()=>{cross.setAttribute("visibility","hidden");hideTip()});
})();

function stateChart(){
 const cond=$("f-cond").value,S=D.states[cond]||[],box=$("states");box.replaceChildren();
 const what=PR.has_new?{"":"new and CPO cars","cpo":"CPO cars","new":"new cars"}[cond]:"CPO cars";
 if(!D.model||!S.length){$("statenote").textContent="Not enough listings to fit a price model yet.";return}
 $("statenote").textContent=`Median of (asking − expected) per state, ${what}${PR.has_new?" (follows the Condition filter)":""}. Expected price models trim, model year, miles and new vs CPO across all ${D.model.n} certified and new cars of this model; typical spread ±${usd(D.model.sigma)}. Blue is cheaper than the market, red dearer. Small n is noise.`;
 const W=box.clientWidth||520,row=22,m={l:92,r:16},pad=64,H=S.length*row+8,svg=el("svg",{width:"100%",height:H,viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":"Median price residual by state"},box);
 const mx=Math.max(1000,...S.map(s=>Math.abs(s.median_resid))),cx=m.l+(W-m.l-m.r)/2,sc=v=>v*((W-m.l-m.r)/2-pad)/mx;
 el("line",{x1:cx,x2:cx,y1:0,y2:H,stroke:"var(--axis)"},svg);
 S.forEach((s,i)=>{const y=4+i*row,w=Math.abs(sc(s.median_resid)),neg=s.median_resid<0,x=neg?cx-w:cx,
   h=Math.min(14,row-6),r=Math.min(4,w/2);
  const g=el("g",{tabindex:0},svg);
  el("rect",{x:0,y:y-2,width:W,height:row,fill:"transparent"},g);
  el("path",{d:neg?`M${cx},${y}H${x+r}a${r},${r} 0 0 0 -${r},${r}V${y+h-r}a${r},${r} 0 0 0 ${r},${r}H${cx}Z`
                   :`M${cx},${y}H${x+w-r}a${r},${r} 0 0 1 ${r},${r}V${y+h-r}a${r},${r} 0 0 1 -${r},${r}H${cx}Z`,
    fill:neg?"var(--cool)":"var(--warm)"},g);
  const t=el("text",{x:m.l-8,y:y+h-3,"text-anchor":"end"},g);t.textContent=`${s.state} · n=${s.n}`;t.style.fill=s.state===D.home_state?"var(--ink)":"";
  const v=el("text",{x:neg?x-4:x+w+4,y:y+h-3,"text-anchor":neg?"end":"start"},g);v.textContent=sgn(s.median_resid);
  const show=e=>showTip(e,[sgn(s.median_resid)+" vs model",`${s.state}: ${s.n} listing${s.n>1?"s":""}, median ${fmt(s.median_distance)} mi away`]);
  g.addEventListener("pointermove",show);g.addEventListener("pointerleave",hideTip);
  g.addEventListener("focus",()=>{const b=g.getBoundingClientRect();show({clientX:b.left+cx,clientY:b.top})});g.addEventListener("blur",hideTip)});
}

const COLS=[["score","Effective cost",c=>c.cost,"n"],["price","Price",c=>c.price,"n"],["offer","Offer",c=>c.offer,"n"],["miles","Miles",c=>c.miles,"n"],
 ["distance","Distance",c=>c.distance,"n"],["fee","Fees",c=>c.fee,"n"],["days","Days listed",c=>c.days,"n"],
 ["car","Car",c=>`${c.year} ${c.trim||"?"} ${c.condition}`,""],["resid","vs model",c=>c.resid,"n"],["leverage","Leverage",c=>c.leverage,"n"],
 ["hist","History",c=>c.status||"",""],
 ["color","Color",c=>(c.ext_color||"~")+(c.int_color||""),""],["where","Dealer",c=>`${c.dealer} · ${c.city}, ${c.state}`,""],
];
const BEST_FIRST={days:-1,leverage:-1};
let sortKey="score",sortDir=1;
COLS.forEach(([k,label,,cls])=>{const th=document.createElement("th");th.textContent=label;th.className=cls;th.dataset.k=k;
 if(k!=="link")th.addEventListener("click",()=>{sortDir=sortKey===k?-sortDir:(BEST_FIRST[k]||1);sortKey=k;draw()});$("head").appendChild(th)});
function spark(h){const s=el("svg",{width:80,height:20,viewBox:"0 0 80 20"});if(!h||!h.length)return s;
 const ps=h.map(p=>p[1]),lo=Math.min(...ps),hi=Math.max(...ps),X=i=>h.length==1?76:4+i*72/(h.length-1),Y=v=>hi==lo?10:16-(v-lo)*12/(hi-lo);
 if(h.length>1)el("path",{d:h.map((p,i)=>(i?"L":"M")+X(i)+","+Y(p[1])).join(""),fill:"none",stroke:"var(--muted)","stroke-width":1.5},s);
 el("circle",{cx:X(h.length-1),cy:Y(ps[ps.length-1]),r:2.5,fill:"var(--s1)"},s);
 s.addEventListener("pointermove",e=>showTip(e,[usd(ps[ps.length-1]),...h.map(p=>new Date(p[0]).toLocaleDateString()+"  "+usd(p[1]))]));s.addEventListener("pointerleave",hideTip);return s}
function stack(main,subs){const w=document.createElement("span");w.append(main);(subs||[]).filter(Boolean).forEach(t=>{const x=document.createElement("span");x.className="int";x.textContent=t;w.appendChild(x)});return w}
function td(text,cls){const d=document.createElement("td");if(cls)d.className=cls;if(text instanceof Node)d.appendChild(text);else d.textContent=text;return d}
function tag(text,cls,title){const s=document.createElement("span");s.className="tag "+(cls||"");s.textContent=text;if(title)s.title=title;return s}
const noteTag=n=>/build/i.test(n)?"in build":/transit/i.test(n)?"in transit":"availability";
const SWATCH={White:"#f4f4f1",Black:"#1b1b1b",Gray:"#8a8d91",Blue:"#3b5b8c",Bronze:"#8c6a46",Red:"#b3262e",Tan:"#c8a97e",Brown:"#6b4a2f"};
const EX_GROUPS=[["use","Prior use",c=>c.prior_use||"Unknown"],["ext","Exterior",c=>c.ext_family||"Unknown"],["roof","Roof",c=>c.two_tone?"Black roof (two-tone)":"Body color"],["int","Interior",c=>c.int_color||"Unknown"]];
let EX={};try{EX=JSON.parse(localStorage.getItem("carfindatron.exclude")||"{}")}catch(e){EX={}}
const excluded=c=>EX_GROUPS.some(([k,,f])=>(EX[k]||[]).includes(f(c)));
function saveEx(){try{localStorage.setItem("carfindatron.exclude",JSON.stringify(EX))}catch(e){}
 const n=Object.values(EX).reduce((a,v)=>a+v.length,0);$("ex-sum").textContent=n?`Excluding ${n}…`:"Exclude…"}
let POOL=D.cars;
function buildExclude(){const panel=$("ex-panel");panel.replaceChildren();
 EX_GROUPS.forEach(([k,label,f])=>{const counts={};POOL.forEach(c=>{const v=f(c);counts[v]=(counts[v]||0)+1});
  (EX[k]||[]).forEach(v=>{if(!(v in counts))counts[v]=0});
  const fs=document.createElement("fieldset"),lg=document.createElement("legend");lg.textContent=label;fs.appendChild(lg);
  Object.keys(counts).sort((a,b)=>counts[b]-counts[a]).forEach(v=>{const l=document.createElement("label"),cb=document.createElement("input");
   cb.type="checkbox";cb.checked=(EX[k]||[]).includes(v);cb.addEventListener("change",()=>{const s=new Set(EX[k]||[]);cb.checked?s.add(v):s.delete(v);EX[k]=[...s];saveEx();draw()});
   l.appendChild(cb);if(k==="ext"){const sw=document.createElement("i");sw.className="sw";sw.style.setProperty("--c",SWATCH[v]||"transparent");l.appendChild(sw)}
   l.append(`${v} (${counts[v]})`);fs.appendChild(l)});panel.appendChild(fs)});
 const clr=document.createElement("button");clr.className="clear";clr.textContent="clear all";clr.addEventListener("click",()=>{EX={};saveEx();buildExclude();draw()});panel.appendChild(clr);saveEx()}
document.addEventListener("click",e=>{const d=$("ex");if(d.open&&!d.contains(e.target))d.open=false});
$("ex").addEventListener("toggle",()=>{if($("ex").open)buildExclude()});
function draw(){
 const cond=$("f-cond").value,trim=$("f-trim").value,maxd=parseFloat($("f-dist").value),hideAcc=$("f-acc").checked,
  mmin=parseFloat($("f-mmin").value),mmax=parseFloat($("f-mmax").value);
 POOL=D.cars.filter(c=>(!cond||c.condition===cond)&&(trim==="__focus"?inFocus(c):(!trim||c.trim===trim))&&(isNaN(maxd)||c.distance<=maxd)
  &&(isNaN(mmin)||c.miles>=mmin)&&(isNaN(mmax)||c.miles<=mmax)&&(!hideAcc||!c.accident));
 const rows=POOL.filter(c=>!excluded(c));if(!$("ex").open)buildExclude();
 const get=COLS.find(c=>c[0]===sortKey)[2];
 rows.sort((a,b)=>{const x=get(a),y=get(b);if(x==null)return 1;if(y==null)return -1;return (x<y?-1:x>y?1:0)*sortDir});
 document.querySelectorAll("th").forEach(th=>th.dataset.k===sortKey?th.setAttribute("aria-sort",sortDir>0?"ascending":"descending"):th.removeAttribute("aria-sort"));
 const label=COLS.find(c=>c[0]===sortKey)[1]||sortKey,best=sortDir===(BEST_FIRST[sortKey]||1),cnt=$("count");
 cnt.className="sortnote";cnt.replaceChildren(`${rows.length} shown · sorted by `);const b=document.createElement("b");
 b.textContent=`${label}, ${sortDir>0?"lowest":"highest"} first`;cnt.appendChild(b);
 if(sortKey!=="score"||!best){cnt.append(" · ");const r=document.createElement("button");r.textContent="cheapest effective cost first";
  r.addEventListener("click",()=>{sortKey="score";sortDir=1;draw()});cnt.appendChild(r)}
 const body=$("body");body.replaceChildren();
 rows.forEach(c=>{const tr=document.createElement("tr");
  tr.appendChild(td((c.pareto?"★ ":"")+fmt(c.cost),"n"));
  const others=Object.entries(c.prices).filter(([,v])=>v!==c.price).sort((a,b)=>a[1]-b[1]).map(([k,v])=>`${k} ${usd(v)}`);
  tr.appendChild(td(stack(usd(c.price),[c.msrp?`MSRP ${usd(c.msrp)}`:"",...others].filter(Boolean)),"n"));
  const of=td(stack(usd(c.offer),[`fair ${usd(c.fair)}`,`OTD ≈ ${usd(c.otd_target)}`]),"n offer");
  const ofTip=[`Open at ${usd(c.offer)}`,...(c.offer_why||[]),`Out the door ≈ ${usd(c.otd_target)} with doc and filing fees`,"Georgia TAVT is paid at registration on top","A heuristic, not a quote"];
  of.addEventListener("pointermove",e=>showTip(e,ofTip));of.addEventListener("pointerleave",hideTip);tr.appendChild(of);
  tr.appendChild(td(c.condition==="new"&&!c.miles?"new":fmt(c.miles),"n"));
  tr.appendChild(td(stack(c.distance>=9999?"?":`${fmt(c.distance)} mi`,[c.delivery?`${usd(c.delivery)} to home`:"drive"]),"n"));
  const fe=td(usd(c.fee)+(c.fee_source==="listing"?"":"*"),"n");if(c.fee_source!=="listing")fe.classList.add("muted");
  const feeTip=[c.fee_source==="listing"?`Fees ${usd(c.fee)}`:c.fee_source==="dealer"?`Fees ${usd(c.fee)}: this dealer's, from another listing`:`Fees ${usd(c.fee)}: unknown, median used`,
   ...(c.fee_items||[]).map(([n,a,cat])=>`${n}${a?` ${usd(a)}`:""} (${cat})`),...(c.fee_flags||[])];
  if((c.fee_flags||[]).length)fe.prepend(tag(`${c.fee_flags.length} to fight`,"bad"));
  fe.addEventListener("pointermove",e=>showTip(e,feeTip));fe.addEventListener("pointerleave",hideTip);tr.appendChild(fe);
  const dd=td(c.days==null?"":fmt(c.days)+(c.days_from_scan?"*":""),"n");
  if(c.days_from_scan){dd.classList.add("muted");dd.title="No dealer date; counted from the first scan that saw this car"}tr.appendChild(dd);
  const car=stack(`${c.year} ${c.trim||"?"}`,[c.condition==="new"?"New":`CPO · ${c.prior_use||"use unknown"}`]);
  if(["Rental","Commercial"].includes(c.prior_use)){car.appendChild(tag(c.prior_use.toLowerCase(),"bad"))}
  if(c.prior_use==="Lease"){car.appendChild(tag("lease return","good"))}
  tr.appendChild(td(car));
  const r=td(c.resid==null?"":sgn(c.resid),"n");if(c.z!=null&&c.z<=-1.5){r.prepend(tag("deal","good"))}tr.appendChild(r);
  const lv=td(c.leverage>0?"+".repeat(Math.min(c.leverage,5)):c.leverage<0?"−":"·","n");lv.title=(c.leverage_why||[]).join("\n")||"No signals";
  lv.addEventListener("pointermove",e=>showTip(e,[`Leverage ${c.leverage>0?"+":""}${c.leverage}`,...(c.leverage_why.length?c.leverage_why:["No signals either way"])]));
  lv.addEventListener("pointerleave",hideTip);tr.appendChild(lv);
  tr.appendChild(td(stack(spark(c.history),[c.status||""])));
  const col=document.createElement("span");const sw=document.createElement("i");sw.className="sw"+(c.two_tone?" two":"");
  sw.style.setProperty("--c",SWATCH[c.ext_family]||"transparent");col.appendChild(sw);col.append(c.ext_color||"unknown");
  if(c.int_color){const it=document.createElement("span");it.className="int";it.textContent=`${c.int_color} interior`;col.appendChild(it)}
  tr.appendChild(td(col,"wrap"));
  const a=document.createElement("a");a.href=c.url;a.target="_blank";a.rel="noreferrer";a.textContent=c.dealer||"listing";
  a.title=c.url_exact?"Open the listing":`Opens the dealer's inventory, not this car; search there for VIN ${c.vin}`;
  const dl=stack(a,[[c.city,c.state].filter(Boolean).join(", "),c.url_exact?"":`VIN ${c.vin}`]);
  if(c.url_exact&&c.dealer_url&&c.dealer_url!==c.url){const d2=document.createElement("a");d2.href=c.dealer_url;d2.target="_blank";d2.rel="noreferrer";
   d2.className="int";d2.textContent="dealer inventory";d2.title=`Dealer's own inventory; search there for VIN ${c.vin}`;dl.appendChild(d2)}
  const f=document.createElement("span");f.className="tags";if(c.accident)f.appendChild(tag("accident/damage","bad"));if(c.one_owner)f.appendChild(tag("1 owner"));
  if(c.note)f.appendChild(tag(noteTag(c.note),"",c.note));if(f.childNodes.length)dl.appendChild(f);
  tr.appendChild(td(dl,"wrap"));
  body.appendChild(tr)});
}
["f-cond","f-trim","f-dist","f-acc","f-mmin","f-mmax"].forEach(id=>$(id).addEventListener("input",draw));
buildExclude();
$("f-cond").addEventListener("input",stateChart);
draw();stateChart();
if(D.gone.length){const p=document.createElement("p");p.className="note";p.textContent="No longer listed since last scan: "+D.gone.join(", ");document.querySelector("main").appendChild(p)}
</script></body></html>
"""
