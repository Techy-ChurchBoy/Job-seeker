// Gives the dashboard one ready-to-send cover letter PDF, only to someone with the dashboard password.
const REPO = "Techy-ChurchBoy/Job-seeker";

const fail = (statusCode, error) => ({
  statusCode,
  headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  body: JSON.stringify({ error }),
});

exports.handler = async (event) => {
  if (event.httpMethod !== "GET") return fail(405, "GET only");
  if (!process.env.APPLY_PASSWORD || !process.env.GITHUB_TOKEN) return fail(500, "APPLY_PASSWORD or GITHUB_TOKEN is not set on this site.");
  const headers = Object.fromEntries(Object.entries(event.headers || {}).map(([k, v]) => [k.toLowerCase(), v]));
  if (headers["x-dashboard-password"] !== process.env.APPLY_PASSWORD) return fail(401, "Wrong password.");
  const name = (event.queryStringParameters || {}).name || "";
  if (!/^[a-z0-9-]{1,80}$/.test(name)) return fail(400, "That letter is not available.");
  const res = await fetch(`https://api.github.com/repos/${REPO}/contents/applications/pdf/${name}.pdf`, {
    headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: "application/vnd.github.raw", "User-Agent": "jobbot-dashboard" },
  });
  if (res.status === 404) return fail(404, "That letter is not ready yet.");
  if (!res.ok) return fail(502, `GitHub returned ${res.status} reading the letter.`);
  const buf = Buffer.from(await res.arrayBuffer());
  return {
    statusCode: 200,
    isBase64Encoded: true,
    headers: { "Content-Type": "application/pdf", "Content-Disposition": `attachment; filename="${name}.pdf"`, "Cache-Control": "no-store" },
    body: buf.toString("base64"),
  };
};
