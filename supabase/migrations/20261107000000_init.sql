-- STEP 8: 問題集・学習履歴のテーブル定義
-- 教材（books / book_versions / questions）はログイン済みユーザーが読み取りのみ。書き込みは取り込みスクリプト（service_role）だけ。
-- 学習履歴（answer_logs / question_stats / study_sessions）は本人の行だけ読み書きできる（RLS）。
-- 個人情報はSupabase AuthのユーザーID以外を保存しない。

create table public.books (
  book_id          text primary key check (book_id ~ '^[A-Za-z0-9_-]{2,32}$'),
  title            text not null,
  current_version  text not null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create table public.book_versions (
  id           bigint generated always as identity primary key,
  book_id      text not null references public.books(book_id) on delete cascade,
  version      text not null,
  json_path    text not null,             -- Storage上の元JSON（バックアップ）
  sha256       text,                      -- 原本PDFのハッシュ
  question_count int not null,
  imported_at  timestamptz not null default now(),
  unique (book_id, version)
);

create table public.questions (
  id                 text primary key,     -- 例: IT001-Q0001
  book_id            text not null references public.books(book_id) on delete cascade,
  version            text not null,
  chapter            text,
  category           text,
  difficulty         smallint check (difficulty between 1 and 5),
  question_type      text not null check (question_type in ('single_choice','multiple_choice','true_false','numeric')),
  validation_status  text not null check (validation_status in ('pending','auto_ok','verified','rejected')),
  body               jsonb not null,       -- 問題文・選択肢・正解・解説など教材JSONの1問分
  updated_at         timestamptz not null default now()
);
create index questions_book_idx on public.questions(book_id);

create table public.answer_logs (
  id           uuid primary key,          -- 端末側で採番（オフライン時の重複送信を防ぐ）
  user_id      uuid not null default auth.uid() references auth.users(id) on delete cascade,
  book_id      text not null references public.books(book_id) on delete cascade,
  question_id  text not null,
  session_id   text,
  selected     text[] not null default '{}',
  is_correct   boolean not null,
  answered_at  timestamptz not null,
  elapsed_ms   int check (elapsed_ms >= 0),
  mode         text not null check (mode in ('normal','exam','weak','review'))
);
create index answer_logs_user_book_idx on public.answer_logs(user_id, book_id, answered_at);

create table public.question_stats (
  user_id           uuid not null references auth.users(id) on delete cascade,
  question_id       text not null,
  book_id           text not null references public.books(book_id) on delete cascade,
  attempts          int not null default 0,
  correct_count     int not null default 0,
  last_answered_at  timestamptz,
  last_correct      boolean,
  -- 将来の間隔反復（SM-2）用
  ease              real not null default 2.5,
  interval_days     int not null default 0,
  due_at            timestamptz,
  primary key (user_id, question_id)
);

create table public.study_sessions (
  id            text not null,
  user_id       uuid not null default auth.uid() references auth.users(id) on delete cascade,
  book_id       text not null references public.books(book_id) on delete cascade,
  mode          text not null,
  question_ids  text[] not null,
  cursor        int not null default 0,
  answers       jsonb not null default '{}',
  started_at    timestamptz not null,
  finished_at   timestamptz,
  updated_at    timestamptz not null default now(),
  primary key (user_id, id)
);

-- 回答が入るたびに問題ごとの集計を更新する
create function public.bump_question_stats() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.question_stats as s (user_id, question_id, book_id, attempts, correct_count, last_answered_at, last_correct)
  values (new.user_id, new.question_id, new.book_id, 1, case when new.is_correct then 1 else 0 end, new.answered_at, new.is_correct)
  on conflict (user_id, question_id) do update set
    attempts = s.attempts + 1,
    correct_count = s.correct_count + excluded.correct_count,
    last_correct = case when excluded.last_answered_at >= coalesce(s.last_answered_at, '-infinity') then excluded.last_correct else s.last_correct end,
    last_answered_at = greatest(s.last_answered_at, excluded.last_answered_at);
  return new;
end $$;
create trigger answer_logs_stats after insert on public.answer_logs
  for each row execute function public.bump_question_stats();

-- 分析用ビュー（呼び出したユーザーの行だけが見える）
create view public.v_accuracy_by_category with (security_invoker = true) as
  select l.user_id, l.book_id, coalesce(q.category, '未設定') as category,
         count(*) as attempts, count(*) filter (where l.is_correct) as correct,
         round(avg(l.is_correct::int)::numeric, 3) as rate
  from public.answer_logs l left join public.questions q on q.id = l.question_id
  group by 1, 2, 3;

create view public.v_accuracy_by_chapter with (security_invoker = true) as
  select l.user_id, l.book_id, coalesce(q.chapter, '未設定') as chapter,
         count(*) as attempts, count(*) filter (where l.is_correct) as correct,
         round(avg(l.is_correct::int)::numeric, 3) as rate
  from public.answer_logs l left join public.questions q on q.id = l.question_id
  group by 1, 2, 3;

-- RLS
alter table public.books          enable row level security;
alter table public.book_versions  enable row level security;
alter table public.questions      enable row level security;
alter table public.answer_logs    enable row level security;
alter table public.question_stats enable row level security;
alter table public.study_sessions enable row level security;

create policy "教材はログインユーザーが読める" on public.books          for select to authenticated using (true);
create policy "教材はログインユーザーが読める" on public.book_versions  for select to authenticated using (true);
create policy "教材はログインユーザーが読める" on public.questions      for select to authenticated using (true);

create policy "自分の回答を読む"   on public.answer_logs for select to authenticated using (user_id = auth.uid());
create policy "自分の回答を追加"   on public.answer_logs for insert to authenticated with check (user_id = auth.uid());
create policy "自分の集計を読む"   on public.question_stats for select to authenticated using (user_id = auth.uid());
create policy "自分のセッション"   on public.study_sessions for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- 回答ログは追記のみ（改ざん防止のため update/delete のポリシーは作らない）
revoke update, delete on public.answer_logs from anon, authenticated;
revoke insert, update, delete on public.question_stats from anon, authenticated;
revoke all on public.books, public.book_versions, public.questions from anon;

-- 元JSONのバックアップ用の非公開バケット
insert into storage.buckets (id, name, public) values ('book-json', 'book-json', false)
  on conflict (id) do nothing;
