"""Coupa MCP resource definitions - self-contained HTML+Skybridge widgets."""

from __future__ import annotations


_WIDGET_HTML = r'''<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root { color-scheme: light dark; --bg:#0c1017; --panel:#151b24; --panel2:#101720; --soft:#1c2633; --text:#e7edf5; --muted:#9ca8b7; --border:#2a3545; --accent:#1f7a8c; --accent2:#2fbf71; --warn:#d89b20; --bad:#df4c5f; --ink:#111827; --shadow:rgba(0,0,0,.22); }
      :root[data-theme="light"] { --bg:#f5f7fa; --panel:#ffffff; --panel2:#f0f4f8; --soft:#e8eef5; --text:#1f2937; --muted:#64748b; --border:#d7dee8; --accent:#006b7f; --accent2:#087f5b; --warn:#9a5b00; --bad:#b4233a; --ink:#ffffff; --shadow:rgba(15,23,42,.08); }
      * { box-sizing:border-box; }
      html, body { min-height:100%; margin:0; background:var(--bg); color:var(--text); }
      body { font-family:"Segoe UI", system-ui, -apple-system, sans-serif; font-size:13px; }
      button, input, select, textarea { font:inherit; }
      .wrap { padding:14px; min-height:100%; }
      .top { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:10px; }
      .brand { display:flex; align-items:center; gap:10px; min-width:0; }
      .logo { width:30px; height:30px; border-radius:7px; display:grid; place-items:center; color:#fff; background:linear-gradient(135deg,#006b7f,#2fbf71); font-weight:800; flex:0 0 auto; }
      .title { font-size:15px; font-weight:700; line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .subtitle { color:var(--muted); font-size:12px; line-height:1.25; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .top-actions { display:flex; gap:7px; align-items:center; }
      .pill { border:1px solid var(--border); border-radius:999px; padding:4px 8px; color:var(--muted); background:var(--panel2); font-size:11px; white-space:nowrap; }
      .icon-btn, .btn { border:1px solid var(--border); background:var(--panel); color:var(--text); cursor:pointer; }
      .icon-btn { width:30px; height:30px; border-radius:7px; display:grid; place-items:center; }
      .btn { border-radius:7px; padding:6px 10px; white-space:nowrap; }
      .icon-btn:hover, .btn:hover { border-color:var(--accent); color:var(--accent); }
      .toolbar { display:flex; gap:8px; align-items:center; margin-bottom:10px; }
      input, select, textarea { border:1px solid var(--border); background:var(--panel); color:var(--text); border-radius:7px; padding:7px 9px; outline:none; min-width:0; }
      input:focus, select:focus, textarea:focus { border-color:var(--accent); }
      .search { flex:1; }
      .kpis { display:flex; gap:6px; overflow-x:auto; padding-bottom:2px; margin-bottom:10px; scrollbar-width:thin; }
      .kpi { display:flex; align-items:baseline; gap:6px; min-width:max-content; border:1px solid var(--border); border-radius:999px; background:var(--panel); padding:5px 8px; box-shadow:0 1px 5px var(--shadow); }
      .kpi-label { color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.04em; }
      .kpi-value { font-size:13px; font-weight:800; }
      .tabs { display:flex; gap:6px; overflow-x:auto; margin-bottom:10px; padding-bottom:2px; }
      .tab { border:1px solid var(--border); color:var(--muted); background:var(--panel2); border-radius:999px; padding:4px 9px; cursor:pointer; white-space:nowrap; }
      .tab.active { color:#fff; background:var(--accent); border-color:var(--accent); }
      .panel { background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:10px; min-width:0; box-shadow:0 1px 8px var(--shadow); }
      .panel-title { display:flex; align-items:center; justify-content:space-between; gap:8px; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; margin-bottom:8px; }
      .grid { display:grid; grid-template-columns:minmax(0,1.15fr) minmax(260px,.85fr); gap:10px; }
      .dashboard-grid { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(240px,.75fr); gap:10px; }
      .chart-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-bottom:10px; }
      .cards { display:grid; gap:7px; }
      .card { border:1px solid var(--border); background:var(--panel2); border-radius:8px; padding:9px; cursor:pointer; min-width:0; }
      .card:hover, .card.active { border-color:var(--accent); }
      .card-head { display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }
      .card-title { font-weight:700; line-height:1.25; word-break:break-word; }
      .card-key { color:var(--accent); font-size:11px; font-weight:700; white-space:nowrap; }
      .meta { display:flex; gap:5px; flex-wrap:wrap; margin-top:7px; color:var(--muted); font-size:11px; }
      .tag { border:1px solid var(--border); background:var(--panel); border-radius:6px; padding:2px 6px; white-space:nowrap; }
      .tag.good { border-color:var(--accent2); color:var(--accent2); }
      .tag.warn { border-color:var(--warn); color:var(--warn); }
      .tag.bad { border-color:var(--bad); color:var(--bad); }
      .table { width:100%; border-collapse:collapse; font-size:12px; }
      .table th { color:var(--muted); text-align:left; font-weight:600; font-size:10px; text-transform:uppercase; letter-spacing:.04em; padding:6px; border-bottom:1px solid var(--border); }
      .table td { padding:7px 6px; border-bottom:1px solid var(--border); vertical-align:top; }
      .table tr:last-child td { border-bottom:0; }
      .num { text-align:right; font-variant-numeric:tabular-nums; }
      .bar-row { display:grid; grid-template-columns:minmax(96px,1fr) minmax(90px,1.4fr) auto; gap:7px; align-items:center; margin:7px 0; }
      .bar-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); font-size:11px; }
      .bar-track { height:10px; border:1px solid var(--border); background:var(--panel2); border-radius:999px; overflow:hidden; }
      .bar-fill { height:100%; background:linear-gradient(90deg,var(--accent),var(--accent2)); }
      .bar-value { font-size:11px; font-weight:700; }
      .heat { display:grid; grid-template-columns:repeat(5,minmax(62px,1fr)); gap:6px; }
      .heat-cell { min-height:62px; border:1px solid var(--border); border-radius:8px; background:var(--panel2); padding:7px; }
      .heat-cell.bad { border-color:var(--bad); }
      .heat-cell.warn { border-color:var(--warn); }
      .heat-value { font-size:18px; font-weight:800; }
      .heat-label { color:var(--muted); font-size:10px; line-height:1.2; margin-top:3px; }
      .flow { display:grid; gap:8px; }
      .flow-row { border:1px solid var(--border); background:var(--panel2); border-radius:8px; padding:9px; }
      .flow-head { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:8px; }
      .steps { display:grid; grid-template-columns:repeat(5,minmax(84px,1fr)); gap:6px; }
      .step { border:1px solid var(--border); border-radius:8px; background:var(--panel); padding:7px; position:relative; min-height:66px; }
      .step.done { border-color:var(--accent2); }
      .step.warn { border-color:var(--warn); }
      .step.bad { border-color:var(--bad); }
      .step-k { color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.04em; }
      .step-v { font-weight:750; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-top:4px; }
      .step-s { color:var(--muted); font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-top:3px; }
      .status-card { display:grid; gap:8px; }
      .status-hero { display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; border:1px solid var(--border); border-radius:8px; background:var(--panel2); padding:10px; }
      .status-key { color:var(--accent); font-weight:800; }
      .status-main { font-size:20px; font-weight:850; line-height:1.15; }
      .fields { display:grid; gap:7px; }
      .field { display:grid; grid-template-columns:120px minmax(0,1fr); gap:8px; padding-bottom:7px; border-bottom:1px solid var(--border); }
      .field:last-child { border-bottom:0; }
      .label { color:var(--muted); font-size:11px; }
      .value { word-break:break-word; }
      .form-grid { display:grid; grid-template-columns:1fr 1fr; gap:9px; }
      .form-grid .wide { grid-column:1/-1; }
      textarea { min-height:70px; resize:vertical; }
      .alert { border:1px solid var(--border); background:var(--panel2); border-radius:8px; padding:8px; margin-bottom:7px; }
      .alert.high { border-color:var(--bad); }
      .alert.medium { border-color:var(--warn); }
      .empty { color:var(--muted); text-align:center; padding:22px 8px; }
      @media (max-width:760px) { .grid,.dashboard-grid,.chart-grid { grid-template-columns:1fr; } .steps { grid-template-columns:repeat(5, minmax(96px, 1fr)); overflow-x:auto; } .field,.form-grid { grid-template-columns:1fr; } .form-grid .wide { grid-column:auto; } .pill { display:none; } }
    </style>
  </head>
  <body>
    <script>(function(){var d=document.documentElement,m=matchMedia('(prefers-color-scheme:dark)'),a=!d.hasAttribute('data-theme');function s(){d.setAttribute('data-theme',m.matches?'dark':'light')}if(a)s();m.addEventListener('change',function(){if(a)s()});new MutationObserver(function(){a=false}).observe(d,{attributes:true,attributeFilter:['data-theme']})})()</script>
    <div class="wrap">
      <div class="top">
        <div class="brand"><div class="logo">C</div><div><div class="title">__TITLE__</div><div class="subtitle">__SUBTITLE__</div></div></div>
        <div class="top-actions"><div class="pill">__KIND__</div><button class="icon-btn" id="maximizeBtn" title="Maximize"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10 2h4v4M6 14H2v-4M14 2L9.5 6.5M2 14l4.5-4.5"/></svg></button></div>
      </div>
      <div id="app"></div>
    </div>
    <script>
      var CONFIG = { title: "__TITLE__", subtitle: "__SUBTITLE__", kind: "__KIND__" };
      var SAMPLE = { success:true, summary:{order_count:7,total_value:"227,464.00",open_value:"173,042.00",at_risk_orders:2,by_status:{issued:3,partially_received:1,closed:1,supplier_acknowledged:1,pending_supplier_ack:1},by_category:{"Laptop hardware":2,"Mobile devices":2,"Developer workstations":1,"Office equipment":1,Accessories:1}}, results:[{"po-number":"PO-2026-1051",status:"partially_received",total:"33,390.00","open-value":"2,796.00",category:"Mobile devices",supplier:{name:"Apple Business Reseller UK"},department:"Sales EMEA",location:"Manchester","delivery-risk":"late",lines:[{description:"iPhone 15 128GB",quantity:42,received:38}]}], suppliers:[{id:"SUP-4101",name:"TechDirect UK Ltd",tier:"strategic",risk:"low",category:"Laptop hardware",metrics:{on_time_rate:94,defect_rate:1.1,avg_lead_days:6},order_summary:{order_count:2,total_value:"65,942.00",open_value:"47,954.00"}},{id:"SUP-4105",name:"Insight Enterprise Technology",tier:"preferred",risk:"medium",category:"Accessories",metrics:{on_time_rate:84,defect_rate:2.4,avg_lead_days:8},order_summary:{order_count:1,total_value:"23,340.00",open_value:"23,340.00"}}], items:[{id:"IT-DOCK-USBC",name:"USB-C Docking Station",category:"Accessories",supplier:"Insight Enterprise Technology","unit-price":"189.00",stock:39,"monthly-demand":68,ordered_quantity:102,open_quantity:90,ordered_value:"19,278.00",risk:"stockout",stock_coverage_months:.6}], flows:[{"service-now-request":"REQ0012491","requested-item":"RITM0018442",employee:"Noah Bennett",department:"Sales EMEA",status:"partially_received",supplier:{name:"Apple Business Reseller UK"},category:"Mobile devices",total:"33,390.00","open-value":"2,796.00","blocked-reason":"Overdue delivery",requisition:{"requisition-number":"REQ-C-2026-9002",status:"approved"},purchase_order:{"po-number":"PO-2026-1051",status:"partially_received",total:"33,390.00","open-value":"2,796.00"},receipts:[{"receipt-number":"RCPT-2026-7002",status:"partial"}],invoices:[{"invoice-number":"INV-2026-0417",status:"pending_approval"}]}], demand:[], alerts:[{severity:"high",title:"PO-2026-1051 is past expected delivery",detail:"Apple Business Reseller UK order for Sales EMEA is overdue."}] };
      function parseMaybeJson(value){ if(typeof value!=="string") return null; try{return JSON.parse(value);}catch(e){return null;} }
      function unwrapToolOutput(value){
        if(!value) return SAMPLE;
        if(value.structuredContent) return unwrapToolOutput(value.structuredContent);
        if(value.data && typeof value.data==="object") return unwrapToolOutput(value.data);
        if(value.output && typeof value.output==="object") return unwrapToolOutput(value.output);
        if(Array.isArray(value.content)){ for(var i=0;i<value.content.length;i++){ var item=value.content[i]||{}; var parsed=parseMaybeJson(item.text||item.content||""); if(parsed) return unwrapToolOutput(parsed); } }
        return value;
      }
      var data = unwrapToolOutput(window.openai && window.openai.toolOutput);
      if(data.supplier_performance && !data.suppliers) data.suppliers = data.supplier_performance;
      if(data.demand && !data.items && Array.isArray(data.demand)) data.items = data.demand;
      var app = document.getElementById("app"), search = "", activeTab = "all", activeIndex = 0;
      var expandSvg = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10 2h4v4M6 14H2v-4M14 2L9.5 6.5M2 14l4.5-4.5"/></svg>';
      var collapseSvg = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 6h-4V2M2 10h4v4M9.5 6.5L14 2M6.5 9.5L2 14"/></svg>';
      function esc(v){var d=document.createElement("div"); d.textContent = v == null ? "" : String(v); return d.innerHTML;}
      function n(v){ var x=parseFloat(String(v||0).replace(/[^0-9.-]/g,"")); return isFinite(x)?x:0; }
      function compact(v){ var x=n(v); if(Math.abs(x)>=1000000) return (x/1000000).toFixed(1)+"m"; if(Math.abs(x)>=1000) return (x/1000).toFixed(0)+"k"; return String(Math.round(x)); }
      function money(v){ if(v==null||v==="") return "GBP 0"; return "GBP "+compact(v); }
      function moneyFull(v){ if(v==null||v==="") return "GBP 0"; return "GBP "+new Intl.NumberFormat("en-GB",{maximumFractionDigits:0}).format(n(v)); }
      function pct(v){ return (n(v)||0).toFixed(0)+"%"; }
      function supplierName(row){ return row && row.supplier && row.supplier.name ? row.supplier.name : row && row.supplier ? row.supplier : row && row.purchase_order && row.purchase_order.supplier && row.purchase_order.supplier.name ? row.purchase_order.supplier.name : row && row.name ? row.name : "-"; }
      function keyOf(row){ row=row||{}; return row["po-number"] || row["invoice-number"] || row["requisition-number"] || row["receipt-number"] || row.id || row["service-now-request"] || (row.purchase_order&&row.purchase_order["po-number"]) || row.name || row.title || "Record"; }
      function titleOf(row){ row=row||{}; return row.title || row.name || row.description || row.item || row["po-number"] || row["service-now-request"] || (row.purchase_order&&row.purchase_order["po-number"]) || row.type || "Coupa record"; }
      function statusOf(row){ row=row||{}; return row.status || row.risk || row["payment-status"] || (row.purchase_order&&row.purchase_order.status) || row.tier || row.category || "active"; }
      function riskClass(v){ v=String(v||"").toLowerCase(); return v.indexOf("late")>=0||v.indexOf("stockout")>=0||v.indexOf("high")>=0||v.indexOf("rejected")>=0||v.indexOf("overdue")>=0?"bad":v.indexOf("risk")>=0||v.indexOf("pending")>=0||v.indexOf("watch")>=0||v.indexOf("medium")>=0||v.indexOf("partial")>=0?"warn":"good"; }
      function baseRows(){ var k=CONFIG.kind; if(k==="category-dashboard") return data.orders||data.results||SAMPLE.results; if(k==="supplier-performance"||k==="supplier-list"||k==="supplier-profile") return data.suppliers||data.results||(Array.isArray(data)?data:[data]); if(k==="item-demand") return data.items||data.demand||SAMPLE.items; if(k==="catalog-search") return data.results||data.items||SAMPLE.items; if(k==="request-flow") return data.flows||SAMPLE.flows; if(k==="receipt-list") return data.results||data.receipts||(Array.isArray(data)?data:[data]); if(k==="requisition-list") return data.results||data.requisitions||(Array.isArray(data)?data:[data]); if(k==="approval-list") return data.results||data.approvals||(Array.isArray(data)?data:[data]); if(k==="status-card"||k==="confirm-action"||k==="form") return Array.isArray(data)?data:[data]; return data.results||data.orders||data.items||data.flows||(Array.isArray(data)?data:[data]); }
      function rows(){ var list=(baseRows()||[]).filter(Boolean); if(search){ var q=search.toLowerCase(); list=list.filter(function(r){return JSON.stringify(r).toLowerCase().indexOf(q)>=0;}); } if(activeTab!=="all") list=list.filter(function(r){return String(statusOf(r)).toLowerCase()===activeTab || String(r.category||"").toLowerCase()===activeTab || String(r.tier||"").toLowerCase()===activeTab;}); return list; }
      function sum(list, fn){ return (list||[]).reduce(function(t,r){ return t+n(fn(r)); },0); }
      function kpis(){ var list=baseRows().filter(Boolean), s=data.summary||{}, k=CONFIG.kind; if(k==="supplier-performance"||k==="supplier-list"||k==="supplier-profile") return [{label:"Suppliers",value:s.supplier_count||list.length},{label:"Strategic",value:s.strategic_suppliers||list.filter(function(x){return x.tier==="strategic";}).length},{label:"Open",value:money(s.open_value||sum(list,function(x){return x.order_summary&&x.order_summary.open_value;}))},{label:"Risk",value:s.at_risk_suppliers||list.filter(function(x){return x.risk!=="low";}).length}]; if(k==="item-demand") return [{label:"Items",value:s.item_count||list.length},{label:"Stockout",value:s.stockout_risk||list.filter(function(x){return x.risk==="stockout";}).length},{label:"Watch",value:s.watch_items||list.filter(function(x){return x.risk==="watch";}).length},{label:"Open Qty",value:sum(list,function(x){return x.open_quantity;})}]; if(k==="catalog-search") return [{label:"Items",value:list.length},{label:"Contracted",value:list.filter(function(x){return x.contracted;}).length},{label:"Avg Lead",value:Math.round(sum(list,function(x){return x["lead-time-days"];})/Math.max(list.length,1))+"d"},{label:"Stock",value:sum(list,function(x){return x.stock;})}]; if(k==="request-flow") return [{label:"Requests",value:s.flow_count||list.length},{label:"PO Value",value:money(s.total_value||sum(list,function(x){return x.total||(x.purchase_order&&x.purchase_order.total);} ))},{label:"Blocked",value:s.blocked_flows||list.filter(function(x){return x["blocked-reason"]!=="Progressing";}).length},{label:"Receipts",value:s.with_receipts||list.filter(function(x){return (x.receipts||[]).length;}).length}]; if(k==="status-card") return [{label:"Status",value:statusOf(list[0])},{label:"Value",value:money((list[0]||{}).total)},{label:"Open",value:money((list[0]||{})["open-value"])},{label:"Supplier",value:supplierName(list[0]).split(" ").slice(0,2).join(" ")}]; if(k==="confirm-action") return [{label:"Action",value:statusOf(list[0])},{label:"ID",value:keyOf(list[0])},{label:"Date",value:(list[0]||{})["actioned-at"]||"ready"}]; return [{label:"Records",value:s.order_count||list.length},{label:"Total",value:money(s.total_value||sum(list,function(x){return x.total||x.ordered_value;}))},{label:"Open",value:money(s.open_value||sum(list,function(x){return x["open-value"];}))},{label:"Risk",value:s.at_risk_orders||list.filter(function(x){return riskClass(statusOf(x))!=="good" || x["delivery-risk"]==="late" || x["delivery-risk"]==="at_risk";}).length}]; }
      function kpiHtml(){ return '<div class="kpis">'+kpis().map(function(x){return '<div class="kpi"><span class="kpi-label">'+esc(x.label)+'</span><span class="kpi-value" title="'+esc(x.value)+'">'+esc(x.value)+'</span></div>';}).join("")+'</div>'; }
      function toolbarHtml(){ return '<div class="toolbar"><input class="search" id="search" value="'+esc(search)+'" placeholder="Search Coupa data"/><button class="btn" id="refresh">Refresh</button><button class="btn" id="ask">Ask Copilot</button></div>'; }
      function tabsHtml(){ var source=data.summary&&data.summary.by_status?data.summary.by_status:{}; if(!Object.keys(source).length && data.summary && data.summary.by_category) source=data.summary.by_category; var counts={all:baseRows().length}; Object.keys(source).slice(0,6).forEach(function(k){counts[k]=source[k];}); var keys=Object.keys(counts); return '<div class="tabs">'+keys.map(function(k){var v=k.toLowerCase(); return '<button class="tab '+(activeTab===v?'active':'')+'" data-tab="'+esc(v)+'">'+esc(k.replace(/_/g," "))+' '+counts[k]+'</button>';}).join("")+'</div>'; }
      function card(row,i){ return '<div class="card '+(i===activeIndex?'active':'')+'" data-idx="'+i+'"><div class="card-head"><div class="card-title">'+esc(titleOf(row))+'</div><div class="card-key">'+esc(keyOf(row))+'</div></div><div class="meta"><span class="tag '+riskClass(statusOf(row))+'">'+esc(String(statusOf(row)).replace(/_/g," "))+'</span><span class="tag">'+esc(row.category||row.department||row.type||row.tier||"")+'</span><span class="tag">'+esc(supplierName(row))+'</span><span class="tag">'+moneyFull(row.total||row.ordered_value||(row.order_summary&&row.order_summary.total_value)||(row.purchase_order&&row.purchase_order.total))+'</span></div></div>'; }
      function listPanel(title){ var list=rows(); return '<div class="panel"><div class="panel-title"><span>'+esc(title||"Records")+'</span><span>'+list.length+' shown</span></div>'+(list.length?'<div class="cards">'+list.map(card).join("")+'</div>':'<div class="empty">No Coupa records match the current filters.</div>')+'</div>'; }
      function fields(row){ row=row||{}; var pairs=[]; Object.keys(row).forEach(function(k){ if(row[k]==null || typeof row[k]!=="object") pairs.push([k,row[k]]); }); if(row.supplier&&row.supplier.name) pairs.push(["supplier",row.supplier.name]); if(row.purchase_order) pairs.push(["purchase order", row.purchase_order["po-number"]+", "+moneyFull(row.purchase_order.total)+", "+String(row.purchase_order.status).replace(/_/g," ")]); if(row.requisition) pairs.push(["requisition", row.requisition["requisition-number"]+", "+String(row.requisition.status).replace(/_/g," ")]); if(row.order_summary) pairs.push(["orders", row.order_summary.order_count+" orders, "+moneyFull(row.order_summary.open_value)+" open"]); if(row.metrics) pairs.push(["metrics", pct(row.metrics.on_time_rate)+" on-time, "+row.metrics.avg_lead_days+" day lead, "+row.metrics.defect_rate+"% defects"]); return '<div class="fields">'+pairs.slice(0,12).map(function(p){return '<div class="field"><div class="label">'+esc(String(p[0]).replace(/-/g," "))+'</div><div class="value">'+esc(p[1])+'</div></div>';}).join("")+'</div>'; }
      function detailPanel(title){ var list=rows(), row=list[Math.min(activeIndex,Math.max(list.length-1,0))]||{}; return '<div class="panel"><div class="panel-title">'+esc(title||"Details")+'</div>'+fields(row)+'<div class="meta" style="margin-top:10px"><button class="btn" id="follow">Next action</button></div></div>'; }
      function bars(source, formatter){ var keys=Object.keys(source||{}); if(!keys.length) return '<div class="empty">No rollup data available.</div>'; var max=Math.max.apply(null,keys.map(function(k){return n(source[k]);}))||1; return keys.slice(0,7).map(function(k){var v=n(source[k]); return '<div class="bar-row"><div class="bar-name" title="'+esc(k)+'">'+esc(k.replace(/_/g," "))+'</div><div class="bar-track"><div class="bar-fill" style="width:'+Math.max(4,(v/max)*100).toFixed(0)+'%"></div></div><div class="bar-value">'+esc(formatter?formatter(source[k]):source[k])+'</div></div>';}).join(""); }
      function alerts(){ var list=data.alerts||[]; if(!list.length) return '<div class="empty">No active category alerts.</div>'; return list.map(function(a){return '<div class="alert '+esc(a.severity||"")+'"><strong>'+esc(a.title)+'</strong><div class="subtitle">'+esc(a.detail)+'</div></div>';}).join(""); }
      function simpleTable(list, cols){ if(!list.length) return '<div class="empty">No rows to show.</div>'; return '<table class="table"><thead><tr>'+cols.map(function(c){return '<th class="'+(c.num?'num':'')+'">'+esc(c.label)+'</th>';}).join("")+'</tr></thead><tbody>'+list.map(function(row){return '<tr>'+cols.map(function(c){return '<td class="'+(c.num?'num':'')+'">'+esc(c.f(row))+'</td>';}).join("")+'</tr>';}).join("")+'</tbody></table>'; }
      function renderCategoryDashboard(){ var s=data.summary||{}, orders=data.orders||data.results||[], byCat=s.by_category||{}, byStatus=s.by_status||{}; return toolbarHtml()+kpiHtml()+tabsHtml()+'<div class="dashboard-grid"><div><div class="chart-grid"><div class="panel"><div class="panel-title"><span>Spend by category</span><span>'+orders.length+' POs</span></div>'+bars(byCat)+'</div><div class="panel"><div class="panel-title"><span>Status mix</span><span>fulfilment</span></div>'+bars(byStatus)+'</div></div>'+listPanel("Open hardware orders")+'</div><div class="panel"><div class="panel-title"><span>Alerts</span><span>category manager</span></div>'+alerts()+'</div></div>'; }
      function renderSupplierPerformance(){ var list=rows(); var riskCounts={low:0,medium:0,high:0}; list.forEach(function(s){riskCounts[s.risk||"low"]=(riskCounts[s.risk||"low"]||0)+1;}); return toolbarHtml()+kpiHtml()+'<div class="chart-grid"><div class="panel"><div class="panel-title"><span>On-time scorecard</span><span>supplier KPI</span></div>'+bars(Object.fromEntries(list.map(function(s){return [s.name,(s.metrics&&s.metrics.on_time_rate)||0];})),function(v){return pct(v);})+'</div><div class="panel"><div class="panel-title"><span>Risk matrix</span><span>tier and exposure</span></div><div class="heat">'+list.slice(0,5).map(function(s){return '<div class="heat-cell '+riskClass(s.risk)+'"><div class="heat-value">'+pct(s.metrics&&s.metrics.on_time_rate)+'</div><div class="heat-label">'+esc(s.name)+'<br>'+esc(s.tier||"")+' / '+esc(s.risk||"")+'<br>'+money(s.order_summary&&s.order_summary.open_value)+' open</div></div>';}).join("")+'</div></div></div><div class="grid">'+listPanel("Supplier scorecards")+detailPanel("Supplier detail")+'</div>'; }
      function renderItemDemand(){ var list=rows().sort(function(a,b){return n(a.stock_coverage_months)-n(b.stock_coverage_months);}); return toolbarHtml()+kpiHtml()+'<div class="chart-grid"><div class="panel"><div class="panel-title"><span>Stock coverage</span><span>months</span></div>'+bars(Object.fromEntries(list.map(function(x){return [x.name,x.stock_coverage_months||0];})),function(v){return n(v).toFixed(1)+" mo";})+'</div><div class="panel"><div class="panel-title"><span>Open demand</span><span>units</span></div>'+bars(Object.fromEntries(list.map(function(x){return [x.name,x.open_quantity||0];})))+'</div></div><div class="panel"><div class="panel-title"><span>Demand risk table</span><span>lowest coverage first</span></div>'+simpleTable(list,[{label:"Item",f:function(x){return x.name;}},{label:"Risk",f:function(x){return x.risk;}},{label:"Stock",num:true,f:function(x){return x.stock;}},{label:"Monthly",num:true,f:function(x){return x["monthly-demand"];}},{label:"Coverage",num:true,f:function(x){return (n(x.stock_coverage_months)).toFixed(1)+" mo";}},{label:"Open",num:true,f:function(x){return x.open_quantity;}}])+'</div>'; }
      function renderRequestFlow(){ var list=rows(); return toolbarHtml()+kpiHtml()+'<div class="flow">'+list.map(function(f,i){var po=f.purchase_order||{}, req=f.requisition||{}, receipts=f.receipts||[], invoices=f.invoices||[], blocked=f["blocked-reason"]&&f["blocked-reason"]!=="Progressing"; var steps=[['ServiceNow',f["service-now-request"],f.employee||f.department,'done'],['Requisition',req["requisition-number"]||f["requested-item"],req.status||'approved','done'],['PO',po["po-number"],po.status||f.status,blocked?'warn':'done'],['Receipt',receipts.length?receipts.length+' posted':'waiting',receipts[0]&&receipts[0].status,receipts.length?'done':'warn'],['Invoice',invoices.length?invoices.length+' created':'waiting',invoices[0]&&invoices[0].status,invoices.length?'done':'warn']]; return '<div class="flow-row"><div class="flow-head"><div><strong>'+esc(f["service-now-request"]||keyOf(f))+'</strong><div class="subtitle">'+esc(f.department||"")+' | '+esc(supplierName(f))+' | '+moneyFull(f.total||(po&&po.total))+'</div></div><span class="tag '+riskClass(f["blocked-reason"])+'">'+esc(f["blocked-reason"]||"Progressing")+'</span></div><div class="steps">'+steps.map(function(s){return '<div class="step '+s[3]+'"><div class="step-k">'+esc(s[0])+'</div><div class="step-v" title="'+esc(s[1])+'">'+esc(s[1]||'-')+'</div><div class="step-s" title="'+esc(s[2])+'">'+esc(s[2]||'')+'</div></div>';}).join("")+'</div></div>'; }).join("")+'</div>'; }
      function renderCatalog(){ var list=rows(); return toolbarHtml()+kpiHtml()+'<div class="panel"><div class="panel-title"><span>Catalog availability</span><span>contracted IT hardware</span></div>'+simpleTable(list,[{label:"Item",f:function(x){return x.name;}},{label:"Category",f:function(x){return x.category;}},{label:"Supplier",f:function(x){return x.supplier;}},{label:"Price",num:true,f:function(x){return moneyFull(x["unit-price"]);}},{label:"Lead",num:true,f:function(x){return x["lead-time-days"]+"d";}},{label:"Stock",num:true,f:function(x){return x.stock;}}])+'</div>'; }
      function renderOrders(){ return toolbarHtml()+kpiHtml()+tabsHtml()+'<div class="grid">'+listPanel("Purchase order board")+detailPanel("Order detail")+'</div>'; }
      function renderStatus(){ var row=rows()[0]||{}; return kpiHtml()+'<div class="status-card"><div class="status-hero"><div><div class="status-key">'+esc(keyOf(row))+'</div><div class="status-main">'+esc(String(statusOf(row)).replace(/_/g," "))+'</div><div class="subtitle">'+esc(supplierName(row))+' | '+moneyFull(row.total)+'</div></div><span class="tag '+riskClass(statusOf(row))+'">'+esc(row["delivery-risk"]||row["payment-status"]||statusOf(row))+'</span></div><div class="panel"><div class="panel-title">Record fields</div>'+fields(row)+'</div></div>'; }
      function renderForm(){ return kpiHtml()+'<div class="panel"><div class="panel-title"><span>Draft transaction</span><span>Coupa</span></div><div class="form-grid"><label>Requester<input id="requester" value="alex.morgan@example.com"></label><label>Need by<input type="date" id="needby" value="2026-05-20"></label><label class="wide">Item<select id="item"><option>Standard Laptop</option><option>Developer Laptop</option><option>iPhone 15 128GB</option><option>USB-C Docking Station</option></select></label><label>Quantity<input type="number" id="qty" value="1" min="1"></label><label>Location<input id="loc" value="London"></label><label class="wide">Business justification<textarea id="just">ServiceNow employee request for approved IT hardware fulfilment.</textarea></label><button class="btn wide" id="draft">Generate draft</button></div><div id="draftOut" class="meta"></div></div>'+(data.catalog_items?'<div class="panel" style="margin-top:10px"><div class="panel-title">Catalog choices</div>'+simpleTable(data.catalog_items.slice(0,5),[{label:"Item",f:function(x){return x.name;}},{label:"Supplier",f:function(x){return x.supplier;}},{label:"Price",num:true,f:function(x){return moneyFull(x["unit-price"]);}}])+'</div>':''); }
      function renderGeneric(){ return toolbarHtml()+kpiHtml()+tabsHtml()+'<div class="grid">'+listPanel("Records")+detailPanel("Details")+'</div>'; }
      function render(){ var k=CONFIG.kind; if(k==="category-dashboard") app.innerHTML=renderCategoryDashboard(); else if(k==="supplier-performance"||k==="supplier-list"||k==="supplier-profile") app.innerHTML=renderSupplierPerformance(); else if(k==="item-demand") app.innerHTML=renderItemDemand(); else if(k==="request-flow") app.innerHTML=renderRequestFlow(); else if(k==="catalog-search") app.innerHTML=renderCatalog(); else if(k==="hardware-order-list") app.innerHTML=renderOrders(); else if(k==="status-card") app.innerHTML=renderStatus(); else if(k==="form") app.innerHTML=renderForm(); else app.innerHTML=renderGeneric(); bind(); reportHeight(); }
      function askCopilot(prompt){ if(window.openai&&typeof window.openai.sendFollowUpMessage==="function") window.openai.sendFollowUpMessage({prompt:prompt}); }
      function bind(){ var s=document.getElementById("search"); if(s) s.oninput=function(){search=this.value; activeIndex=0; render();}; document.querySelectorAll(".tab").forEach(function(t){t.onclick=function(){activeTab=this.getAttribute("data-tab"); activeIndex=0; render();};}); document.querySelectorAll(".card").forEach(function(c){c.onclick=function(){activeIndex=parseInt(this.getAttribute("data-idx"),10)||0; render();};}); var ask=document.getElementById("ask"); if(ask) ask.onclick=function(){askCopilot("Summarize the Coupa "+CONFIG.title+" data and recommend procurement actions.");}; var follow=document.getElementById("follow"); if(follow) follow.onclick=function(){askCopilot("Show the next best action for "+keyOf(rows()[activeIndex]||{}));}; var refresh=document.getElementById("refresh"); if(refresh) refresh.onclick=function(){search=""; activeTab="all"; activeIndex=0; render();}; var draft=document.getElementById("draft"); if(draft) draft.onclick=function(){document.getElementById("draftOut").innerHTML='<span class="tag good">Draft ready</span><span class="tag">'+esc(document.getElementById("item").value)+'</span><span class="tag">Qty '+esc(document.getElementById("qty").value)+'</span>'; reportHeight();}; }
      function reportHeight(){ if(window.openai&&typeof window.openai.notifyIntrinsicHeight==="function") window.openai.notifyIntrinsicHeight(document.body.scrollHeight); }
      var isFullscreen=false, maxBtn=document.getElementById("maximizeBtn");
      async function toggleFullscreen(){ if(!window.openai||typeof window.openai.requestDisplayMode!=="function") return; try{ await window.openai.requestDisplayMode({mode:isFullscreen?"inline":"fullscreen"}); isFullscreen=!isFullscreen; maxBtn.innerHTML=isFullscreen?collapseSvg:expandSvg; maxBtn.title=isFullscreen?"Restore":"Maximize"; reportHeight(); }catch(e){} }
      if(maxBtn){ if(window.openai&&typeof window.openai.requestDisplayMode==="function") maxBtn.onclick=toggleFullscreen; else maxBtn.style.display="none"; }
      render();
    </script>
  </body>
</html>'''


def _widget(title: str, subtitle: str, kind: str) -> str:
    return (
        _WIDGET_HTML
        .replace("__TITLE__", title)
        .replace("__SUBTITLE__", subtitle)
        .replace("__KIND__", kind)
    )


def _res(description: str, title: str, subtitle: str, kind: str) -> dict:
    return {
        "description": description,
        "mime_type": "text/html+skybridge",
        "content": _widget(title, subtitle, kind),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    }


COUPA_RESOURCES: dict[str, dict] = {
    "coupa-invoice-status": _res("Invoice payment status card from Coupa.", "Invoice Status", "Coupa AP and payment status", "status-card"),
    "coupa-po-status": _res("Purchase order status card from Coupa.", "Purchase Order", "Supplier order and fulfilment view", "status-card"),
    "coupa-confirm-action": _res("Confirmation widget for Coupa actions.", "Action Confirmation", "Reject, close, transfer, or approve", "confirm-action"),
    "coupa-receipt-list": _res("Goods receipts list from Coupa.", "Goods Receipts", "Received quantities and receipt exceptions", "receipt-list"),
    "coupa-create-receipt": _res("Goods receipt creation form for Coupa.", "Create Receipt", "Post goods receipt against a PO", "form"),
    "coupa-requisition-list": _res("Purchase requisitions list from Coupa.", "Requisitions", "ServiceNow-originated demand in Coupa", "requisition-list"),
    "coupa-create-requisition": _res("Purchase requisition creation form for Coupa.", "Create Requisition", "Draft IT hardware requisitions", "form"),
    "coupa-catalog-search": _res("Procurement catalog search widget for Coupa.", "Catalog Search", "Phones, laptops, accessories, and office equipment", "catalog-search"),
    "coupa-supplier-list": _res("Supplier search results from Coupa.", "Suppliers", "IT hardware supplier network", "supplier-list"),
    "coupa-supplier-profile": _res("Supplier detail profile from Coupa.", "Supplier Profile", "Performance, risk, contract, and open orders", "supplier-profile"),
    "coupa-supplier-registration": _res("Supplier registration/onboarding form for Coupa.", "Supplier Onboarding", "Register and review new suppliers", "form"),
    "coupa-approval-list": _res("Pending approvals list from Coupa.", "Approvals", "High-value and exception approvals", "approval-list"),
    "coupa-category-dashboard": _res("Category manager dashboard for ServiceNow-sourced IT hardware orders in Coupa.", "Category Dashboard", "Spend, fulfilment risk, demand, and supplier performance", "category-dashboard"),
    "coupa-hardware-order-list": _res("Interactive IT hardware purchase order list from Coupa.", "IT Hardware Orders", "ServiceNow requests converted into Coupa POs", "hardware-order-list"),
    "coupa-supplier-performance": _res("Supplier performance and risk dashboard for Coupa IT hardware suppliers.", "Supplier Performance", "On-time rate, risk, open value, and category coverage", "supplier-performance"),
    "coupa-item-demand": _res("Demand, stock coverage, and fulfilment risk for Coupa catalog items.", "Item Demand", "Demand signals for phones, laptops, docks, and equipment", "item-demand"),
    "coupa-request-flow": _res("Trace ServiceNow requests through Coupa requisitions, POs, receipts, and invoices.", "Request Flow", "ServiceNow to Coupa lifecycle trace", "request-flow"),
}