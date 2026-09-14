const JSON_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};

function response(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

async function totals(store) {
  const [visits, downloads] = await Promise.all([
    store.get("visits"),
    store.get("downloads"),
  ]);
  return {
    visits: Math.max(0, Number.parseInt(visits || "0", 10) || 0),
    downloads: Math.max(0, Number.parseInt(downloads || "0", 10) || 0),
  };
}

export async function onRequestGet({ env }) {
  if (!env.COUNTERS) return response({ error: "counter_store_unavailable" }, 503);
  return response(await totals(env.COUNTERS));
}

export async function onRequestPost({ request, env }) {
  if (!env.COUNTERS) return response({ error: "counter_store_unavailable" }, 503);

  let payload;
  try {
    payload = await request.json();
  } catch (_) {
    return response({ error: "invalid_json" }, 400);
  }

  const key = payload && payload.event === "visit"
    ? "visits"
    : payload && payload.event === "download"
      ? "downloads"
      : "";

  if (!key) return response({ error: "invalid_event" }, 400);

  const current = await totals(env.COUNTERS);
  const next = current[key] + 1;
  await env.COUNTERS.put(key, String(next));
  current[key] = next;
  return response(current);
}
