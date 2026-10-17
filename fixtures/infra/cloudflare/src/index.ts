export default {
  async fetch(req: Request, env: any) {
    const id = new URL(req.url).searchParams.get("id");
    await env.DB.exec(`DELETE FROM orders WHERE id = ${id}`);
    return new Response("done");
  },
};
