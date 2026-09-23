
-- Setup 16: Sistema de Suporte com IA.
-- Esta migration pode ser reaplicada: todos os objetos criados por ela têm nomes
-- estáveis e as policies são removidas antes de serem recriadas.

create extension if not exists pgcrypto;

create table if not exists public.sup_equipe (
  user_id uuid primary key references auth.users(id) on delete cascade,
  nome text not null,
  papel text not null default 'agente' check (papel in ('admin', 'agente')),
  created_at timestamptz not null default now()
);

create table if not exists public.sup_config (
  chave text primary key,
  valor jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists public.sup_tickets (
  id uuid primary key default gen_random_uuid(),
  numero bigint generated always as identity,
  canal text not null check (canal in ('whatsapp', 'site', 'manual')),
  conversa_id text not null,
  contato_nome text,
  contato_whatsapp text,
  contato_email text,
  assunto text not null,
  status text not null default 'aberto'
    check (status in ('aberto', 'em_atendimento', 'aguardando_cliente', 'resolvido')),
  prioridade text not null default 'normal' check (prioridade in ('baixa', 'normal', 'alta')),
  motivo_escalonamento text,
  sugestao_ia text,
  atribuido_a uuid references public.sup_equipe(user_id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolvido_em timestamptz
);

create table if not exists public.sup_mensagens (
  id uuid primary key default gen_random_uuid(),
  canal text not null check (canal in ('whatsapp', 'site', 'manual')),
  conversa_id text not null,
  ticket_id uuid references public.sup_tickets(id) on delete cascade,
  evento_id text,
  autor text not null check (autor in ('cliente', 'ia', 'humano')),
  conteudo text not null,
  modelo text,
  confianca numeric,
  autor_user_id uuid,
  created_at timestamptz not null default now()
);

create table if not exists public.sup_kb (
  id uuid primary key default gen_random_uuid(),
  tema text not null,
  pergunta text not null,
  resposta text not null,
  fonte text,
  ativo boolean not null default true,
  busca tsvector generated always as (
    to_tsvector(
      'portuguese'::regconfig,
      coalesce(tema, '') || ' ' || coalesce(pergunta, '') || ' ' || coalesce(resposta, '')
    )
  ) stored,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.sup_kb_candidatas (
  id uuid primary key default gen_random_uuid(),
  pergunta text not null,
  contexto text,
  resposta_sugerida text,
  ocorrencias integer not null default 1,
  status text not null default 'pendente'
    check (status in ('pendente', 'aprovada', 'rejeitada')),
  ticket_id uuid references public.sup_tickets(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.sup_uso_ia (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  dia date not null default ((now() at time zone 'America/Sao_Paulo')::date),
  modelo text not null,
  etapa text not null check (etapa in ('barato', 'forte')),
  tokens_entrada integer,
  tokens_saida integer,
  custo_usd numeric(12, 6) not null default 0,
  confianca numeric,
  escalou boolean not null default false,
  erro text
);

alter table public.sup_mensagens add column if not exists evento_id text;

create unique index if not exists sup_tickets_uma_conversa_aberta
  on public.sup_tickets (canal, conversa_id)
  where status <> 'resolvido';
create index if not exists sup_mensagens_conversa_data
  on public.sup_mensagens (canal, conversa_id, created_at);
create index if not exists sup_mensagens_ticket on public.sup_mensagens (ticket_id);
create unique index if not exists sup_mensagens_evento_unico
  on public.sup_mensagens (evento_id) where evento_id is not null;
create index if not exists sup_kb_busca_gin on public.sup_kb using gin (busca);
create index if not exists sup_kb_candidatas_pendentes
  on public.sup_kb_candidatas (status, ocorrencias desc, updated_at);
create index if not exists sup_uso_ia_dia on public.sup_uso_ia (dia, created_at);

create or replace function public.sup_set_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists sup_tickets_updated_at on public.sup_tickets;
create trigger sup_tickets_updated_at before update on public.sup_tickets
for each row execute function public.sup_set_updated_at();
drop trigger if exists sup_kb_updated_at on public.sup_kb;
create trigger sup_kb_updated_at before update on public.sup_kb
for each row execute function public.sup_set_updated_at();
drop trigger if exists sup_kb_candidatas_updated_at on public.sup_kb_candidatas;
create trigger sup_kb_candidatas_updated_at before update on public.sup_kb_candidatas
for each row execute function public.sup_set_updated_at();
drop trigger if exists sup_config_updated_at on public.sup_config;
create trigger sup_config_updated_at before update on public.sup_config
for each row execute function public.sup_set_updated_at();

create or replace function public.sup_eh_membro()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (select 1 from public.sup_equipe where user_id = auth.uid());
$$;

create or replace function public.sup_eh_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.sup_equipe
    where user_id = auth.uid() and papel = 'admin'
  );
$$;

create or replace function public.sup_buscar_kb(consulta text, limite integer default 5)
returns table (id uuid, tema text, pergunta text, resposta text, rank real)
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  consulta_limpa text := left(coalesce(consulta, ''), 2000);
  q tsquery;
  palavras text;
begin
  if btrim(consulta_limpa) = '' then
    return;
  end if;

  q := websearch_to_tsquery('portuguese'::regconfig, consulta_limpa);
  return query
    select k.id, k.tema, k.pergunta, k.resposta, ts_rank(k.busca, q)::real
    from public.sup_kb k
    where k.ativo and k.busca @@ q
    order by ts_rank(k.busca, q) desc, k.updated_at desc
    limit greatest(1, least(coalesce(limite, 5), 20));

  if found then
    return;
  end if;

  select string_agg(quote_literal(p) || ':*', ' | ')
    into palavras
    from unnest(regexp_split_to_array(lower(consulta_limpa), '[^[:alnum:]]+')) as p
    where char_length(p) >= 4;
  if palavras is null or palavras = '' then
    return;
  end if;
  q := to_tsquery('portuguese'::regconfig, palavras);
  return query
    select k.id, k.tema, k.pergunta, k.resposta, ts_rank(k.busca, q)::real
    from public.sup_kb k
    where k.ativo and k.busca @@ q
    order by ts_rank(k.busca, q) desc, k.updated_at desc
    limit greatest(1, least(coalesce(limite, 5), 20));
end;
$$;

create or replace function public.sup_custo_hoje()
returns numeric
language sql
stable
security definer
set search_path = public
as $$
  select coalesce(sum(custo_usd), 0)::numeric
  from public.sup_uso_ia
  where dia = (now() at time zone 'America/Sao_Paulo')::date;
$$;

create or replace function public.sup_reservar_custo(
  limite numeric, estimativa numeric, modelo_reserva text, etapa_reserva text
)
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
  hoje date := (now() at time zone 'America/Sao_Paulo')::date;
  reservado numeric;
  novo_id bigint;
begin
  if limite is null or limite <= 0 or estimativa is null or estimativa <= 0
     or etapa_reserva is null or etapa_reserva not in ('barato', 'forte') then
    return null;
  end if;
  perform pg_advisory_xact_lock(hashtextextended('sup_custo_ia:' || hoje::text, 0));
  select coalesce(sum(custo_usd), 0) into reservado
    from public.sup_uso_ia where dia = hoje;
  if reservado + estimativa > limite then
    return null;
  end if;
  insert into public.sup_uso_ia (
    dia, modelo, etapa, custo_usd, escalou, erro
  ) values (hoje, modelo_reserva, etapa_reserva, estimativa, false, 'reserva')
  returning id into novo_id;
  return novo_id;
end;
$$;

insert into public.sup_config (chave, valor) values
  ('negocio_nome', to_jsonb('Seu negócio'::text)),
  ('negocio_descricao', to_jsonb('Atendimento ao cliente'::text)),
  ('tom_de_voz', to_jsonb('claro, cordial e direto'::text)),
  ('limiar_confianca', '0.7'::jsonb),
  ('teto_diario_usd', '2.0'::jsonb),
  ('modelo_barato', to_jsonb('gemini-2.5-flash-lite'::text)),
  ('modelo_forte', to_jsonb('gemini-2.5-flash'::text)),
  ('provedor', to_jsonb('gemini'::text)),
  ('mensagem_transbordo', to_jsonb('Vou encaminhar sua mensagem para uma pessoa da equipe. Assim que possível, alguém continuará o atendimento.'::text)),
  ('horario_humano', to_jsonb('horário comercial'::text))
on conflict (chave) do nothing;

alter table public.sup_equipe enable row level security;
alter table public.sup_config enable row level security;
alter table public.sup_tickets enable row level security;
alter table public.sup_mensagens enable row level security;
alter table public.sup_kb enable row level security;
alter table public.sup_kb_candidatas enable row level security;
alter table public.sup_uso_ia enable row level security;

do $$
declare
  tabela text;
begin
  foreach tabela in array array[
    'sup_equipe', 'sup_config', 'sup_tickets', 'sup_mensagens',
    'sup_kb', 'sup_kb_candidatas', 'sup_uso_ia'
  ] loop
    execute format('revoke all on table public.%I from anon', tabela);
  end loop;
end;
$$;

drop policy if exists sup_equipe_select_membro on public.sup_equipe;
create policy sup_equipe_select_membro on public.sup_equipe
  for select to authenticated using (public.sup_eh_membro());

drop policy if exists sup_config_select_membro on public.sup_config;
create policy sup_config_select_membro on public.sup_config
  for select to authenticated using (public.sup_eh_membro());
drop policy if exists sup_config_insert_membro on public.sup_config;
create policy sup_config_insert_membro on public.sup_config
  for insert to authenticated with check (public.sup_eh_admin());
drop policy if exists sup_config_update_membro on public.sup_config;
create policy sup_config_update_membro on public.sup_config
  for update to authenticated using (public.sup_eh_admin()) with check (public.sup_eh_admin());

drop policy if exists sup_tickets_select_membro on public.sup_tickets;
create policy sup_tickets_select_membro on public.sup_tickets
  for select to authenticated using (public.sup_eh_membro());
drop policy if exists sup_tickets_insert_membro on public.sup_tickets;
create policy sup_tickets_insert_membro on public.sup_tickets
  for insert to authenticated with check (public.sup_eh_membro());
drop policy if exists sup_tickets_update_membro on public.sup_tickets;
create policy sup_tickets_update_membro on public.sup_tickets
  for update to authenticated using (public.sup_eh_membro()) with check (public.sup_eh_membro());

drop policy if exists sup_mensagens_select_membro on public.sup_mensagens;
create policy sup_mensagens_select_membro on public.sup_mensagens
  for select to authenticated using (public.sup_eh_membro());
drop policy if exists sup_mensagens_insert_membro on public.sup_mensagens;
drop policy if exists sup_mensagens_update_membro on public.sup_mensagens;

drop policy if exists sup_kb_select_membro on public.sup_kb;
create policy sup_kb_select_membro on public.sup_kb
  for select to authenticated using (public.sup_eh_membro());
drop policy if exists sup_kb_insert_membro on public.sup_kb;
create policy sup_kb_insert_membro on public.sup_kb
  for insert to authenticated with check (public.sup_eh_membro());
drop policy if exists sup_kb_update_membro on public.sup_kb;
create policy sup_kb_update_membro on public.sup_kb
  for update to authenticated using (public.sup_eh_membro()) with check (public.sup_eh_membro());
drop policy if exists sup_kb_delete_admin on public.sup_kb;
create policy sup_kb_delete_admin on public.sup_kb
  for delete to authenticated using (public.sup_eh_admin());

drop policy if exists sup_kb_candidatas_select_membro on public.sup_kb_candidatas;
create policy sup_kb_candidatas_select_membro on public.sup_kb_candidatas
  for select to authenticated using (public.sup_eh_membro());
drop policy if exists sup_kb_candidatas_insert_membro on public.sup_kb_candidatas;
create policy sup_kb_candidatas_insert_membro on public.sup_kb_candidatas
  for insert to authenticated with check (public.sup_eh_membro());
drop policy if exists sup_kb_candidatas_update_membro on public.sup_kb_candidatas;
create policy sup_kb_candidatas_update_membro on public.sup_kb_candidatas
  for update to authenticated using (public.sup_eh_membro()) with check (public.sup_eh_membro());
drop policy if exists sup_kb_candidatas_delete_admin on public.sup_kb_candidatas;
create policy sup_kb_candidatas_delete_admin on public.sup_kb_candidatas
  for delete to authenticated using (public.sup_eh_admin());

drop policy if exists sup_uso_ia_select_membro on public.sup_uso_ia;
create policy sup_uso_ia_select_membro on public.sup_uso_ia
  for select to authenticated using (public.sup_eh_membro());
drop policy if exists sup_uso_ia_insert_membro on public.sup_uso_ia;
drop policy if exists sup_uso_ia_update_membro on public.sup_uso_ia;

grant select, insert, update, delete on public.sup_equipe to authenticated;
grant select, insert, update, delete on public.sup_config to authenticated;
grant select, insert, update, delete on public.sup_tickets to authenticated;
grant select, insert, update, delete on public.sup_mensagens to authenticated;
grant select, insert, update, delete on public.sup_kb to authenticated;
grant select, insert, update, delete on public.sup_kb_candidatas to authenticated;
grant select, insert, update, delete on public.sup_uso_ia to authenticated;
grant usage, select on all sequences in schema public to authenticated;
revoke all on function public.sup_eh_membro() from public;
revoke all on function public.sup_eh_admin() from public;
revoke all on function public.sup_buscar_kb(text, integer) from public;
revoke all on function public.sup_custo_hoje() from public;
revoke all on function public.sup_reservar_custo(numeric, numeric, text, text) from public;
grant execute on function public.sup_eh_membro() to authenticated;
grant execute on function public.sup_eh_admin() to authenticated;
-- A reserva é uma operação interna da Edge Function: authenticated não pode
-- escolher limite/estimativa e bloquear o atendimento de outros usuários.
grant execute on function public.sup_eh_membro() to service_role;
grant execute on function public.sup_eh_admin() to service_role;
grant execute on function public.sup_buscar_kb(text, integer) to service_role;
grant execute on function public.sup_custo_hoje() to service_role;
grant execute on function public.sup_reservar_custo(numeric, numeric, text, text) to service_role;
-- Busca na base e custo do dia rodam SECURITY DEFINER: só a Edge Function (service_role) chama.
revoke execute on function public.sup_buscar_kb(text, integer) from authenticated;
revoke execute on function public.sup_custo_hoje() from authenticated;
revoke all on function public.sup_eh_membro() from anon;
revoke all on function public.sup_eh_admin() from anon;
revoke all on function public.sup_buscar_kb(text, integer) from anon;
revoke all on function public.sup_custo_hoje() from anon;
revoke all on function public.sup_reservar_custo(numeric, numeric, text, text) from anon;
