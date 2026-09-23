import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") || "";
const SERVICE_ROLE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const GEMINI_KEY = Deno.env.get("GEMINI_API_KEY") || "";
const ANTHROPIC_KEY = Deno.env.get("ANTHROPIC_API_KEY") || "";
const EVOLUTION_URL = (Deno.env.get("EVOLUTION_URL") || "").replace(/\/$/, "");
const EVOLUTION_KEY = Deno.env.get("EVOLUTION_API_KEY") || "";
const EVOLUTION_INSTANCE = Deno.env.get("EVOLUTION_INSTANCE") || "";
const WEBHOOK_TOKEN = Deno.env.get("SUPORTE_WEBHOOK_TOKEN") || "";
const ALLOWED_ORIGINS = (Deno.env.get("SUPORTE_ORIGENS") || "")
  .split(",").map((value) => value.trim()).filter(Boolean);
const MODEL_TIMEOUT_MS = 25000;
const MAX_MESSAGE = 2000;
const MAX_CONVERSATION = 100;
const DEFAULT_THRESHOLD = 0.7;
const DEFAULT_DAILY_LIMIT = 2;

const supabase = createClient(SUPABASE_URL, SERVICE_ROLE, {
  auth: { autoRefreshToken: false, persistSession: false },
});

const PRICE_USD_PER_MILLION: Record<string, { input: number; output: number }> = {
  "gemini-flash-lite-latest": { input: 0.1, output: 0.4 },
  "gemini-flash-latest": { input: 0.3, output: 2.5 },
  "gemini-2.5-flash-lite": { input: 0.1, output: 0.4 },
  "gemini-2.5-flash": { input: 0.3, output: 2.5 },
  "gemini-2.0-flash": { input: 0.1, output: 0.4 },
  "claude-haiku-4-5-20251001": { input: 1, output: 5 },
  "claude-sonnet-5": { input: 3, output: 15 },
};
const CONSERVATIVE_PRICE = { input: 1.5, output: 6 };

type ConfigMap = Record<string, unknown>;
type Contact = { nome?: string; email?: string; whatsapp?: string };
type KBItem = { id: string; tema: string; pergunta: string; resposta: string; rank?: number };
type ModelAnswer = {
  resposta: string;
  confianca: number;
  precisa_humano: boolean;
};
type ModelResult = {
  answer: ModelAnswer | null;
  raw: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  error?: string;
};
type EvolutionItem = { remote: string; text: string; eventId?: string };
type EscalationResult = {
  resposta: string; escalou: boolean; ticket_id: string | null; modelo: string | null;
  numero?: number | null; whatsapp_equipe?: string | null;
};

function originAllowed(origin: string | null): boolean {
  if (ALLOWED_ORIGINS.length === 0) return true;
  return !!origin && ALLOWED_ORIGINS.includes(origin);
}

function corsHeaders(origin: string | null): Record<string, string> {
  const allow = ALLOWED_ORIGINS.length === 0 ? "*" : (originAllowed(origin) ? origin || "" : "");
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
    "Content-Type": "application/json; charset=utf-8",
  };
}

function jsonResponse(body: unknown, status: number, origin: string | null): Response {
  return new Response(JSON.stringify(body), { status, headers: corsHeaders(origin) });
}

function constantTimeEqual(left: string, right: string): boolean {
  const a = new TextEncoder().encode(left);
  const b = new TextEncoder().encode(right);
  const length = Math.max(a.length, b.length);
  let difference = a.length ^ b.length;
  for (let index = 0; index < length; index += 1) {
    difference |= (a[index] || 0) ^ (b[index] || 0);
  }
  return difference === 0;
}

function bearer(request: Request): string {
  const value = request.headers.get("authorization") || "";
  return value.toLowerCase().startsWith("bearer ") ? value.slice(7).trim() : "";
}

async function requireTeamUser(request: Request): Promise<{ id: string } | null> {
  const token = bearer(request);
  if (!token) return null;
  const { data, error } = await supabase.auth.getUser(token);
  if (error || !data.user) return null;
  const { data: member, error: memberError } = await supabase
    .from("sup_equipe").select("user_id").eq("user_id", data.user.id).maybeSingle();
  return memberError || !member ? null : { id: data.user.id };
}

async function getConfig(): Promise<ConfigMap> {
  const { data, error } = await supabase.from("sup_config").select("chave,valor");
  if (error) throw new Error(`configuração indisponível: ${error.message}`);
  const result: ConfigMap = {};
  for (const row of data || []) result[row.chave] = row.valor;
  return result;
}

function configString(config: ConfigMap, key: string, fallback: string): string {
  const value = config[key];
  return typeof value === "string" ? value : fallback;
}

function configNumber(config: ConfigMap, key: string, fallback: number): number {
  const value = Number(config[key]);
  return Number.isFinite(value) ? value : fallback;
}

function validText(value: unknown, max: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= max;
}

function cleanContact(value: unknown): Contact | undefined {
  if (!value || typeof value !== "object") return undefined;
  const raw = value as Record<string, unknown>;
  const text = (v: unknown, max: number) => typeof v === "string" && v.trim() ? v.trim().slice(0, max) : undefined;
  const nome = text(raw.nome, 120);
  const emailRaw = text(raw.email, 160);
  const email = emailRaw && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailRaw) ? emailRaw.toLowerCase() : undefined;
  const digits = typeof raw.whatsapp === "string" ? raw.whatsapp.replace(/\D/g, "") : "";
  const whatsapp = digits.length >= 8 && digits.length <= 15 ? digits : undefined;
  return nome || email || whatsapp ? { nome, email, whatsapp } : undefined;
}

function validConversation(value: unknown): value is string {
  // conversa do site = ID aleatório gerado no navegador (randomUUID); curto demais seria adivinhável
  return typeof value === "string" && value.length >= 16 && value.length <= MAX_CONVERSATION &&
    /^[A-Za-z0-9_-]+$/.test(value);
}

function formatPhone(digits: string): string {
  if (digits.startsWith("55") && (digits.length === 12 || digits.length === 13)) {
    const local = digits.slice(4);
    return `(${digits.slice(2, 4)}) ${local.slice(0, local.length - 4)}-${local.slice(-4)}`;
  }
  return `+${digits}`;
}

// Compara números com e sem o 9º dígito brasileiro (o JID do WhatsApp às vezes vem sem ele).
function samePhone(a: string, b: string): boolean {
  const norm = (v: string) => {
    const d = v.replace(/\D/g, "");
    return d.startsWith("55") && d.length === 13 && d[4] === "9" ? d.slice(0, 4) + d.slice(5) : d;
  };
  return norm(a) === norm(b);
}

// Número/WhatsApp do negócio para o cliente falar direto (sup_config.whatsapp_atendimento). Vazio = não mostra.
function teamWhatsapp(config: ConfigMap): string {
  const digits = configString(config, "whatsapp_atendimento", "").replace(/\D/g, "");
  return digits.length >= 8 && digits.length <= 15 ? digits : "";
}

// Texto que o cliente recebe quando a conversa vira ticket: ninguém fica "esperando no chat" —
// a equipe retoma pelo WhatsApp (ou e-mail) do cliente, e ele pode chamar o negócio direto.
function handoffText(
  config: ConfigMap, canal: string, contact: Contact | undefined, numero: number | null | undefined,
  reason: string, existing = false,
): string {
  const ticket = numero ? `ticket #${numero}` : "um ticket";
  const parts: string[] = [];
  if (existing) {
    parts.push(`Anotei sua mensagem no ${ticket}, que já está com a nossa equipe.`);
  } else if (reason === "pedido_cliente" || reason === "pedido_humano") {
    parts.push(`Pronto! Abri o ${ticket} para a nossa equipe.`);
  } else {
    const opener = configString(config, "mensagem_transbordo", "").trim() ||
      "Essa eu não sei responder com segurança e prefiro não te passar uma informação errada.";
    parts.push(`${opener} Por isso abri o ${ticket} para a nossa equipe.`);
  }
  if (canal === "whatsapp") {
    parts.push("Uma pessoa da equipe vai continuar o atendimento aqui mesmo, no WhatsApp.");
  } else if (contact?.whatsapp) {
    parts.push(`Vamos te chamar no WhatsApp ${formatPhone(contact.whatsapp)} para resolver.`);
  } else if (contact?.email) {
    parts.push(`Vamos te responder no e-mail ${contact.email}.`);
  } else {
    parts.push("A equipe vai responder nesta conversa.");
  }
  const team = teamWhatsapp(config);
  if (team && canal !== "whatsapp" && !existing) parts.push(`Se preferir, fale direto com a gente no WhatsApp ${formatPhone(team)}.`);
  return parts.join(" ");
}

function normalizeQuestion(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase().replace(/\s+/g, " ").trim().slice(0, 2000);
}

function extractJson(text: string): ModelAnswer | null {
  const cleaned = text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "").trim();
  const start = cleaned.indexOf("{");
  const end = cleaned.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    const value = JSON.parse(cleaned.slice(start, end + 1));
    if (!value || typeof value.resposta !== "string") return null;
    const confidence = Number(value.confianca);
    if (!Number.isFinite(confidence)) return null;
    if (!value.resposta.trim()) return null;
    return {
      resposta: value.resposta.trim().slice(0, 4000),
      confianca: Math.max(0, Math.min(1, confidence)),
      precisa_humano: Boolean(value.precisa_humano),
    };
  } catch (_) {
    return null;
  }
}

function modelPrice(model: string): { input: number; output: number } {
  return PRICE_USD_PER_MILLION[model] || CONSERVATIVE_PRICE;
}

function modelCost(model: string, input: number, output: number): number {
  const price = modelPrice(model);
  return (Math.max(0, input) * price.input + Math.max(0, output) * price.output) / 1000000;
}

function promptFor(
  config: ConfigMap,
  message: string,
  kb: KBItem[],
  history: Array<{ autor: string; conteudo: string }>,
  contact?: Contact,
): string {
  const name = configString(config, "negocio_nome", "nosso negócio");
  const description = configString(config, "negocio_descricao", "atendimento ao cliente");
  const tone = configString(config, "tom_de_voz", "claro, cordial e direto");
  const base = kb.map((item) => `[${item.tema}] Pergunta: ${item.pergunta}\nResposta: ${item.resposta}`).join("\n\n");
  const previous = history.map((item) => `${item.autor}: ${item.conteudo}`).join("\n");
  return `Você é o agente de suporte de ${name}. Contexto: ${description}. Tom: ${tone}.\n\n` +
    `REGRA DA CITAÇÃO LITERAL: só afirme fatos que estejam literalmente sustentados pela base de conhecimento abaixo. ` +
    `Sem base suficiente, responda com confiança baixa e marque precisa_humano=true. É proibido inventar link, preço, prazo, ` +
    `telefone, menu, política ou passo a passo que não esteja na base. Não complete lacunas com conhecimento geral.\n\n` +
    `Responda SOMENTE JSON válido no formato {"resposta":"...","confianca":0.0,"precisa_humano":false}. ` +
    `A confiança deve ser baixa quando a resposta não puder ser citada literalmente da base.\n\n` +
    `BASE DE CONHECIMENTO:\n${base || "(base vazia)"}\n\n` +
    `HISTÓRICO RECENTE:\n${previous || "(sem histórico)"}\n\n` +
    `CONTATO: ${contact?.nome || "não informado"}\nMENSAGEM: ${message}`;
}

async function fetchWithTimeout(url: string, init: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), MODEL_TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function callGemini(model: string, prompt: string): Promise<ModelResult> {
  if (!GEMINI_KEY) return { answer: null, raw: "", model, inputTokens: 0, outputTokens: 0, error: "GEMINI_API_KEY ausente" };
  try {
    const response = await fetchWithTimeout(
      `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`,
      { method: "POST", headers: { "Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY },
        body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }], generationConfig: { responseMimeType: "application/json" } }) },
    );
    const body = await response.json();
    if (!response.ok) return { answer: null, raw: "", model, inputTokens: 0, outputTokens: 0, error: `Gemini HTTP ${response.status}` };
    const raw = body?.candidates?.[0]?.content?.parts?.[0]?.text || "";
    const usage = body?.usageMetadata || {};
    return { answer: extractJson(raw), raw, model, inputTokens: Number(usage.promptTokenCount || 0), outputTokens: Number(usage.candidatesTokenCount || 0) };
  } catch (error) {
    return { answer: null, raw: "", model, inputTokens: 0, outputTokens: 0, error: String(error) };
  }
}

async function callAnthropic(model: string, prompt: string): Promise<ModelResult> {
  if (!ANTHROPIC_KEY) return { answer: null, raw: "", model, inputTokens: 0, outputTokens: 0, error: "ANTHROPIC_API_KEY ausente" };
  try {
    const response = await fetchWithTimeout("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01" },
      body: JSON.stringify({ model, max_tokens: 1000, messages: [{ role: "user", content: prompt }] }),
    });
    const body = await response.json();
    if (!response.ok) return { answer: null, raw: "", model, inputTokens: 0, outputTokens: 0, error: `Anthropic HTTP ${response.status}` };
    const raw = (body?.content || []).map((part: { text?: string }) => part.text || "").join("\n");
    const usage = body?.usage || {};
    return { answer: extractJson(raw), raw, model, inputTokens: Number(usage.input_tokens || 0), outputTokens: Number(usage.output_tokens || 0) };
  } catch (error) {
    return { answer: null, raw: "", model, inputTokens: 0, outputTokens: 0, error: String(error) };
  }
}

async function callModel(provider: string, model: string, prompt: string): Promise<ModelResult> {
  return provider === "anthropic" ? callAnthropic(model, prompt) : callGemini(model, prompt);
}

function reservationEstimate(model: string, prompt: string): number {
  const inputTokens = Math.ceil(prompt.length / 4);
  return Math.max(0.001, modelCost(model, inputTokens, 10000));
}

async function reserveCost(limit: number, model: string, etapa: string, prompt: string): Promise<number | null> {
  const { data, error } = await supabase.rpc("sup_reservar_custo", {
    limite: limit, estimativa: reservationEstimate(model, prompt), modelo_reserva: model, etapa_reserva: etapa,
  });
  if (error || data === null || data === undefined) return null;
  return Number(data);
}

async function logUsage(result: ModelResult, etapa: string, confidence: number | null, escalated: boolean, reservationId: number): Promise<void> {
  const actual = modelCost(result.model, result.inputTokens, result.outputTokens);
  const changes: Record<string, unknown> = {
    tokens_entrada: result.inputTokens, tokens_saida: result.outputTokens,
    confianca: confidence, escalou: escalated, erro: result.error || null,
  };
  if (!(result.error && actual === 0)) changes.custo_usd = actual;
  const { error } = await supabase.from("sup_uso_ia").update(changes).eq("id", reservationId);
  if (error) throw new Error(`uso de IA não registrado: ${error.message}`);
}

async function findOpenTicket(canal: string, conversaId: string): Promise<{ id: string; status: string; numero: number } | null> {
  const { data, error } = await supabase.from("sup_tickets").select("id,status,numero")
    .eq("canal", canal).eq("conversa_id", conversaId).neq("status", "resolvido")
    .order("created_at", { ascending: false }).limit(1).maybeSingle();
  if (error) throw new Error(`tickets indisponíveis: ${error.message}`);
  return data || null;
}

async function sendEvolution(number: string, text: string): Promise<boolean> {
  if (!EVOLUTION_URL || !EVOLUTION_KEY || !EVOLUTION_INSTANCE || !text) return false;
  try {
    const response = await fetch(`${EVOLUTION_URL}/message/sendText/${encodeURIComponent(EVOLUTION_INSTANCE)}`, {
      method: "POST", headers: { apikey: EVOLUTION_KEY, "Content-Type": "application/json" },
      body: JSON.stringify({ number, text }),
    });
    return response.ok;
  } catch (_) {
    return false;
  }
}

async function escalate(
  canal: string, conversaId: string, message: string, contact: Contact | undefined,
  reason: string, draft: string, config: ConfigMap,
): Promise<EscalationResult> {
  const inserted = await supabase.from("sup_tickets").insert({
    canal, conversa_id: conversaId, contato_nome: contact?.nome || null,
    contato_whatsapp: contact?.whatsapp || (canal === "whatsapp" ? conversaId : null),
    contato_email: contact?.email || null, assunto: message.slice(0, 160),
    motivo_escalonamento: reason, sugestao_ia: draft || null,
  }).select("id,numero").single();
  let ticket = inserted.data as { id: string; numero: number } | null;
  if (inserted.error) {
    if (inserted.error.code !== "23505") throw new Error(`ticket não criado: ${inserted.error.message}`);
    ticket = await findOpenTicket(canal, conversaId);
  }
  const ticketId = ticket?.id || null;
  if (ticketId) {
    await supabase.from("sup_mensagens").update({ ticket_id: ticketId }).eq("canal", canal)
      .eq("conversa_id", conversaId).eq("autor", "cliente").is("ticket_id", null);
    const question = normalizeQuestion(message);
    const { data: candidate } = await supabase.from("sup_kb_candidatas").select("id,ocorrencias")
      .eq("pergunta", question).eq("status", "pendente").maybeSingle();
    if (candidate) {
      await supabase.from("sup_kb_candidatas").update({ ocorrencias: Number(candidate.ocorrencias || 1) + 1, contexto: message, resposta_sugerida: draft || null }).eq("id", candidate.id);
    } else {
      await supabase.from("sup_kb_candidatas").insert({ pergunta: question, contexto: message, resposta_sugerida: draft || null, ticket_id: ticketId });
    }
  }
  const resposta = ticketId ? handoffText(config, canal, contact, ticket?.numero, reason) : "";
  if (ticketId) {
    // grava o aviso no histórico: o cliente o revê ao reabrir o chat e a equipe vê no hub o que foi prometido
    await supabase.from("sup_mensagens").insert({ canal, conversa_id: conversaId, ticket_id: ticketId, autor: "ia", conteudo: resposta });
  }
  return {
    resposta,
    escalou: Boolean(ticketId),
    ticket_id: ticketId,
    modelo: null,
    numero: ticket?.numero ?? null,
    whatsapp_equipe: teamWhatsapp(config) || null,
  };
}

// Cliente do site que responde no WhatsApp da equipe: a mensagem entra no ticket do site que já está aberto,
// em vez de a IA começar outro atendimento do zero.
async function findOpenSiteTicketByPhone(phone: string): Promise<{ id: string; status: string; numero: number } | null> {
  const tail = phone.replace(/\D/g, "").slice(-8);
  if (tail.length < 8) return null;
  const { data, error } = await supabase.from("sup_tickets").select("id,status,numero,contato_whatsapp")
    .eq("canal", "site").neq("status", "resolvido").like("contato_whatsapp", `%${tail}`)
    .order("created_at", { ascending: false }).limit(5);
  if (error) throw new Error(`tickets indisponíveis: ${error.message}`);
  const found = (data || []).find((row: { contato_whatsapp: string | null }) => samePhone(row.contato_whatsapp || "", phone));
  return found ? { id: found.id, status: found.status, numero: found.numero } : null;
}

async function processMessage(
  canal: "site" | "whatsapp", conversaId: string, message: string, contact?: Contact, eventId?: string,
): Promise<EscalationResult> {
  const config = await getConfig();
  if (eventId) {
    const { data: alreadyProcessed, error: duplicateCheckError } = await supabase.from("sup_mensagens")
      .select("id").eq("evento_id", eventId).maybeSingle();
    if (duplicateCheckError) throw new Error(`deduplicação indisponível: ${duplicateCheckError.message}`);
    if (alreadyProcessed) return { resposta: "", escalou: false, ticket_id: null, modelo: null };
  }
  const { error: clientError } = await supabase.from("sup_mensagens").insert({ canal, conversa_id: conversaId, autor: "cliente", conteudo: message, evento_id: eventId || null });
  if (clientError && !(eventId && clientError.code === "23505")) throw new Error(`mensagem cliente não registrada: ${clientError.message}`);
  if (clientError) return { resposta: "", escalou: false, ticket_id: null, modelo: null };
  const open = await findOpenTicket(canal, conversaId);
  if (open) {
    await supabase.from("sup_mensagens").update({ ticket_id: open.id }).eq("canal", canal).eq("conversa_id", conversaId)
      .eq("autor", "cliente").is("ticket_id", null);
    if (open.status === "aguardando_cliente") await supabase.from("sup_tickets").update({ status: "aberto" }).eq("id", open.id);
    // no WhatsApp a equipe já está na conversa; no site, confirma que a mensagem foi anotada no ticket
    const ack = canal === "site" ? handoffText(config, canal, contact, open.numero, "", true) : "";
    return { resposta: ack, escalou: true, ticket_id: open.id, modelo: null, numero: open.numero, whatsapp_equipe: teamWhatsapp(config) || null };
  }
  if (canal === "whatsapp") {
    const siteTicket = await findOpenSiteTicketByPhone(conversaId);
    if (siteTicket) {
      await supabase.from("sup_mensagens").update({ ticket_id: siteTicket.id }).eq("canal", canal).eq("conversa_id", conversaId)
        .eq("autor", "cliente").is("ticket_id", null);
      if (siteTicket.status === "aguardando_cliente") await supabase.from("sup_tickets").update({ status: "aberto" }).eq("id", siteTicket.id);
      return { resposta: "", escalou: true, ticket_id: siteTicket.id, modelo: null, numero: siteTicket.numero };
    }
  }
  if (/(atendente|humano|pessoa|falar com alguém|reclama)/i.test(message)) {
    return escalate(canal, conversaId, message, contact, "pedido_humano", "", config);
  }
  const limit = configNumber(config, "teto_diario_usd", DEFAULT_DAILY_LIMIT);
  const { data: cost, error: costError } = await supabase.rpc("sup_custo_hoje");
  if (costError) throw new Error(`custo indisponível: ${costError.message}`);
  if (Number(cost || 0) >= limit) return escalate(canal, conversaId, message, contact, "teto_custo", "", config);
  const { data: kb, error: kbError } = await supabase.rpc("sup_buscar_kb", { consulta: message, limite: 5 });
  if (kbError) throw new Error(`KB indisponível: ${kbError.message}`);
  const { data: history, error: historyError } = await supabase.from("sup_mensagens").select("autor,conteudo")
    .eq("canal", canal).eq("conversa_id", conversaId).order("created_at", { ascending: false }).limit(8);
  if (historyError) throw new Error(`histórico indisponível: ${historyError.message}`);
  const provider = configString(config, "provedor", "gemini");
  const cheap = configString(config, "modelo_barato", provider === "anthropic" ? "claude-haiku-4-5-20251001" : "gemini-flash-lite-latest");
  const strong = configString(config, "modelo_forte", provider === "anthropic" ? "claude-sonnet-5" : "gemini-flash-latest");
  const threshold = configNumber(config, "limiar_confianca", DEFAULT_THRESHOLD);
  const prompt = promptFor(config, message, (kb || []) as KBItem[], (history || []).reverse(), contact);
  if (!("teto_diario_usd" in config) || !("provedor" in config)) {
    throw new Error("configuração operacional incompleta");
  }
  const cheapReservation = await reserveCost(limit, cheap, "barato", prompt);
  if (cheapReservation === null) return escalate(canal, conversaId, message, contact, "teto_custo", "", config);
  let result = await callModel(provider, cheap, prompt);
  await logUsage(result, "barato", result.answer?.confianca ?? null, false, cheapReservation);
  let best = result.answer;
  let model = cheap;
  if (!best || best.confianca < threshold) {
    const strongReservation = await reserveCost(limit, strong, "forte", prompt);
    if (strongReservation === null) return escalate(canal, conversaId, message, contact, "teto_custo", best?.resposta || "", config);
    result = await callModel(provider, strong, prompt);
    await logUsage(result, "forte", result.answer?.confianca ?? null, false, strongReservation);
    if (result.answer && (!best || result.answer.confianca >= best.confianca)) best = result.answer;
    model = strong;
  }
  if (!best || best.confianca < threshold || best.precisa_humano) {
    const escalated = await escalate(canal, conversaId, message, contact, result.error ? "erro_ia" : "baixa_confianca", best?.resposta || "", config);
    if (best?.resposta && escalated.ticket_id) await supabase.from("sup_tickets").update({ sugestao_ia: best.resposta }).eq("id", escalated.ticket_id);
    return escalated;
  }
  const openedMeanwhile = await findOpenTicket(canal, conversaId);
  if (openedMeanwhile) return { resposta: "", escalou: true, ticket_id: openedMeanwhile.id, modelo: null, numero: openedMeanwhile.numero };
  const { error: answerError } = await supabase.from("sup_mensagens").insert({ canal, conversa_id: conversaId, autor: "ia", conteudo: best.resposta, modelo: model, confianca: best.confianca });
  if (answerError) throw new Error(`resposta IA não registrada: ${answerError.message}`);
  return { resposta: best.resposta, escalou: false, ticket_id: null, modelo: model };
}

function evolutionText(payload: any): EvolutionItem | null {
  const data = payload?.data || payload;
  const key = data?.key || {};
  const remote = String(key.remoteJid || data?.remoteJid || "");
  if (!remote || key.fromMe || remote.endsWith("@g.us")) return null;
  const text = String(data?.message?.conversation || data?.message?.extendedTextMessage?.text || data?.conversation || data?.extendedTextMessage?.text || "").trim();
  const jid = remote.match(/^(\d{6,15})@s\.whatsapp\.net$/);
  if (!jid || remote.includes("@broadcast") || remote.includes("@newsletter")) return null;
  const candidate = String(key.id || data?.messageId || "").trim();
  return text ? { remote: jid[1], text, eventId: candidate ? candidate.slice(0, 200) : undefined } : null;
}

async function handleEvolution(request: Request, payload: any, origin: string | null): Promise<Response> {
  const token = new URL(request.url).searchParams.get("token") || "";
  if (!WEBHOOK_TOKEN || !constantTimeEqual(token, WEBHOOK_TOKEN)) return jsonResponse({ error: "não autorizado" }, 401, origin);
  if (String(payload?.event || "").toLowerCase() !== "messages.upsert") return jsonResponse({ ok: true, ignorado: true }, 200, origin);
  try {
    const item = evolutionText(payload);
    if (item) {
      const result = await processMessage("whatsapp", item.remote, item.text, undefined, item.eventId);
      if (result.resposta) await sendEvolution(item.remote, result.resposta);
    }
  } catch (error) {
    console.error("support-ai evolution error", String(error));
  }
  return jsonResponse({ ok: true }, 200, origin);
}

async function handleHuman(request: Request, body: any, origin: string | null): Promise<Response> {
  const user = await requireTeamUser(request);
  if (!user) return jsonResponse({ error: "não autorizado" }, 401, origin);
  if (!validText(body.ticket_id, 80) || !validText(body.conteudo, MAX_MESSAGE)) return jsonResponse({ error: "ticket_id e conteudo são obrigatórios" }, 400, origin);
  const { data: ticket } = await supabase.from("sup_tickets").select("id,canal,conversa_id,atribuido_a,numero,contato_whatsapp").eq("id", body.ticket_id).maybeSingle();
  if (!ticket) return jsonResponse({ error: "ticket não encontrado" }, 404, origin);
  const { error: humanError } = await supabase.from("sup_mensagens").insert({ canal: ticket.canal, conversa_id: ticket.conversa_id, ticket_id: ticket.id, autor: "humano", autor_user_id: user.id, conteudo: body.conteudo });
  if (humanError) return jsonResponse({ enviado: false, erro: "resposta não registrada" }, 500, origin);
  let enviado: boolean;
  let whatsapp = false;
  if (ticket.canal === "site") {
    // a resposta fica no chat do site e, se o cliente deixou WhatsApp, também vai para lá (é o canal prometido no transbordo)
    enviado = true;
    if (ticket.contato_whatsapp) {
      const negocio = configString(await getConfig(), "negocio_nome", "");
      const header = `${negocio ? negocio + " · " : ""}ticket #${ticket.numero}`;
      whatsapp = await sendEvolution(ticket.contato_whatsapp, `*${header}*\n\n${body.conteudo}`);
    }
  } else {
    enviado = await sendEvolution(ticket.conversa_id, body.conteudo);
    whatsapp = enviado;
  }
  const { error: statusError } = await supabase.from("sup_tickets").update({ status: enviado ? "aguardando_cliente" : "em_atendimento", atribuido_a: ticket.atribuido_a || user.id }).eq("id", ticket.id);
  if (statusError) return jsonResponse({ enviado: false, erro: "ticket não atualizado" }, 500, origin);
  return jsonResponse({ enviado, whatsapp }, 200, origin);
}

async function handleSuggestion(request: Request, body: any, origin: string | null): Promise<Response> {
  const user = await requireTeamUser(request);
  if (!user) return jsonResponse({ error: "não autorizado" }, 401, origin);
  if (!validText(body.ticket_id, 80)) return jsonResponse({ error: "ticket_id é obrigatório" }, 400, origin);
  const { data: ticket } = await supabase.from("sup_tickets").select("id,canal,conversa_id,assunto").eq("id", body.ticket_id).maybeSingle();
  if (!ticket) return jsonResponse({ error: "ticket não encontrado" }, 404, origin);
  const config = await getConfig();
  const { data: kb } = await supabase.rpc("sup_buscar_kb", { consulta: ticket.assunto, limite: 5 });
  const prompt = promptFor(config, ticket.assunto, (kb || []) as KBItem[], [], undefined);
  const provider = configString(config, "provedor", "gemini");
  const model = configString(config, "modelo_forte", provider === "anthropic" ? "claude-sonnet-5" : "gemini-flash-latest");
  const reservation = await reserveCost(configNumber(config, "teto_diario_usd", DEFAULT_DAILY_LIMIT), model, "forte", prompt);
  if (reservation === null) return jsonResponse({ error: "teto diário atingido" }, 429, origin);
  const result = await callModel(provider, model, prompt);
  await logUsage(result, "forte", result.answer?.confianca ?? null, false, reservation);
  const suggestion = result.answer?.resposta || "Não foi possível gerar uma sugestão com base na KB.";
  await supabase.from("sup_tickets").update({ sugestao_ia: suggestion }).eq("id", ticket.id);
  return jsonResponse({ sugestao: suggestion, confianca: result.answer?.confianca || 0 }, 200, origin);
}

async function handleHistory(body: any, origin: string | null): Promise<Response> {
  if (!originAllowed(origin)) return jsonResponse({ error: "origem não permitida" }, 403, origin);
  if (body.canal !== "site" || !validConversation(body.conversa_id)) return jsonResponse({ error: "conversa inválida" }, 400, origin);
  let query = supabase.from("sup_mensagens").select("id,autor,conteudo,created_at")
    .eq("canal", "site").eq("conversa_id", body.conversa_id).in("autor", ["cliente", "ia", "humano"]).order("created_at", { ascending: true }).limit(200);
  if (typeof body.desde === "string" && body.desde.length < 80) query = query.gt("created_at", body.desde);
  const { data, error } = await query;
  return error ? jsonResponse({ error: "não foi possível carregar o histórico" }, 500, origin) : jsonResponse({ mensagens: data || [] }, 200, origin);
}

async function handleSiteMessage(body: any, origin: string | null): Promise<Response> {
  if (!originAllowed(origin)) return jsonResponse({ error: "origem não permitida" }, 403, origin);
  if (body.canal !== "site" || !validConversation(body.conversa_id) || !validText(body.mensagem, MAX_MESSAGE)) {
    return jsonResponse({ error: "mensagem, canal ou conversa inválidos" }, 400, origin);
  }
  const message = body.mensagem.trim();
  const contact = cleanContact(body.contato);
  try {
    const result = await processMessage("site", body.conversa_id, message, contact);
    return jsonResponse(result, 200, origin);
  } catch (error) {
    console.error("support-ai site fallback", String(error));
    try {
      const fallback = await escalate("site", body.conversa_id, message, contact, "erro_ia", "", await getConfig());
      return jsonResponse(fallback, 200, origin);
    } catch (fallbackError) {
      console.error("support-ai site fallback failed", String(fallbackError));
      return jsonResponse({ resposta: "Não foi possível registrar sua mensagem agora. Tente novamente em instantes.", escalou: false, ticket_id: null, modelo: null, erro: true }, 503, origin);
    }
  }
}

async function handleOpenTicket(body: any, origin: string | null): Promise<Response> {
  if (!originAllowed(origin)) return jsonResponse({ error: "origem não permitida" }, 403, origin);
  if (body.canal !== "site" || !validConversation(body.conversa_id)) return jsonResponse({ error: "conversa inválida" }, 400, origin);
  const contact = cleanContact(body.contato);
  if (!contact?.nome || (!contact.email && !contact.whatsapp)) return jsonResponse({ error: "informe nome e e-mail ou WhatsApp" }, 400, origin);
  const descricao = typeof body.mensagem === "string" ? body.mensagem.trim().slice(0, MAX_MESSAGE) : "";
  const open = await findOpenTicket("site", body.conversa_id);
  if (open) {
    if (descricao) {
      const { error } = await supabase.from("sup_mensagens").insert({ canal: "site", conversa_id: body.conversa_id, ticket_id: open.id, autor: "cliente", conteudo: descricao });
      if (error) return jsonResponse({ error: "mensagem não registrada" }, 500, origin);
    }
    const config = await getConfig();
    return jsonResponse({ escalou: true, ticket_id: open.id, numero: open.numero, ja_existia: true,
      resposta: handoffText(config, "site", contact, open.numero, "", true), whatsapp_equipe: teamWhatsapp(config) || null }, 200, origin);
  }
  if (descricao) {
    const { error } = await supabase.from("sup_mensagens").insert({ canal: "site", conversa_id: body.conversa_id, autor: "cliente", conteudo: descricao });
    if (error) return jsonResponse({ error: "mensagem não registrada" }, 500, origin);
  }
  const { data: last } = await supabase.from("sup_mensagens").select("conteudo").eq("canal", "site").eq("conversa_id", body.conversa_id)
    .eq("autor", "cliente").order("created_at", { ascending: false }).limit(1).maybeSingle();
  const assunto = descricao || last?.conteudo || "Atendimento solicitado pelo cliente";
  const result = await escalate("site", body.conversa_id, assunto, contact, "pedido_cliente", "", await getConfig());
  if (!result.ticket_id) return jsonResponse({ error: "não foi possível abrir o ticket" }, 500, origin);
  return jsonResponse(result, 200, origin);
}

async function handlePing(origin: string | null): Promise<Response> {
  const { count, error } = await supabase.from("sup_kb").select("id", { count: "exact", head: true });
  if (error) return jsonResponse({ ok: false, error: "KB indisponível" }, 503, origin);
  const config = await getConfig();
  return jsonResponse({ ok: true, provedor: configString(config, "provedor", "configurado"), kb_itens: count || 0 }, 200, origin);
}

Deno.serve(async (request: Request): Promise<Response> => {
  const origin = request.headers.get("origin");
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders(origin) });
  if (request.method !== "POST") return jsonResponse({ error: "método não permitido" }, 405, origin);
  let body: any;
  try { body = await request.json(); } catch (_) { return jsonResponse({ error: "JSON inválido" }, 400, origin); }
  if (body?.event) {
    try { return await handleEvolution(request, body, origin); }
    catch (error) { console.error("support-ai webhook error", String(error)); return jsonResponse({ ok: true }, 200, origin); }
  }
  try {
    if (body?.acao === "ping") return await handlePing(origin);
    if (body?.acao === "historico") return await handleHistory(body, origin);
    if (body?.acao === "responder_humano") return await handleHuman(request, body, origin);
    if (body?.acao === "sugerir") return await handleSuggestion(request, body, origin);
    if (body?.acao === "mensagem") return await handleSiteMessage(body, origin);
    if (body?.acao === "abrir_ticket") return await handleOpenTicket(body, origin);
    return jsonResponse({ error: "ação inválida" }, 400, origin);
  } catch (error) {
    console.error("support-ai error", String(error));
    return jsonResponse({ resposta: "No momento não consegui concluir o atendimento. Tente novamente em instantes.", escalou: false, ticket_id: null, modelo: null, erro: true }, 503, origin);
  }
});
