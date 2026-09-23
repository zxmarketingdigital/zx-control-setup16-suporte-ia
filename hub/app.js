/* Hub de Suporte — SPA sem build. Dados externos são sempre inseridos com textContent. */
(function () {
  "use strict";

  var cfg = window.SUPORTE_CONFIG || {};
  var supabaseLib = window.supabase;
  var client = null;
  var state = {
    session: null, user: null, member: null, members: [], tickets: [], currentTicket: null,
    messages: [], activeStatus: "aberto", ticketSort: "priority", realtime: null, polling: null,
    loadingTickets: false
  };
  var statusNames = { aberto: "Abertos", em_atendimento: "Em atendimento", aguardando_cliente: "Aguardando cliente", resolvido: "Resolvidos" };
  var priorityNames = { baixa: "Baixa", normal: "Normal", alta: "Alta" };
  var $ = function (id) { return document.getElementById(id); };
  var make = function (tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  var clear = function (node) { while (node && node.firstChild) node.removeChild(node.firstChild); };
  var setHidden = function (node, hidden) { if (node) node.hidden = hidden; };
  var setStatus = function (node, text, error) { if (node) { node.textContent = text || ""; node.classList.toggle("form-error", !!error); } };
  var escapePath = function (value) { return String(value || "").replace(/[^a-zA-Z0-9_-]/g, ""); };
  var nowMs = function (value) { var t = Date.parse(value || ""); return isNaN(t) ? 0 : t; };
  var formatDate = function (value) {
    var t = nowMs(value);
    return t ? new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(t)) : "—";
  };
  var waitText = function (value) {
    var t = nowMs(value); if (!t) return "";
    var minutes = Math.max(0, Math.floor((Date.now() - t) / 60000));
    if (minutes < 60) return minutes + " min de espera";
    var hours = Math.floor(minutes / 60); return hours + " h de espera";
  };
  var isRecent = function (value, days) { var t = nowMs(value); return t >= Date.now() - days * 86400000; };
  var errorText = function (error) { return error && error.message ? error.message : "Não foi possível concluir a operação."; };

  function showAuth(kind) {
    setHidden($("login-view"), kind !== "login"); setHidden($("no-access-view"), kind !== "no-access"); setHidden($("hub-view"), kind !== "hub");
  }

  function showPage(id) {
    document.querySelectorAll(".page-view").forEach(function (view) { view.hidden = view.id !== id; });
    document.querySelectorAll(".nav-item").forEach(function (button) { button.classList.toggle("active", button.dataset.view === id); });
    if (id === "queue-view") loadTickets();
    if (id === "learn-view") loadCandidates();
    if (id === "kb-view") loadKB();
    if (id === "dashboard-view") loadDashboard();
  }

  function statusLabel(value) { return statusNames[value] || value || "—"; }
  function priorityLabel(value) { return priorityNames[value] || value || "—"; }

  function fnUrl() { return String(cfg.supabaseUrl || "").replace(/\/$/, "") + "/functions/v1/support-ai"; }
  async function callFunction(body) {
    if (!state.session) throw new Error("Sua sessão expirou. Entre novamente.");
    var response = await fetch(fnUrl(), { method: "POST", headers: { "Content-Type": "application/json", apikey: cfg.anonKey || "", Authorization: "Bearer " + state.session.access_token }, body: JSON.stringify(body) });
    var data = null; try { data = await response.json(); } catch (ignore) {}
    if (!response.ok) throw new Error(data && (data.erro || data.error || data.message) || "A função de suporte recusou a operação.");
    return data || {};
  }

  async function handleLogin(event) {
    event.preventDefault();
    var form = event.currentTarget; var email = form.elements.email.value.trim(); var password = form.elements.password.value;
    setStatus($("login-error"), "Entrando…", false); setHidden($("login-error"), false);
    var result = await client.auth.signInWithPassword({ email: email, password: password });
    if (result.error) { setStatus($("login-error"), errorText(result.error), true); return; }
    setHidden($("login-error"), true); await enterHub(result.data.session);
  }

  async function enterHub(session) {
    if (!session) { showAuth("login"); return; }
    state.session = session; state.user = session.user;
    var memberResult = await client.from("sup_equipe").select("user_id,nome,papel").eq("user_id", session.user.id).maybeSingle();
    if (memberResult.error || !memberResult.data) { showAuth("no-access"); return; }
    state.member = memberResult.data; showAuth("hub");
    $("business-name").textContent = cfg.negocioNome || "Hub de Suporte"; $("current-user").textContent = state.member.nome || session.user.email || "Usuário";
    document.documentElement.style.setProperty("--acento", cfg.cor || "#7C3AED");
    await Promise.all([loadMembers(), loadTickets()]); setupRealtime();
  }

  async function signOut() { if (state.realtime) { client.removeChannel(state.realtime); state.realtime = null; } if (state.polling) { window.clearInterval(state.polling); state.polling = null; } await client.auth.signOut(); state.session = null; state.member = null; showAuth("login"); }

  async function loadMembers() {
    var result = await client.from("sup_equipe").select("user_id,nome,papel").order("nome");
    if (!result.error) { state.members = result.data || []; renderAssignees(); }
  }

  function setupRealtime() {
    if (!client || state.realtime) return;
    try { state.realtime = client.channel("sup-tickets-hub").on("postgres_changes", { event: "*", schema: "public", table: "sup_tickets" }, function () { loadTickets(); }).subscribe(); } catch (ignore) { state.realtime = null; }
    state.polling = window.setInterval(function () { if (state.session && !document.hidden) loadTickets(); }, 20000);
  }

  function renderTabs() {
    var box = $("queue-tabs"); clear(box);
    ["aberto", "em_atendimento", "aguardando_cliente", "resolvido"].forEach(function (value) {
      var button = make("button", "tab" + (state.activeStatus === value ? " active" : "")); button.type = "button"; button.setAttribute("role", "tab");
      button.appendChild(document.createTextNode(statusLabel(value) + " "));
      var count = make("span", "tab-count", state.tickets.filter(function (ticket) { return ticket.status === value; }).length); button.appendChild(count);
      button.addEventListener("click", function () { state.activeStatus = value; renderTabs(); renderTickets(); }); box.appendChild(button);
    });
  }

  async function loadTickets() {
    if (!state.session) return;
    if (state.loadingTickets) return; state.loadingTickets = true; setStatus($("queue-status"), "Atualizando fila…", false);
    try {
      var rows = []; var offset = 0; var pageSize = 1000;
      while (true) { var result = await client.from("sup_tickets").select("*").order("created_at", { ascending: true }).range(offset, offset + pageSize - 1); if (result.error) throw result.error; var page = result.data || []; rows = rows.concat(page); if (page.length < pageSize) break; offset += pageSize; }
      state.tickets = rows; renderTabs(); renderTickets(); $("nav-open-count").textContent = state.tickets.filter(function (t) { return t.status !== "resolvido"; }).length; setStatus($("queue-status"), "", false);
    } catch (error) { setStatus($("queue-status"), errorText(error), true); } finally { state.loadingTickets = false; }
  }

  function renderTickets() {
    var list = $("ticket-list"); clear(list); var query = ($("ticket-search").value || "").toLocaleLowerCase();
    var filtered = state.tickets.filter(function (ticket) { var text = ((ticket.contato_nome || "") + " " + (ticket.assunto || "")).toLocaleLowerCase(); return ticket.status === state.activeStatus && (!query || text.indexOf(query) >= 0); });
    filtered.sort(function (a, b) {
      if (state.ticketSort === "oldest") return nowMs(a.created_at) - nowMs(b.created_at);
      if (state.ticketSort === "newest") return nowMs(b.created_at) - nowMs(a.created_at);
      var weight = { alta: 0, normal: 1, baixa: 2 }; var aWeight = weight[a.prioridade] === undefined ? 1 : weight[a.prioridade]; var bWeight = weight[b.prioridade] === undefined ? 1 : weight[b.prioridade]; return aWeight - bWeight || nowMs(a.created_at) - nowMs(b.created_at);
    });
    if (!filtered.length) { list.appendChild(make("div", "empty-state", query ? "Nenhum ticket corresponde à busca." : "Não há tickets nesta aba.")); return; }
    filtered.forEach(function (ticket) {
      var card = make("button", "ticket-card"); card.type = "button"; card.setAttribute("aria-label", "Abrir ticket " + (ticket.assunto || "sem assunto"));
      var main = make("span", "ticket-card-main"); main.appendChild(make("h2", "", ticket.assunto || "Sem assunto")); main.appendChild(make("p", "", ticket.contato_nome || ticket.contato_whatsapp || "Contato sem nome"));
      var badges = make("span", "ticket-card-meta"); badges.appendChild(make("span", "badge channel", ticket.canal || "—")); badges.appendChild(make("span", "badge" + (ticket.prioridade === "alta" ? " high" : ""), priorityLabel(ticket.prioridade))); badges.appendChild(make("span", "badge", statusLabel(ticket.status))); main.appendChild(badges);
      card.appendChild(main); card.appendChild(make("span", "waiting", waitText(ticket.created_at))); card.addEventListener("click", function () { openTicket(ticket.id); }); list.appendChild(card);
    });
  }

  async function openTicket(id) {
    var ticket = state.tickets.find(function (item) { return item.id === id; }); if (!ticket) return;
    state.currentTicket = ticket; $("ticket-number").textContent = ticket.numero ? "#" + ticket.numero : ""; $("ticket-subject").textContent = ticket.assunto || "Sem assunto";
    $("ticket-meta").textContent = (ticket.contato_nome || "Contato sem nome") + " · " + (ticket.canal || "—") + " · criado em " + formatDate(ticket.created_at);
    $("ticket-status").value = ticket.status || "aberto"; $("ticket-priority").value = ticket.prioridade || "normal"; renderAssignees(ticket.atribuido_a); $("ai-suggestion").textContent = ticket.sugestao_ia || "Nenhuma sugestão disponível."; setHidden($("use-suggestion"), !ticket.sugestao_ia); setStatus($("reply-status"), "", false); $("reply-content").value = "";
    showPage("ticket-view"); clear($("conversation")); $("conversation").appendChild(make("p", "loading", "Carregando conversa…"));
    var result = await client.from("sup_mensagens").select("*").eq("ticket_id", id).order("created_at", { ascending: true });
    if (result.error) { clear($("conversation")); $("conversation").appendChild(make("p", "form-error", errorText(result.error))); return; }
    if (!state.currentTicket || state.currentTicket.id !== id) return; state.messages = result.data || []; renderConversation();
  }

  function renderConversation() {
    var box = $("conversation"); clear(box); if (!state.messages.length) { box.appendChild(make("p", "empty-state", "Ainda não há mensagens vinculadas.")); return; }
    state.messages.forEach(function (message) { var bubble = make("article", "message " + (message.autor || "cliente")); bubble.appendChild(make("span", "message-author", message.autor === "ia" ? "IA" : message.autor === "humano" ? "Equipe" : "Cliente")); bubble.appendChild(make("div", "message-content", message.conteudo)); bubble.appendChild(make("time", "message-time", formatDate(message.created_at))); box.appendChild(bubble); }); box.scrollTop = box.scrollHeight;
  }

  function renderAssignees(selected) {
    var select = $("ticket-assignee"); if (!select) return; clear(select); var unassigned = document.createElement("option"); unassigned.value = ""; unassigned.textContent = "Sem atribuição"; select.appendChild(unassigned);
    state.members.forEach(function (member) { var option = document.createElement("option"); option.value = member.user_id; option.textContent = member.nome || member.user_id; select.appendChild(option); }); if (selected !== undefined) select.value = selected || "";
  }

  async function updateCurrentTicket(field, value) {
    if (!state.currentTicket) return; var update = {}; update[field] = value || null; if (field === "status" && value === "resolvido") update.resolvido_em = new Date().toISOString();
    var result = await client.from("sup_tickets").update(update).eq("id", state.currentTicket.id).select("*").single(); if (result.error) { setStatus($("reply-status"), errorText(result.error), true); return; }
    state.currentTicket = result.data; await loadTickets(); setStatus($("reply-status"), "Ticket atualizado.", false);
  }

  async function submitReply(event) {
    event.preventDefault(); if (!state.currentTicket) return; var content = $("reply-content").value.trim(); if (!content) return;
    $("reply-button").disabled = true; setStatus($("reply-status"), "Enviando resposta…", false);
    try { var data = await callFunction({ acao: "responder_humano", ticket_id: state.currentTicket.id, conteudo: content }); if (data.enviado === false) throw new Error("A resposta não foi enviada."); await openTicket(state.currentTicket.id); setStatus($("reply-status"), "Resposta enviada.", false); } catch (error) { setStatus($("reply-status"), errorText(error), true); } finally { $("reply-button").disabled = false; }
  }

  async function requestSuggestion() {
    if (!state.currentTicket) return; $("new-suggestion").disabled = true; setStatus($("reply-status"), "Gerando sugestão…", false);
    try { var data = await callFunction({ acao: "sugerir", ticket_id: state.currentTicket.id }); var suggestion = data.sugestao || data.resposta || data.sugestao_ia || "Nenhuma sugestão foi retornada."; $("ai-suggestion").textContent = suggestion; setHidden($("use-suggestion"), false); } catch (error) { setStatus($("reply-status"), errorText(error), true); } finally { $("new-suggestion").disabled = false; }
  }

  async function loadCandidates() {
    var box = $("candidate-list"); clear(box); box.appendChild(make("p", "loading", "Carregando candidatas…"));
    var result = await client.from("sup_kb_candidatas").select("*").eq("status", "pendente").order("ocorrencias", { ascending: false }); clear(box);
    if (result.error) { box.appendChild(make("p", "form-error", errorText(result.error))); return; } if (!result.data || !result.data.length) { box.appendChild(make("div", "empty-state", "Nenhuma candidata pendente.")); return; }
    result.data.forEach(function (candidate) {
      var card = make("article", "candidate-card"); var header = make("div", "candidate-header"); var heading = make("div"); heading.appendChild(make("h2", "", candidate.pergunta)); heading.appendChild(make("p", "", (candidate.ocorrencias || 1) + " ocorrência(s)")); header.appendChild(heading); header.appendChild(make("span", "badge", formatDate(candidate.updated_at || candidate.created_at))); card.appendChild(header);
      var edit = make("div", "candidate-edit"); var label = make("label", "", "Resposta sugerida"); var textarea = document.createElement("textarea"); textarea.rows = 4; textarea.maxLength = 4000; textarea.value = candidate.resposta_sugerida || ""; label.appendChild(textarea); edit.appendChild(label); if (candidate.contexto) edit.appendChild(make("p", "", candidate.contexto)); card.appendChild(edit);
      var actions = make("div", "candidate-actions"); var reject = make("button", "button secondary", "Rejeitar"); reject.type = "button"; var approve = make("button", "button primary", "Aprovar na base"); approve.type = "button"; reject.addEventListener("click", function () { updateCandidate(candidate, "rejeitada"); }); approve.addEventListener("click", function () { approveCandidate(candidate, textarea.value.trim()); }); actions.appendChild(reject); actions.appendChild(approve); card.appendChild(actions); box.appendChild(card);
    });
  }
  async function updateCandidate(candidate, status) { var result = await client.from("sup_kb_candidatas").update({ status: status }).eq("id", candidate.id); if (result.error) window.alert(errorText(result.error)); else loadCandidates(); }
  async function approveCandidate(candidate, answer) { if (!answer) { window.alert("Escreva uma resposta antes de aprovar."); return; } var existing = await client.from("sup_kb").select("id").eq("pergunta", candidate.pergunta).limit(1); if (existing.error) { window.alert(errorText(existing.error)); return; } if (!existing.data || !existing.data.length) { var insert = await client.from("sup_kb").insert({ tema: "Perguntas recorrentes", pergunta: candidate.pergunta, resposta: answer, fonte: "base que aprende" }); if (insert.error) { window.alert(errorText(insert.error)); return; } } else { var refresh = await client.from("sup_kb").update({ resposta: answer, ativo: true }).eq("id", existing.data[0].id); if (refresh.error) { window.alert(errorText(refresh.error)); return; } } var update = await client.from("sup_kb_candidatas").update({ status: "aprovada", resposta_sugerida: answer }).eq("id", candidate.id); if (update.error) window.alert(errorText(update.error)); else loadCandidates(); }

  async function loadKB() {
    var box = $("kb-list"); clear(box); box.appendChild(make("p", "loading", "Carregando base…")); var query = ($("kb-search").value || "").trim().toLocaleLowerCase(); var result = await client.from("sup_kb").select("*").order("updated_at", { ascending: false }); clear(box);
    if (result.error) { box.appendChild(make("p", "form-error", errorText(result.error))); return; } var items = (result.data || []).filter(function (item) { if (!query) return true; return [item.tema, item.pergunta, item.resposta].some(function (value) { return String(value || "").toLocaleLowerCase().indexOf(query) >= 0; }); }); if (!items.length) { box.appendChild(make("div", "empty-state", "Nenhum item encontrado.")); return; }
    items.forEach(function (item) {
      var card = make("article", "kb-card"); card.appendChild(make("span", "badge", item.ativo ? "Ativo" : "Desativado")); card.appendChild(make("h2", "", item.pergunta)); card.appendChild(make("p", "", item.tema || "Sem tema"));
      var edit = make("div", "kb-edit"); var theme = document.createElement("input"); theme.value = item.tema || ""; theme.setAttribute("aria-label", "Tema"); var answer = document.createElement("textarea"); answer.value = item.resposta || ""; answer.rows = 4; answer.setAttribute("aria-label", "Resposta"); edit.appendChild(theme); edit.appendChild(answer); card.appendChild(edit); var actions = make("div", "kb-actions"); var save = make("button", "button primary", "Salvar"); save.type = "button"; var toggle = make("button", "button secondary", item.ativo ? "Desativar" : "Ativar"); toggle.type = "button"; save.addEventListener("click", function () { saveKB(item, theme.value.trim(), answer.value.trim()); }); toggle.addEventListener("click", function () { saveKB(item, item.tema, item.resposta, !item.ativo); }); actions.appendChild(toggle); actions.appendChild(save); card.appendChild(actions); box.appendChild(card);
    });
  }
  async function saveKB(item, tema, resposta, ativo) { var patch = { tema: tema, resposta: resposta }; if (ativo !== undefined) patch.ativo = ativo; var result = await client.from("sup_kb").update(patch).eq("id", item.id); if (result.error) window.alert(errorText(result.error)); else loadKB(); }

  function metric(label, value) { var card = make("div", "metric-card"); card.appendChild(make("span", "metric-label", label)); card.appendChild(make("strong", "metric-value", value)); return card; }
  async function loadDashboard() {
    var box = $("dashboard-cards"); clear(box); box.appendChild(make("p", "loading", "Calculando indicadores…")); var since = new Date(Date.now() - 7 * 86400000).toISOString();
    var results = await Promise.all([client.from("sup_mensagens").select("autor,created_at,conversa_id,ticket_id").gte("created_at", since), client.from("sup_tickets").select("status,created_at,resolvido_em,conversa_id").gte("created_at", since), client.from("sup_uso_ia").select("etapa,custo_usd,created_at,erro").gte("created_at", since)]); clear(box); if (results.some(function (r) { return r.error; })) { box.appendChild(make("p", "form-error", "Não foi possível carregar todos os indicadores.")); return; }
    var messages = results[0].data || [], tickets = results[1].data || [], usage = results[2].data || []; var conversations = new Set(messages.map(function (m) { return m.conversa_id; })).size; var aiResolved = new Set(messages.filter(function (m) { return m.autor === "ia" && !m.ticket_id; }).map(function (m) { return m.conversa_id; })).size; var strong = usage.filter(function (u) { return u.etapa === "forte"; }).length; var cost = usage.reduce(function (sum, u) { return sum + Number(u.custo_usd || 0); }, 0); var todayTickets = tickets.filter(function (t) { return isRecent(t.created_at, 1); }).length; var firstClient = {}; var firstHuman = {};
    messages.forEach(function (message) { var key = message.ticket_id || message.conversa_id; if (!key) return; var time = nowMs(message.created_at); if (!time) return; if (message.autor === "cliente" && (!firstClient[key] || time < firstClient[key])) firstClient[key] = time; if (message.autor === "humano" && (!firstHuman[key] || time < firstHuman[key])) firstHuman[key] = time; });
    var responseTimes = Object.keys(firstHuman).map(function (key) { return firstClient[key] ? firstHuman[key] - firstClient[key] : 0; }).filter(function (value) { return value >= 0; }); var averageResponse = responseTimes.length ? Math.round(responseTimes.reduce(function (sum, value) { return sum + value; }, 0) / responseTimes.length / 60000) + " min" : "—";
    box.appendChild(metric("Conversas · 7 dias", conversations)); box.appendChild(metric("Resolvidas pela IA", conversations ? Math.round((aiResolved / conversations) * 100) + "%" : "—")); box.appendChild(metric("Tickets novos hoje", todayTickets)); box.appendChild(metric("Tickets em aberto", state.tickets.filter(function (t) { return t.status !== "resolvido"; }).length)); box.appendChild(metric("Custo de IA · 7 dias", "$" + cost.toFixed(4))); box.appendChild(metric("Degrau forte", usage.length ? Math.round((strong / usage.length) * 100) + "%" : "—")); box.appendChild(metric("1ª resposta humana", averageResponse));
  }

  function bind() {
    $("login-form").addEventListener("submit", handleLogin); $("logout-button").addEventListener("click", signOut); $("no-access-logout").addEventListener("click", signOut); $("back-to-queue").addEventListener("click", function () { showPage("queue-view"); }); $("refresh-queue").addEventListener("click", loadTickets); $("ticket-refresh").addEventListener("click", function () { if (state.currentTicket) openTicket(state.currentTicket.id); }); $("ticket-search").addEventListener("input", renderTickets); $("ticket-sort").addEventListener("change", function (event) { state.ticketSort = event.target.value; renderTickets(); }); $("reply-form").addEventListener("submit", submitReply); $("new-suggestion").addEventListener("click", requestSuggestion); $("use-suggestion").addEventListener("click", function () { $("reply-content").value = $("ai-suggestion").textContent || ""; $("reply-content").focus(); }); $("ticket-status").addEventListener("change", function (event) { updateCurrentTicket("status", event.target.value); }); $("ticket-priority").addEventListener("change", function (event) { updateCurrentTicket("prioridade", event.target.value); }); $("ticket-assignee").addEventListener("change", function (event) { updateCurrentTicket("atribuido_a", event.target.value); }); $("refresh-candidates").addEventListener("click", loadCandidates); $("refresh-kb").addEventListener("click", loadKB); $("kb-search").addEventListener("input", loadKB); $("refresh-dashboard").addEventListener("click", loadDashboard); document.querySelectorAll(".nav-item").forEach(function (button) { button.addEventListener("click", function () { showPage(button.dataset.view); }); });
  }

  async function boot() {
    if (!supabaseLib || !cfg.supabaseUrl || !cfg.anonKey) { showAuth("login"); setStatus($("login-error"), "Configuração ausente: gere hub/config.js na Etapa 4.", true); setHidden($("login-error"), false); return; }
    client = supabaseLib.createClient(cfg.supabaseUrl, cfg.anonKey); bind(); var result = await client.auth.getSession(); if (result.data && result.data.session) await enterHub(result.data.session); else showAuth("login"); client.auth.onAuthStateChange(function (event, session) { if (event === "TOKEN_REFRESHED" && session) state.session = session; else if (event === "SIGNED_OUT") showAuth("login"); else if (event === "SIGNED_IN" && session && !state.member) enterHub(session); });
  }
  boot();
}());
