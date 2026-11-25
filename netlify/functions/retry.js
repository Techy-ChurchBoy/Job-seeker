// Starts the retry workflow for one outstanding cover letter or email.
const REPO = "Techy-ChurchBoy/Job-seeker";

const reply = (statusCode, obj) => ({
  statusCode,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(obj),
});

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") return reply(405, { error: "POST only" });
  if (!process.env.APPLY_PASSWORD || !process.env.GITHUB_TOKEN) {
    return reply(500, { error: "APPLY_PASSWORD or GITHUB_TOKEN is not set on this site." });
  }
  let data;
  try {
    data = JSON.parse(event.body || "{}");
  } catch {
    return reply(400, { error: "Bad request." });
  }
  if (data.password !== process.env.APPLY_PASSWORD) return reply(401, { error: "Wrong password." });
  const kind = data.kind === "send" ? "send" : "draft";
  const url = String(data.url || "").trim();
  if (kind === "draft" && !/^https?:\/\/\S+$/.test(url)) return reply(400, { error: "No job link to retry." });

  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/retry.yml/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "jobbot-retry",
    },
    body: JSON.stringify({ ref: "main", inputs: { kind, url: kind === "draft" ? url : "" } }),
  });
  if (!res.ok) return reply(502, { error: `GitHub returned ${res.status}. Check GITHUB_TOKEN on the site.` });
  return reply(200, { message: "Retry started. It takes a few minutes." });
};
