"use client";

// ログイン。Supabaseが未設定なら何も表示しない。
// - パスワードでログイン（iPhoneのパスワード自動入力で1タップ。ホーム画面のアイコンからでも使える）
// - パスワード未設定の人は、メールのリンクでログイン → ログイン中の画面でパスワードを設定
import { useEffect, useState, type FormEvent } from "react";
import { supabase } from "@/lib/supabase";

export default function Account() {
  const c = supabase();
  const [email, setEmail] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [showSetPw, setShowSetPw] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!c) return;
    c.auth.getSession().then(({ data }) => setEmail(data.session?.user.email ?? null));
    const { data } = c.auth.onAuthStateChange((_e, s) => setEmail(s?.user.email ?? null));
    return () => data.subscription.unsubscribe();
  }, [c]);

  if (!c) return null;

  if (email) {
    const savePassword = async (e: FormEvent) => {
      e.preventDefault();
      setBusy(true); setMsg(null);
      const { error } = await c.auth.updateUser({ password: newPassword });
      setBusy(false);
      if (error) { setMsg(`設定できませんでした：${error.message}`); return; }
      setNewPassword(""); setShowSetPw(false);
      setMsg("パスワードを設定しました。次からはメールアドレスとパスワードでログインできます。");
    };
    return (
      <div className="card">
        <div className="spread">
          <div><div className="muted">ログイン中（履歴を端末間で同期）</div>{email}</div>
          <button className="btn" onClick={() => { setMsg(null); c.auth.signOut(); }}>ログアウト</button>
        </div>
        {!showSetPw && <button className="btn" style={{ marginTop: 8 }} onClick={() => { setMsg(null); setShowSetPw(true); }}>パスワードを設定・変更</button>}
        {showSetPw && (
          <form onSubmit={savePassword} className="row" style={{ marginTop: 8, flexWrap: "nowrap" }}>
            {/* iPhoneのキーチェーンがメールアドレスと組にして保存できるよう、ユーザー名欄を隠して置く */}
            <input type="email" autoComplete="username" value={email} readOnly hidden />
            <input type="password" autoComplete="new-password" placeholder="新しいパスワード（6文字以上）" value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)} />
            <button className="btn primary" type="submit" style={{ whiteSpace: "nowrap" }} disabled={busy || newPassword.length < 6}>保存</button>
          </form>
        )}
        {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
      </div>
    );
  }

  const valid = /.+@.+\..+/.test(input);
  const login = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    const { error } = await c.auth.signInWithPassword({ email: input.trim(), password });
    setBusy(false);
    if (error) setMsg("ログインできませんでした。パスワードをまだ設定していない場合は、下の「メールでログイン用リンクを送る」からログインして、パスワードを設定してください。");
  };
  const sendLink = async () => {
    setBusy(true); setMsg(null);
    const { error } = await c.auth.signInWithOtp({ email: input.trim(), options: { emailRedirectTo: window.location.origin, shouldCreateUser: false } });
    setBusy(false);
    setMsg(error ? `送信できませんでした：${error.message}` : "ログイン用のリンクをメールで送りました。リンクを長押しでコピーし、このアプリと同じブラウザで開いてください。");
  };
  return (
    <div className="card">
      <strong>ログインすると、学習履歴をスマホとPCで共有できます</strong>
      <div className="muted">ログインしなくても、この端末の中に履歴を保存して使えます。</div>
      <form onSubmit={login} style={{ marginTop: 8, display: "grid", gap: 8 }}>
        <input type="email" inputMode="email" autoComplete="username" placeholder="メールアドレス" value={input} onChange={(e) => setInput(e.target.value)} />
        <input type="password" autoComplete="current-password" placeholder="パスワード" value={password} onChange={(e) => setPassword(e.target.value)} />
        <button className="btn primary" type="submit" disabled={busy || !valid || !password}>ログイン</button>
      </form>
      <button className="btn" style={{ marginTop: 8 }} disabled={busy || !valid} onClick={sendLink}>メールでログイン用リンクを送る</button>
      {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
    </div>
  );
}
