// Supabaseクライアント。環境変数が無ければ null（＝ブラウザ保存だけで動く）。
// ここで使うのは anon キーだけ。service_role キーは絶対に置かない。
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null | undefined;

export function supabase(): SupabaseClient | null {
  if (client !== undefined) return client;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  client = url && key ? createClient(url, key, { auth: { persistSession: true, detectSessionInUrl: true } }) : null;
  return client;
}
