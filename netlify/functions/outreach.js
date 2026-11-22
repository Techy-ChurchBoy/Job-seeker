// Starts a location search, or sends the ticked organisations of one batch, by starting the matching workflow.
// Needs APPLY_PASSWORD and GITHUB_TOKEN (Actions read and write).
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

  let workflow, inputs, message;
  if (data.action === "search") {
    const location = String(data.location || "").trim();
    if (!location) return reply(400, { error: "Enter a town or area." });
    workflow = "location-search.yml";
    inputs = { location, categories: String(data.categories || "").trim() };
    message = "Search started. The batch appears on this page in a few minutes.";
  } else if (data.action === "send") {
    const batch = String(data.batch || "").trim();
    const ids = Array.isArray(data.ids) ? data.ids.map(String).join(",") : "";
    if (!/^[a-z0-9-]+\.json$/.test(batch)) return reply(400, { error: "Unknown batch." });
    if (!ids) return reply(400, { error: "Tick at least one organisation." });
    workflow = "outreach-send.yml";
    inputs = { batch, ids };
    message = "Sending started. Results appear on this page after the next refresh.";
  } else if (data.action === "resend") {
    const url = String(data.url || "").trim();
    if (!/^https?:\/\/\S+$/.test(url)) return reply(400, { error: "Paste the job link." });
    workflow = "resend.yml";
    inputs = { job_url: url };
    message = "Resend started. Check Telegram for the result.";
  } else {
    return reply(400, { error: "Unknown action." });
  }

  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "jobbot-outreach",
    },
    body: JSON.stringify({ ref: "main", inputs }),
  });
  if (!res.ok) return reply(502, { error: `GitHub returned ${res.status}. Check GITHUB_TOKEN on this site.` });
  return reply(200, { message });
};
