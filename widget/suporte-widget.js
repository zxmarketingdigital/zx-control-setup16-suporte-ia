/* Central de atendimento com IA: identificação → chat com a IA → ticket com a equipe.
 * Isolada em Shadow DOM, sem dependências. Dois modos:
 *   - flutuante (padrão): botão no canto da página abre a janela de atendimento;
 *   - página (data-modo="pagina"): ocupa o elemento #suporte-atendimento (ou o body).
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script) return;
  var data = script.dataset || {};
  var endpoint = String(data.endpoint || "").replace(/\/$/, "");
  var anonKey = data.anonKey || "";
  var title = data.titulo || "Central de atendimento";
  var subtitle = data.subtitulo || "Tire sua dúvida ou fale com a gente";
  var color = /^#[0-9a-fA-F]{3,8}$/.test(data.cor || "") ? data.cor : "#7C3AED";
  var pageMode = data.modo === "pagina";
  if (!endpoint) return;

  var host = document.createElement("div");
  host.setAttribute("data-suporte-widget", "true");
  if (!host.attachShadow) return;
  var mount = pageMode ? (document.getElementById("suporte-atendimento") || document.body) : document.body;
  mount.appendChild(host);
  var root = host.attachShadow({ mode: "open" });

  var css = [
    ":host{all:initial}*{box-sizing:border-box;margin:0}[hidden]{display:none!important}",
    ".wrap{--ac:" + color + ";--bg:#0f0f13;--sf:#17171d;--sf2:#1f1f27;--bd:#2a2a35;--tx:#f2f1f6;--mu:#9d9aab;font:14px/1.5 Inter,system-ui,-apple-system,'Segoe UI',sans-serif;color:var(--tx)}",
    ".launcher{position:fixed;right:22px;bottom:22px;z-index:2147483000;display:flex;align-items:center;gap:8px;height:52px;padding:0 20px 0 16px;border:0;border-radius:999px;background:var(--ac);color:#fff;box-shadow:0 10px 30px rgba(0,0,0,.3);font:600 14px Inter,system-ui,sans-serif;cursor:pointer}",
    ".launcher svg{width:20px;height:20px}",
    ".panel{display:flex;flex-direction:column;overflow:hidden;background:var(--bg);border:1px solid var(--bd)}",
    ".float{position:fixed;right:22px;bottom:88px;z-index:2147483000;width:min(410px,calc(100vw - 24px));height:min(640px,calc(100vh - 110px));border-radius:18px;box-shadow:0 24px 70px rgba(0,0,0,.45)}",
    ".page{width:100%;min-height:100vh;border:0}",
    ".head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 18px;border-bottom:1px solid var(--bd)}",
    ".brand{display:flex;align-items:center;gap:12px;min-width:0}",
    ".logo{flex:0 0 auto;display:grid;place-items:center;width:40px;height:40px;border-radius:13px;background:linear-gradient(135deg,var(--ac),#f59e0b);color:#fff}",
    ".logo svg{width:22px;height:22px}",
    ".brand strong{display:block;font-size:15px;font-weight:700;letter-spacing:-.01em}.brand small{display:block;color:var(--mu);font-size:12.5px}",
    ".close{border:0;background:transparent;color:var(--mu);font-size:24px;line-height:1;cursor:pointer;padding:4px 6px;border-radius:8px}.close:hover{color:var(--tx);background:var(--sf2)}",
    ".body{flex:1;overflow-y:auto;padding:18px}",
    ".page .body{width:100%;max-width:760px;margin:0 auto;padding:28px 16px}",
    ".card{background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:20px}",
    ".gate{max-width:420px;margin:0 auto}.gate h2{font-size:17px;font-weight:700;margin-bottom:4px}.gate p.lead{color:var(--mu);font-size:13px;margin-bottom:16px}",
    "label{display:block;font-size:13px;font-weight:600;margin:12px 0 6px}",
    "input,textarea{width:100%;border:1px solid var(--bd);border-radius:10px;background:var(--sf2);color:var(--tx);padding:10px 12px;font:inherit;outline:none}",
    "input:focus,textarea:focus{border-color:var(--ac);box-shadow:0 0 0 3px color-mix(in srgb,var(--ac) 30%,transparent)}",
    "input::placeholder,textarea::placeholder{color:#6f6c7c}",
    ".btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;border:0;border-radius:10px;padding:10px 16px;background:var(--ac);color:#fff;font:600 14px Inter,system-ui,sans-serif;cursor:pointer}",
    ".btn:disabled{opacity:.55;cursor:not-allowed}.btn.full{width:100%;margin-top:16px}",
    ".btn.ghost{background:transparent;border:1px solid var(--bd);color:var(--tx)}",
    ".note{color:var(--mu);font-size:11.5px;text-align:center;margin-top:12px}",
    ".err{color:#f87171;font-size:12.5px;margin-top:10px}",
    ".chat{display:flex;flex-direction:column;min-height:360px;padding:0;overflow:hidden}",
    ".page .chat{min-height:460px}",
    ".msgs{flex:1;display:flex;flex-direction:column;gap:10px;padding:18px;overflow-y:auto;max-height:52vh}",
    ".float .msgs{max-height:none}",
    ".empty{margin:auto;text-align:center;color:var(--mu);font-size:13px;max-width:300px}.empty strong{display:block;color:var(--tx);font-size:14px;margin-bottom:4px}",
    ".b{max-width:85%;white-space:pre-wrap;overflow-wrap:anywhere;border-radius:14px;padding:10px 13px;font-size:14px}",
    ".b.ia{align-self:flex-start;background:var(--sf2);border:1px solid var(--bd)}",
    ".b.humano{align-self:flex-start;background:color-mix(in srgb,var(--ac) 16%,var(--sf2));border:1px solid color-mix(in srgb,var(--ac) 45%,transparent)}",
    ".b.cliente{align-self:flex-end;background:var(--ac);color:#fff}",
    ".who{display:block;font-size:11px;font-weight:600;color:var(--mu);margin-bottom:3px}.b.cliente .who{display:none}",
    ".sys{align-self:center;color:var(--mu);font-size:12px;text-align:center;max-width:92%}",
    ".typing{align-self:flex-start;color:var(--mu);font-size:12.5px;font-style:italic}",
    ".composer{display:flex;gap:8px;align-items:flex-end;padding:12px;border-top:1px solid var(--bd);background:var(--sf)}",
    ".composer textarea{resize:none;min-height:44px;max-height:120px}",
    ".foot{color:var(--mu);font-size:11.5px;padding:0 14px 12px;background:var(--sf)}",
    ".cta{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:14px}",
    ".cta h3{font-size:14px;font-weight:600}.cta p{color:var(--mu);font-size:12.5px}",
    ".ticket{display:flex;align-items:center;gap:12px;margin-top:14px;border-color:color-mix(in srgb,var(--ac) 55%,var(--bd))}",
    ".ticket .num{flex:0 0 auto;display:grid;place-items:center;min-width:52px;height:40px;padding:0 8px;border-radius:10px;background:color-mix(in srgb,var(--ac) 22%,transparent);color:#fff;font-weight:700}",
    ".ticket p{color:var(--mu);font-size:12.5px}.ticket strong{font-size:14px}",
    ".ticket .wa{display:inline-flex;margin-top:8px;padding:7px 12px;border-radius:9px;background:#25D366;color:#06301a;font-weight:700;font-size:12.5px;text-decoration:none}",
    ".open-form textarea{min-height:80px;resize:vertical}.open-form .row{display:flex;gap:8px;justify-content:flex-end;margin-top:10px}",
    "@media(max-width:520px){.cta{flex-direction:column;align-items:stretch}.float{right:8px;left:8px;width:auto;bottom:80px;height:calc(100vh - 100px)}.launcher{right:14px;bottom:14px}}"
  ].join("");
  var style = document.createElement("style");
  style.textContent = css;
  root.appendChild(style);

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  var ICON_CHAT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  var ICON_BUOY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/><path d="m4.93 4.93 4.24 4.24M14.83 14.83l4.24 4.24M14.83 9.17l4.24-4.24M4.93 19.07l4.24-4.24"/></svg>';

  var wrap = el("div", "wrap");
  root.appendChild(wrap);
  var launcher = null;
  if (!pageMode) {
    launcher = el("button", "launcher");
    launcher.type = "button";
    launcher.setAttribute("aria-label", title);
    launcher.setAttribute("aria-expanded", "false");
    launcher.innerHTML = ICON_CHAT;
    launcher.appendChild(el("span", "", "Atendimento"));
    wrap.appendChild(launcher);
  }
  var panel = el("section", "panel " + (pageMode ? "page" : "float"));
  panel.setAttribute("aria-label", title);
  panel.hidden = !pageMode;
  wrap.appendChild(panel);

  var head = el("header", "head");
  var brand = el("div", "brand");
  var logo = el("div", "logo");
  logo.innerHTML = ICON_BUOY;
  var brandText = el("div");
  brandText.appendChild(el("strong", "", title));
  brandText.appendChild(el("small", "", subtitle));
  brand.appendChild(logo);
  brand.appendChild(brandText);
  head.appendChild(brand);
  if (!pageMode) {
    var close = el("button", "close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Fechar atendimento");
    close.addEventListener("click", closePanel);
    head.appendChild(close);
  }
  panel.appendChild(head);
  var body = el("div", "body");
  panel.appendChild(body);

  // ---------- estado persistido ----------
  var KEY_CONV = "suporte_conversa_id", KEY_CONTATO = "suporte_contato", KEY_TICKET = "suporte_ticket";
  function load(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } }
  function save(key, value) { try { if (value === null) window.localStorage.removeItem(key); else window.localStorage.setItem(key, value); } catch (e) {} }
  function newId() {
    try { if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID(); } catch (e) {}
    return "c-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  }
  var conversationId = load(KEY_CONV);
  if (!conversationId || !/^[A-Za-z0-9_-]{1,100}$/.test(conversationId)) { conversationId = newId(); save(KEY_CONV, conversationId); }
  var contact = null;
  try { contact = JSON.parse(load(KEY_CONTATO) || "null"); } catch (e) { contact = null; }
  var ticket = null;
  try { ticket = JSON.parse(load(KEY_TICKET) || "null"); } catch (e) { ticket = null; }

  var busy = false, poll = null, lastSeen = null, seen = {};

  async function request(payload) {
    var response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", apikey: anonKey, Authorization: "Bearer " + anonKey },
      body: JSON.stringify(payload),
    });
    var json = null;
    try { json = await response.json(); } catch (e) {}
    if (!response.ok) throw new Error((json && (json.error || json.erro)) || "Não foi possível falar com o atendimento agora.");
    return json || {};
  }

  // ---------- tela 1: identificação ----------
  function renderGate() {
    body.textContent = "";
    var card = el("div", "card gate");
    card.appendChild(el("h2", "", "Antes de começar 👋"));
    card.appendChild(el("p", "lead", "Precisamos de alguns dados pra te atender e poder acompanhar seu caso."));
    var form = el("form");
    function field(labelText, type, placeholder, autocomplete, value) {
      var id = "f" + Math.random().toString(36).slice(2, 8);
      var label = el("label", "", labelText);
      label.setAttribute("for", id);
      var input = el("input");
      input.id = id; input.type = type; input.placeholder = placeholder; input.autocomplete = autocomplete; input.value = value || "";
      form.appendChild(label); form.appendChild(input);
      return input;
    }
    var nome = field("Nome", "text", "Seu nome completo", "name", contact && contact.nome);
    var email = field("E-mail", "email", "seu@email.com", "email", contact && contact.email);
    var whats = field("WhatsApp", "tel", "+55 11 90000-0000", "tel", contact && contact.whatsapp);
    nome.maxLength = 120; email.maxLength = 160; whats.maxLength = 24;
    var err = el("p", "err"); err.hidden = true;
    var go = el("button", "btn full", "Começar atendimento →");
    go.type = "submit";
    form.appendChild(err); form.appendChild(go);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var n = nome.value.trim(), e = email.value.trim().toLowerCase(), w = whats.value.replace(/\D/g, "");
      var problem = !n ? "Informe seu nome." : !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e) ? "Informe um e-mail válido." :
        (w.length < 8 || w.length > 15) ? "Informe um WhatsApp válido, com DDI e DDD (ex.: +55 11 90000-0000)." : "";
      if (problem) { err.textContent = problem; err.hidden = false; return; }
      contact = { nome: n, email: e, whatsapp: w };
      save(KEY_CONTATO, JSON.stringify(contact));
      renderChat();
    });
    card.appendChild(form);
    card.appendChild(el("p", "note", "Usamos seus dados só para te atender. Nunca pedimos senha nem dados de pagamento por aqui."));
    body.appendChild(card);
    setTimeout(function () { nome.focus(); }, 30);
  }

  // ---------- tela 2: chat + ticket ----------
  var msgs, input, send, ticketBox;
  function renderChat() {
    body.textContent = "";
    seen = {}; lastSeen = null;
    var chat = el("div", "card chat");
    msgs = el("div", "msgs");
    msgs.setAttribute("aria-live", "polite");
    var empty = el("div", "empty");
    empty.appendChild(el("strong", "", "Olá, " + ((contact && contact.nome) || "").split(" ")[0] + "! Como posso ajudar?"));
    empty.appendChild(el("span", "", "Respondo na hora com base nas informações oficiais. Se eu não souber, abro um ticket e a equipe te chama no WhatsApp."));
    msgs.appendChild(empty);
    chat.appendChild(msgs);
    var composer = el("form", "composer");
    input = el("textarea");
    input.rows = 1; input.maxLength = 2000; input.placeholder = "Digite sua dúvida...";
    input.setAttribute("aria-label", "Mensagem");
    send = el("button", "btn", "Enviar");
    send.type = "submit";
    composer.appendChild(input); composer.appendChild(send);
    composer.addEventListener("submit", submit);
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); composer.requestSubmit(); }
    });
    chat.appendChild(composer);
    chat.appendChild(el("p", "foot", "Atendendo como " + contact.nome + " · " + contact.email + ". "));
    var change = el("button", "", "Trocar dados");
    change.type = "button";
    change.style.cssText = "border:0;background:none;color:inherit;text-decoration:underline;cursor:pointer;font:inherit;padding:0";
    change.addEventListener("click", function () { save(KEY_TICKET, null); ticket = null; conversationId = newId(); save(KEY_CONV, conversationId); stopPolling(); renderGate(); });
    chat.lastChild.appendChild(change);
    body.appendChild(chat);
    ticketBox = el("div");
    body.appendChild(ticketBox);
    renderTicketBox();
    loadHistory(true);
    setTimeout(function () { input.focus(); }, 30);
  }

  function clearEmpty() { var e = msgs && msgs.querySelector(".empty"); if (e) e.remove(); }
  function bubble(text, autor, id) {
    if (id) { if (seen[id]) return; seen[id] = true; }
    clearEmpty();
    var node = el("div", "b " + autor);
    if (autor !== "cliente") node.appendChild(el("span", "who", autor === "humano" ? "Equipe" : "Assistente"));
    node.appendChild(document.createTextNode(String(text || "")));
    msgs.appendChild(node);
    msgs.scrollTop = msgs.scrollHeight;
  }
  function sys(text) { clearEmpty(); msgs.appendChild(el("div", "sys", text)); msgs.scrollTop = msgs.scrollHeight; }
  function typing(on) {
    var old = msgs.querySelector(".typing"); if (old) old.remove();
    if (on) { msgs.appendChild(el("div", "typing", "digitando…")); msgs.scrollTop = msgs.scrollHeight; }
  }

  function setTicket(result) {
    if (!result || !result.ticket_id) return;
    var novo = !ticket || ticket.id !== result.ticket_id;
    ticket = { id: result.ticket_id, numero: result.numero || (ticket && ticket.numero) || null,
      whats: result.whatsapp_equipe || (ticket && ticket.whats) || null };
    save(KEY_TICKET, JSON.stringify(ticket));
    renderTicketBox();
    if (novo) sys("Ticket " + (ticket.numero ? "#" + ticket.numero + " " : "") + "aberto");
    startPolling();
  }

  function renderTicketBox() {
    if (!ticketBox) return;
    ticketBox.textContent = "";
    if (ticket) {
      var box = el("div", "card ticket");
      box.appendChild(el("div", "num", ticket.numero ? "#" + ticket.numero : "✓"));
      var t = el("div");
      t.appendChild(el("strong", "", "Seu ticket está com a equipe"));
      var canal = contact && contact.whatsapp ? "no seu WhatsApp" : "no seu e-mail";
      t.appendChild(el("p", "", "Vamos te chamar " + canal + " para resolver. Pode mandar mais detalhes aqui que eles entram no ticket."));
      if (ticket.whats) {
        var direto = el("a", "wa", "Falar agora no WhatsApp");
        direto.href = "https://wa.me/" + String(ticket.whats).replace(/\D/g, "");
        direto.target = "_blank"; direto.rel = "noopener";
        t.appendChild(direto);
      }
      box.appendChild(t);
      ticketBox.appendChild(box);
      return;
    }
    var cta = el("div", "card cta");
    var txt = el("div");
    txt.appendChild(el("h3", "", "Não resolveu?"));
    txt.appendChild(el("p", "", "Abra um ticket e a equipe te chama no WhatsApp para resolver."));
    var open = el("button", "btn", "Abrir ticket");
    open.type = "button";
    open.addEventListener("click", renderOpenForm);
    cta.appendChild(txt); cta.appendChild(open);
    ticketBox.appendChild(cta);
  }

  function renderOpenForm() {
    ticketBox.textContent = "";
    var card = el("form", "card open-form");
    card.style.marginTop = "14px";
    card.appendChild(el("h3", "", "Abrir ticket"));
    var label = el("label", "", "Conte o que você precisa (opcional se já explicou no chat)");
    var area = el("textarea");
    area.maxLength = 2000;
    area.placeholder = "Ex.: quero remarcar minha consulta de sexta.";
    label.appendChild(area);
    card.appendChild(label);
    var err = el("p", "err"); err.hidden = true; card.appendChild(err);
    var row = el("div", "row");
    var cancel = el("button", "btn ghost", "Cancelar"); cancel.type = "button";
    var ok = el("button", "btn", "Confirmar abertura"); ok.type = "submit";
    cancel.addEventListener("click", renderTicketBox);
    row.appendChild(cancel); row.appendChild(ok); card.appendChild(row);
    card.addEventListener("submit", async function (event) {
      event.preventDefault();
      ok.disabled = true; err.hidden = true;
      var texto = area.value.trim();
      try {
        var result = await request({ acao: "abrir_ticket", canal: "site", conversa_id: conversationId, contato: contact, mensagem: texto });
        if (texto) bubble(texto, "cliente");
        if (result.resposta) bubble(result.resposta, "ia");
        setTicket(result);
      } catch (e) {
        err.textContent = e.message; err.hidden = false; ok.disabled = false;
      }
    });
    ticketBox.appendChild(card);
    area.focus();
  }

  async function submit(event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text || busy) return;
    busy = true; send.disabled = true; input.value = "";
    bubble(text, "cliente");
    typing(true);
    try {
      var result = await request({ acao: "mensagem", canal: "site", conversa_id: conversationId, mensagem: text, contato: contact });
      typing(false);
      if (result.resposta) bubble(result.resposta, "ia");
      if (result.escalou || result.ticket_id) setTicket(result);
    } catch (e) {
      typing(false);
      sys(e.message || "Não foi possível enviar agora. Tente novamente.");
    } finally {
      busy = false; send.disabled = false; input.focus();
    }
  }

  async function loadHistory(full) {
    try {
      var payload = { acao: "historico", canal: "site", conversa_id: conversationId };
      if (!full && lastSeen) payload.desde = lastSeen;
      var result = await request(payload);
      var items = Array.isArray(result.mensagens) ? result.mensagens : [];
      items.forEach(function (m) {
        if (m.created_at) lastSeen = m.created_at;
        if (!full && m.autor !== "humano") { if (m.id) seen[m.id] = true; return; }
        bubble(m.conteudo, m.autor === "cliente" || m.autor === "humano" ? m.autor : "ia", m.id);
      });
      if (full && ticket) startPolling();
    } catch (e) {}
  }
  function stopPolling() { if (poll) { window.clearInterval(poll); poll = null; } }
  function startPolling() {
    stopPolling();
    if (!ticket || (!pageMode && panel.hidden)) return;
    poll = window.setInterval(function () { loadHistory(false); }, 8000);
  }

  function openPanel() {
    panel.hidden = false;
    if (launcher) launcher.setAttribute("aria-expanded", "true");
    if (!body.firstChild) { if (contact && contact.nome) renderChat(); else renderGate(); }
    else if (ticket) startPolling();
  }
  function closePanel() {
    panel.hidden = true;
    if (launcher) launcher.setAttribute("aria-expanded", "false");
    stopPolling();
  }
  if (launcher) launcher.addEventListener("click", function () { if (panel.hidden) openPanel(); else closePanel(); });
  if (pageMode) openPanel();
}());
