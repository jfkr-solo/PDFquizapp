-- RLSとトリガーの確認。 psql -v ON_ERROR_STOP=1 -f で実行し、最後に「ALL OK」が出れば合格
\set ON_ERROR_STOP 1
insert into auth.users values ('00000000-0000-0000-0000-00000000000a'), ('00000000-0000-0000-0000-00000000000b');
insert into public.books (book_id, title, current_version) values ('T01', 'テスト', '1.0');
insert into public.questions (id, book_id, version, chapter, category, question_type, validation_status, body)
  values ('T01-Q0001', 'T01', '1.0', '第1章', 'ネットワーク', 'single_choice', 'auto_ok', '{}'),
         ('T01-Q0002', 'T01', '1.0', '第1章', 'セキュリティ', 'single_choice', 'auto_ok', '{}');

-- ユーザーAとして回答
set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000a', false);
insert into public.answer_logs (id, book_id, question_id, selected, is_correct, answered_at, elapsed_ms, mode) values
  (gen_random_uuid(), 'T01', 'T01-Q0001', '{A}', false, '2026-11-01T00:00:00Z', 1000, 'normal'),
  (gen_random_uuid(), 'T01', 'T01-Q0001', '{C}', true,  '2026-11-02T00:00:00Z', 900,  'normal'),
  (gen_random_uuid(), 'T01', 'T01-Q0002', '{B}', false, '2026-11-03T00:00:00Z', 800,  'exam');
do $$ declare s record; begin
  select * into s from public.question_stats where question_id = 'T01-Q0001';
  assert s.attempts = 2 and s.correct_count = 1 and s.last_correct, '集計トリガー';
  assert (select count(*) from public.answer_logs) = 3, 'Aは自分の回答を3件見られる';
  assert (select rate from public.v_accuracy_by_category where category = 'ネットワーク') = 0.5, 'ビュー';
end $$;

-- 回答ログは書き換えられない
do $$ begin
  begin update public.answer_logs set is_correct = true; raise exception 'update が通ってしまった';
  exception when insufficient_privilege then null; end;
end $$;
-- 他人のuser_idでは書けない
do $$ begin
  begin
    insert into public.answer_logs (id, user_id, book_id, question_id, is_correct, answered_at, mode)
      values (gen_random_uuid(), '00000000-0000-0000-0000-00000000000b', 'T01', 'T01-Q0001', true, now(), 'normal');
    raise exception '他人の行を書けてしまった';
  exception when insufficient_privilege then null; end;
end $$;
-- 教材は読めるが書けない
do $$ begin
  assert (select count(*) from public.questions) = 2, '教材を読める';
  begin update public.questions set validation_status = 'verified'; 
    if found then raise exception '教材を書き換えられてしまった'; end if;
  exception when insufficient_privilege then null; end;
end $$;

-- ユーザーBからはAの履歴が見えない
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', false);
do $$ begin
  assert (select count(*) from public.answer_logs) = 0, 'Bには見えない';
  assert (select count(*) from public.question_stats) = 0, 'Bには集計も見えない';
  assert (select count(*) from public.v_accuracy_by_category) = 0, 'Bにはビューも見えない';
end $$;

-- 未ログイン（anon）は教材も読めない
reset role; set role anon;
do $$ begin
  begin perform 1 from public.questions; raise exception 'anonが教材を読めた';
  exception when insufficient_privilege then null; end;
end $$;
reset role;
select 'ALL OK';
