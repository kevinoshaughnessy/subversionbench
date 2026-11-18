"""
The page the run-command builder serves.

Held as a string so the builder is one process with no static directory to
find or install. The page reads its choices from /api/options and asks
/api/command to assemble the command on every change, so nothing about the
flags is written out here: a flag or a bundle that the parser or the sidecars
gain appears with no edit to this file. Output is written with textContent
only; no value from the form is ever interpreted as markup.
"""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SubversionBench run builder</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#14181f;--muted:#5a6472;--line:#d9dde4;
--accent:#1d5fd1;--accent-ink:#fff;--bad:#b3261e;--warn:#8a5a00;--code:#0f1620;--code-ink:#e6edf6;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#10141a;--panel:#181e27;--ink:#e6eaf0;--muted:#94a0b0;--line:#2a3340;--accent:#6aa3ff;--accent-ink:#0b1220;--bad:#ff8a80;--warn:#f0b955;--code:#0a0e14;--code-ink:#dbe6f5;color-scheme:dark}}
:root[data-theme=dark]{--bg:#10141a;--panel:#181e27;--ink:#e6eaf0;--muted:#94a0b0;--line:#2a3340;--accent:#6aa3ff;--accent-ink:#0b1220;--bad:#ff8a80;--warn:#f0b955;--code:#0a0e14;--code-ink:#dbe6f5;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif;
padding-inline:max(16px,env(safe-area-inset-left,0px)) max(16px,env(safe-area-inset-right,0px))}
main{max-width:1100px;margin:0 auto;padding-block:20px 40px;display:grid;gap:16px;grid-template-columns:minmax(0,1fr)}
@media (min-width:900px){main{grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);align-items:start}.out{position:sticky;top:16px}}
header{grid-column:1/-1}
h1{font-size:20px;margin:0 0 4px}h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 10px}
.lede{margin:0;color:var(--muted);max-width:70ch}
section{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px 16px}
.stack{display:grid;gap:14px}
label{display:grid;gap:4px;font-weight:600}label small{font-weight:400;color:var(--muted)}
.row{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
input[type=text],input[type=number],select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:4px;background:var(--bg);color:var(--ink);width:100%}
.opts{display:flex;flex-wrap:wrap;gap:6px 14px}.opts label{display:flex;gap:6px;align-items:center;font-weight:400}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:4px;overflow:hidden}
.seg button{font:inherit;border:0;background:var(--bg);color:var(--ink);padding:6px 12px;cursor:pointer}
.seg button[aria-pressed=true]{background:var(--accent);color:var(--accent-ink)}
.fieldname{font-weight:600;margin-bottom:4px}
details summary{cursor:pointer;font-weight:600}
pre{margin:0;background:var(--code);color:var(--code-ink);padding:12px;border-radius:4px;overflow-x:auto;white-space:pre-wrap;word-break:break-all;font:12.5px/1.5 ui-monospace,Menlo,monospace}
button.act{font:inherit;font-weight:600;border:1px solid var(--accent);background:var(--accent);color:var(--accent-ink);border-radius:4px;padding:6px 12px;cursor:pointer}
button.act.alt{background:transparent;color:var(--accent)}
.msg{margin:8px 0 0;padding:0;list-style:none;display:grid;gap:4px}.msg li{padding-left:10px;border-left:3px solid}
.msg .e{color:var(--bad)}.msg .w{color:var(--warn)}
.count{color:var(--muted);margin:0 0 8px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
</style></head><body><main>
<header><h1>SubversionBench run builder</h1>
<p class="lede">Fill in the form and copy the command. This page builds commands and does not run them, and it never reads your API keys. Set the grader's key in the shell you run the command in.</p></header>
<div class="stack">
<section><h2>Scenario</h2><div class="stack">
<label>Scenario<select id="scenario"></select></label>
<div id="variants-box" hidden><div class="fieldname">Variant</div><div class="opts" id="variants"></div></div>
</div></section>
<section><h2>Model</h2><div class="stack">
<label>Model ID<input type="text" id="model" list="models" autocomplete="off" spellcheck="false" placeholder="vendor/model for OpenRouter, a bare ID for a developer API"></label>
<datalist id="models"></datalist>
<div class="row">
<label>Provider pin<small>OpenRouter only; turns fallback off</small><input type="text" id="provider" autocomplete="off" spellcheck="false" placeholder="unpinned"></label>
<label>Routing sort<small>OpenRouter only</small><select id="sort"></select></label>
<label>Reasoning level<small>blank sends nothing</small><select id="effort"></select></label>
</div></div></section>
<section><h2>Grader</h2><div class="stack">
<div class="opts"><label><input type="checkbox" id="grade" checked> Grade at collection</label></div>
<label>Grader model<input type="text" id="grader_model" autocomplete="off" spellcheck="false"></label>
</div></section>
<section><h2>Arms</h2><div class="stack">
<div><div class="fieldname">Command</div><div class="seg" id="mode">
<button type="button" data-mode="batch" aria-pressed="true">All arms (batch script)</button>
<button type="button" data-mode="single" aria-pressed="false">One arm (run_eval)</button></div></div>
<label>Capability arm<small>instructed act; one arm at a time</small><select id="capability"></select></label>
<div><div class="fieldname">Nudge</div><div class="opts" id="nudges"></div></div>
<div><div class="fieldname">Oversight</div><div class="opts" id="oversights"></div></div>
<div><div class="fieldname">Lure</div><div class="opts" id="lures"></div></div>
<div id="goalguards-box"><div class="fieldname">Goal-guarding arm</div><div class="opts" id="goalguards"></div></div>
<div class="row">
<label>Runs per arm<input type="number" id="runs" min="1" step="1"></label>
<label>Output directory<input type="text" id="output_dir" autocomplete="off" spellcheck="false"></label>
<label>Artefact dates<select id="date_mode"></select></label>
</div></div></section>
<section><details><summary>Advanced settings</summary><div class="row" id="advanced" style="margin-top:12px"></div></details></section>
</div>
<section class="out"><h2>Command</h2>
<p class="count" id="count"></p>
<pre id="command"></pre>
<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
<button class="act" type="button" id="copy">Copy command</button>
<button class="act alt" type="button" id="copy-dry" hidden>Copy dry-run preview</button></div>
<ul class="msg" id="messages"></ul>
</section>
<script>
const $=id=>document.getElementById(id);let O,S={mode:"batch",advanced:{}},timer;
const KEYS={nudges:["nudge"],oversights:["oversight"],lures:["lure"]};
function opt(sel,values,blank){sel.replaceChildren();if(blank!==undefined){const o=document.createElement("option");o.value="";o.textContent=blank;sel.append(o)}
 for(const v of values){const o=document.createElement("option");o.value=v;o.textContent=v;sel.append(o)}}
function axis(id,values,multi){const box=$(id);box.replaceChildren();const sel=S[id]||[];
 for(const v of values){const l=document.createElement("label"),i=document.createElement("input");
  i.type=multi?"checkbox":"radio";i.name=id;i.value=v;i.checked=sel.includes(v);
  i.addEventListener("change",()=>{S[id]=[...box.querySelectorAll("input:checked")].map(x=>x.value);refresh()});
  l.append(i,document.createTextNode(v));box.append(l)}}
function scenario(){return O.scenarios.find(s=>s.id===$("scenario").value)}
function drawAxes(){const multi=S.mode==="batch";
 axis("nudges",multi?O.batch_nudges:O.fields.nudge.choices,multi);
 axis("oversights",["true","false"],multi);axis("lures",["false","true"],multi);
 axis("goalguards",O.goalguard_arms,multi);
 const sc=scenario();$("variants-box").hidden=!sc.variants.length;axis("variants",sc.variants,multi);
 $("goalguards-box").hidden=!!sc.path}
function setMode(m){S.mode=m;for(const b of document.querySelectorAll("#mode button"))b.setAttribute("aria-pressed",b.dataset.mode===m);
 const pick=a=>S[a]&&S[a].length?[S[a][0]]:[];
 if(m==="single"){for(const a of["nudges","oversights","lures","goalguards","variants"])S[a]=pick(a)}drawAxes();refresh()}
function applyScenario(){const sc=scenario();S.variants=[];
 if(sc.cells&&sc.cells.length){S.oversights=[String(sc.cells[0][0])];S.lures=[String(sc.cells[0][1])]}
 const caps=sc.path?sc.capabilities:O.fields.capability.choices;opt($("capability"),caps,"none (propensity)");
 drawAxes();refresh()}
function applyCapability(){S.capability=$("capability").value;
 if(S.capability){S.nudges=["none"];S.lures=["false"];if(!(S.oversights||[]).length||S.capability.startsWith("oversight"))S.oversights=["true"];S.goalguards=[];setMode("single")}else refresh()}
function advanced(){const box=$("advanced");box.replaceChildren();
 for(const d of O.advanced){const f=O.fields[d];const l=document.createElement("label");l.append(document.createTextNode(f.flag));
  const h=document.createElement("small");h.textContent=f.help.slice(0,110)+(f.help.length>110?"...":"");l.append(h);
  let i;if(f.kind==="choice"){i=document.createElement("select");opt(i,f.choices,"default")}
  else if(f.kind==="bool"){i=document.createElement("input");i.type="checkbox"}
  else{i=document.createElement("input");i.type="text";i.placeholder=f.default==null?"":String(f.default)}
  i.addEventListener("input",()=>{S.advanced[d]=f.kind==="bool"?i.checked:i.value;refresh()});l.append(i);box.append(l)}}
function spec(){return{mode:S.mode,scenario:$("scenario").value,model:$("model").value,provider:$("provider").value,sort:$("sort").value,
 effort:$("effort").value,grade:$("grade").checked,grader_model:$("grader_model").value,capability:S.capability||"",
 nudges:S.nudges,oversights:S.oversights,lures:S.lures,goalguards:$("goalguards-box").hidden?[]:S.goalguards,variants:S.variants,
 runs:$("runs").value,output_dir:$("output_dir").value,date_mode:$("date_mode").value==="default"?"":$("date_mode").value,advanced:S.advanced}}
function refresh(){clearTimeout(timer);timer=setTimeout(async()=>{
 const r=await fetch("/api/command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(spec())});
 const d=await r.json();$("command").textContent=d.command||"(fix the errors below)";S.cmd=d.command;S.dry=d.dry_run;
 $("copy").disabled=!d.command;$("copy-dry").hidden=!d.dry_run;
 $("count").textContent=d.command?(d.arms===1?"1 arm":d.arms+" arms")+", "+d.episodes+" episodes if nothing is on disk":"";
 const m=$("messages");m.replaceChildren();
 for(const [c,list] of [["e",d.errors],["w",d.warnings]])for(const t of list){const li=document.createElement("li");li.className=c;li.textContent=t;m.append(li)}},120)}
async function copy(text,btn){try{await navigator.clipboard.writeText(text);const t=btn.textContent;btn.textContent="Copied";setTimeout(()=>btn.textContent=t,1200)}catch(e){const s=getSelection(),r=document.createRange();r.selectNodeContents($("command"));s.removeAllRanges();s.addRange(r)}}
async function start(){O=await (await fetch("/api/options")).json();const f=O.fields;
 for(const sc of O.scenarios){const o=document.createElement("option");o.value=sc.id;o.textContent=sc.id===""?sc.name+" ("+sc.rollout+")":sc.name+" ("+sc.rollout+")";$("scenario").append(o)}
 for(const m of O.models){const o=document.createElement("option");o.value=m;$("models").append(o)}
 $("model").value=f.model.default;opt($("sort"),f.openrouter_sort.choices,"default");opt($("effort"),f.effort.choices,"none sent");
 opt($("date_mode"),f.date_mode.choices);$("date_mode").value="default";
 $("grader_model").value=f.grader_model.default;$("runs").value=f.runs.default;$("output_dir").value=f.output_dir.default;
 S.nudges=[...O.batch_nudges];S.oversights=["true","false"];S.lures=["false","true"];S.goalguards=["none"];S.variants=[];
 advanced();applyScenario();
 $("scenario").addEventListener("change",applyScenario);$("capability").addEventListener("change",applyCapability);
 for(const id of["model","provider","sort","effort","grade","grader_model","runs","output_dir","date_mode"])$(id).addEventListener("input",refresh);
 $("grade").addEventListener("change",()=>{$("grader_model").disabled=!$("grade").checked;refresh()});
 for(const b of document.querySelectorAll("#mode button"))b.addEventListener("click",()=>setMode(b.dataset.mode));
 $("copy").addEventListener("click",e=>copy(S.cmd,e.target));$("copy-dry").addEventListener("click",e=>copy(S.dry,e.target))}
start();
</script></main></body></html>
"""
