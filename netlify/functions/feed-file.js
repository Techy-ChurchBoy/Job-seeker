// Serves one data file from the feed folder (sites, outstanding list, run results), only to someone with the dashboard password.
const REPO = "Techy-ChurchBoy/Job-seeker";

const reply = (statusCode, obj) => ({
  statusCode,
  headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  body: JSON.stringify(obj),
});

exports.handler = async (event) => {
  if (event.httpMethod !== "GET") return reply(405, { error: "GET only" });
  if (!process.env.APPLY_PASSWORD || !process.env.GITHUB_TOKEN) {
    return reply(500, { error: "APPLY_PASSWORD or GITHUB_TOKEN is not set on this site." });
  }
  const headers = Object.fromEntries(Object.entries(event.headers || {}).map(([k, v]) => [k.toLowerCase(), v]));
  if (headers["x-dashboard-password"] !== process.env.APPLY_PASSWORD) return reply(401, { error: "Wrong password." });
  const path = (event.queryStringParameters || {}).path || "";
  if (!/^feed\/[A-Za-z0-9_.\/-]+\.json$/.test(path) || path.includes("..")) return reply(400, { error: "That file is not available." });
  const res = await fetch(`https://api.github.com/repos/${REPO}/contents/${path}`, {
    headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: "application/vnd.github.raw", "User-Agent": "jobbot-dashboard" },
  });
  if (res.status === 404) return reply(404, { error: "Not found yet." });
  if (!res.ok) return reply(502, { error: `GitHub returned ${res.status} reading the data.` });
  return { statusCode: 200, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" }, body: await res.text() };
};
