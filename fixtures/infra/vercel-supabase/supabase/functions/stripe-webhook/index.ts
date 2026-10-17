import { createClient } from "npm:@supabase/supabase-js@2";
const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
Deno.serve(async (req) => {
  const { user_id, plan } = await req.json();      // trusted as sent, no signature check
  await admin.from("profiles").update({ plan }).eq("id", user_id);
  return new Response("ok", { headers: { "Access-Control-Allow-Origin": "*" } });
});
