"use client";

// ログイン（メールのリンクでログイン）。Supabaseが未設定なら何も表示しない。
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

export default function Account() {
  const c = supabase();
  const [email, setEmail] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!c) return;
    c.auth.getSession().then(({ data }) => setEmail(data.session?.user.email ?? null));
    const { data } = c.auth.onAuthStateChange((_e, s) => setEmail(s?.user.email ?? null));
    return () => data.subscription.unsubscribe();
  }, [c]);

  if (!c) return null;
  if (email) {
    return (
      <div className="card spread">
        <div><div className="muted">ログイン中（履歴を端末間で同期）</div>{email}</div>
        <button className="btn" onClick={() => c.auth.signOut()}>ログアウト</button>
      </div>
    );
  }
  const send = async () => {
    setMsg(null);
    const { error } = await c.auth.signInWithOtp({ email: input.trim(), options: { emailRedirectTo: window.location.origin } });
    setMsg(error ? `送信できませんでした：${error.message}` : "ログイン用のリンクをメールで送りました。メールのリンクを開いてください。");
  };
  return (
    <div className="card">
      <strong>ログインすると、学習履歴をスマホとPCで共有できます</strong>
      <div className="muted">ログインしなくても、この端末の中に履歴を保存して使えます。</div>
      <div className="row" style={{ marginTop: 8, flexWrap: "nowrap" }}>
        <input type="text" inputMode="email" autoComplete="email" placeholder="メールアドレス" value={input} onChange={(e) => setInput(e.target.value)} />
        <button className="btn primary" disabled={!/.+@.+\..+/.test(input)} onClick={send}>送信</button>
      </div>
      {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
    </div>
  );
}
