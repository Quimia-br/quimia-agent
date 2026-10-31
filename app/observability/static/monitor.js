"use strict";
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = v => v == null ? "—" : new Intl.NumberFormat("pt-BR",{style:"currency",currency:"USD",maximumFractionDigits:5}).format(v);
const integer = v => new Intl.NumberFormat("pt-BR",{maximumFractionDigits:0}).format(v ?? 0);
const percent = v => v == null ? "—" : new Intl.NumberFormat("pt-BR",{style:"percent",maximumFractionDigits:1}).format(v);
const ms = v => v == null ? "—" : v >= 1000 ? (v/1000).toFixed(2)+" s" : Math.round(v)+" ms";
const date = v => new Date(v*1000).toLocaleString("pt-BR");
let latest = null, selected = null, timer = null, loading = false;
function table(columns, rows) {
  return `<table><thead><tr>${columns.map(x=>`<th scope="col">${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.map(row=>`<tr>${row.map(x=>`<td>${x}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${columns.length}" class="empty">Sem medições nesta janela.</td></tr>`}</tbody></table>`;
}
function card(label, value, note) { return `<article class="card"><span class="label">${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`; }
function chart(id, points, format, color) {
  if (!points.length) { $(id).textContent="O gráfico aparece após o primeiro turno."; return; }
  const max=Math.max(...points,0.000001), width=580, height=145;
  const path=points.map((v,i)=>`${i ? "L":"M"}${45+i*(width-60)/Math.max(1,points.length-1)},${15+(1-v/max)*95}`).join(" ");
  $(id).innerHTML=`<svg viewBox="0 0 580 145" role="img" aria-label="${esc(id==='latency-chart'?'Latência dos turnos recentes':'Custo conhecido acumulado dos turnos recentes')}"><path d="M45,15 H570 M45,62 H570 M45,110 H570" stroke="currentColor" opacity=".08" fill="none"/><path d="${path}" fill="none" stroke="${color}" stroke-width="2.5"/><text x="0" y="18" class="chart-label">${esc(format(max))}</text><text x="45" y="140" class="chart-label">Mais antigo</text><text x="500" y="140" class="chart-label">Mais recente</text></svg>`;
}
function render(d) {
  latest=d; const s=d.summary;
  $("slo").className="slo"+(d.slo.ok==null ? "" : d.slo.ok ? " good":" bad");
  $("slo-title").textContent=d.slo.ok==null ? "Pronto para observar" : d.slo.ok ? "Dentro dos objetivos de serviço" : "Um objetivo precisa de atenção";
  $("slo-badge").textContent=d.slo.ok==null ? "Sem amostras" : d.slo.ok ? "SLO atendido":"SLO excedido";
  $("slo-description").textContent=`p95 até ${ms(d.slo.p95_limit_ms)} · erros até ${percent(d.slo.error_rate_limit)} · ${d.window_days} dia(s). Bloqueios de segurança não são falhas técnicas.`;
  $("cards").innerHTML=[card("Turnos observados",integer(s.requests),`${s.in_progress_this_process} em andamento neste processo`),card("Latência p95",ms(s.latency_p95_ms),`p50 ${ms(s.latency_p50_ms)} · p99 ${ms(s.latency_p99_ms)}`),card("Índice de erros",percent(s.error_rate),`${s.errors} falhas técnicas · ${s.blocked_input+s.blocked_output} bloqueios`),card("Custo conhecido",money(s.known_cost_usd),`${s.cost_partial?"Parcial · ":""}cobertura ${percent(s.cost_coverage)}`),card("Custo por resolução",money(s.cost_per_resolution_usd),`${s.confirmed_resolutions} resoluções confirmadas · ${s.feedback_count} avaliações${s.cost_partial?" · custo parcial":""}`),card("ROI por tempo",percent(s.roi),s.roi==null ? "Informe benefício e confirme resoluções" : `Benefício estimado ${money(s.benefit_usd)}`)].join("");
  const chronological=[...d.traces].reverse();
  chart("latency-chart",chronological.filter(t=>t.operation==="chat").map(t=>t.duration_ms),ms,"#02c1d6");
  let cumulative=0; chart("cost-chart",chronological.map(t=>(cumulative+=t.known_cost_usd)),money,"#2dbc93");
  $("stages").innerHTML=table(["Etapa / dependência","Tipo","Execuções","Média","p95","Erros"],d.by_stage.map(x=>[esc(x.name),esc(x.kind),integer(x.calls),ms(x.mean_ms),ms(x.p95_ms),integer(x.errors)]));
  $("models").innerHTML=table(["Modelo","Chamadas","Tokens entrada","Tokens saída","Custo conhecido","Sem custo aferível","Erros"],d.by_model.map(x=>[esc(x.model),integer(x.calls),integer(x.input_tokens),integer(x.output_tokens),money(x.cost_usd),integer(x.missing_usage),integer(x.errors)]));
  const a=d.assumptions;
  $("basis").textContent=`Base: ${a.cost_basis==='observed'?'custo médio observado por turno':'simulação de tokens do modelo principal'}. Resolução: ${a.resolution_rate_basis==='assumed'?'taxa assumida':'confirmações divididas por todos os turnos'} (${percent(a.resolution_rate)}). ${s.cost_partial?'Há chamadas sem custo aferível; os valores são parciais. ':''}${a.cost_basis==='planning'?'Sem histórico, JEV, embeddings e fallback não estão incluídos. ':''}${d.truncated?'Limite de 20.000 registros atingido: reduza a janela.':''}`;
  $("scenarios").innerHTML=d.scenarios.map(x=>`<article class="scenario"><p class="eyebrow">CENÁRIO SEMANAL</p><h3>${integer(x.weekly_users)} usuários</h3><strong>${esc(money(x.estimated_cost_usd))}</strong><span class="muted small"> / semana</span><dl><dt>Turnos previstos</dt><dd>${integer(x.weekly_turns)}</dd><dt>Resoluções estimadas</dt><dd>${integer(x.estimated_resolutions)}</dd><dt>Custo por resolução</dt><dd>${esc(money(x.cost_per_resolution_usd))}</dd><dt>Tempo convertido em benefício</dt><dd>${esc(money(x.estimated_benefit_usd))}</dd><dt>Retorno líquido</dt><dd>${esc(money(x.net_return_usd))}</dd><dt>ROI estimado</dt><dd>${percent(x.roi)}</dd></dl></article>`).join("");
  $("pricing").textContent=`Tabela consultada em ${d.pricing.as_of}. ${d.pricing.policy} Embeddings sem usage exposto e tentativas com consumo desconhecido aparecem como custo não aferível. Inclua hospedagem, banco e demais despesas no custo fixo. Fallbacks: ${s.fallback_calls} chamadas em ${s.fallback_turns} turnos. FAQ sem evidência: ${s.faq_no_evidence}. Rejeições do juiz: ${s.judge_rejected}.`;
  $("turns").innerHTML=table(["Turno","Rota","Resultado","Tempo total","Custo","Ação"],d.traces.map(t=>[`${esc(date(t.created))}<br><code>${esc(t.id)}</code>`,esc(t.route),`<span class="state ${t.http_status>=500||t.degraded?'error':t.outcome.startsWith('bloqueado')?'neutral':''}">${esc(t.http_status>=500?'erro HTTP '+t.http_status:t.outcome)}</span>`,ms(t.duration_ms),esc(money(t.known_cost_usd))+(t.cost_partial?' *':''),`<button type="button" class="quiet trace-open" data-id="${esc(t.id)}">Ver etapas <span class="icon icon-chevron-right" aria-hidden="true"></span></button>`]));
  if(selected) showTrace(selected);
}
function showTrace(id, focus = false) {
  selected=id; const t=latest.traces.find(x=>x.id===id); if(!t){$("detail").hidden=true;return;}
  const eligible=t.http_status===200&&!t.degraded&&t.outcome==='respondido';
  $("detail").hidden=false;
  $("detail").innerHTML=`<h3>Etapas do turno</h3><code>${esc(t.id)}</code><p class="muted small">A posição indica o início relativo. Barras podem se sobrepor quando há concorrência.</p>${t.spans.map(s=>`<div class="track"><span>${esc(s.name)}${s.error?' · '+esc(s.error):''}</span><div class="track-area"><span class="bar ${s.error?'failed':''}" style="left:${Math.min(100,s.start_ms/Math.max(1,t.duration_ms)*100)}%;width:${Math.min(100,s.duration_ms/Math.max(1,t.duration_ms)*100)}%"></span></div><span>${ms(s.duration_ms)}</span></div>`).join("")}<h3>Intervalos entre etapas</h3><p class="muted small">${t.handoffs.map(h=>`${esc(h.from)} <span class="icon icon-chevron-right" role="img" aria-label="para"></span> ${esc(h.to)}: ${ms(h.gap_ms)}`).join(' · ')||'Nenhuma transição registrada.'}</p><div class="feedback">${eligible?`<span>Confirmação de resolução: ${t.resolved==null?'pendente':t.resolved?'resolveu':'não resolveu'}</span><button type="button" data-feedback="true" data-id="${esc(t.id)}">Resolveu</button><button class="quiet" type="button" data-feedback="false" data-id="${esc(t.id)}">Não resolveu</button>`:'Este turno não é elegível para confirmar uma resolução.'}</div>`;
  if (focus) $("detail").focus();
}
async function load() {
  if(loading)return; loading=true; clearTimeout(timer); $("refresh").disabled=true;
  const query=new URLSearchParams(new FormData($("assumptions"))); query.set('days',$("days").value);
  for(const [k,v] of [...query]) if(v==='')query.delete(k);
  try {
    const r=await fetch('/monitor?'+query,{cache:'no-store'});
    if(!r.ok){
      const problem = await r.json().catch(() => null);
      throw new Error(typeof problem?.detail === 'string' ? problem.detail : 'Falha ao ler métricas: HTTP '+r.status);
    }
    render(await r.json()); $("error").hidden=true; document.body.classList.remove('stale');
    $("updated").textContent='Atualizado às '+new Date().toLocaleTimeString('pt-BR')+' · a cada 10 s';
  }catch(e){$("error").hidden=false;$("error").textContent=e.message;document.body.classList.add('stale');$("updated").textContent='Dados indisponíveis ou desatualizados';}
  finally{loading=false;$("refresh").disabled=false;timer=setTimeout(()=>{if(!document.hidden)load();else timer=setTimeout(load,10000);},10000);}
}
$("assumptions").addEventListener('submit',e=>{e.preventDefault();load();});
$("refresh").addEventListener('click',load);$("days").addEventListener('change',load);
$("theme").addEventListener('click',()=>{
  const dark = document.documentElement.dataset.theme !== 'dark';
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  $("theme").setAttribute('aria-pressed', String(dark));
});
$("turns").addEventListener('click',e=>{const b=e.target.closest('.trace-open');if(b)showTrace(b.dataset.id, true);});
$("detail").addEventListener('click',async e=>{
  const b=e.target.closest('[data-feedback]');if(!b)return;b.disabled=true;
  try {const r=await fetch('/monitor/feedback/'+encodeURIComponent(b.dataset.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resolved:b.dataset.feedback==='true'})});if(!r.ok)throw new Error('Não foi possível registrar a confirmação: HTTP '+r.status);await load();}
  catch(err){$("error").hidden=false;$("error").textContent=err.message;}finally{b.disabled=false;}
});
load();
