// Reads and sets whether the bot submits Greenhouse applications itself.
// Stored as the GitHub repo variable AUTO_SUBMIT ("true" or "false"). Setting it needs APPLY_PASSWORD.
const REPO = "Techy-ChurchBoy/Job-seeker";
const NAME = "AUTO_SUBMIT";

const reply = (statusCode, obj) => ({
  statusCode,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(obj),
});

const gh = (path, opts = {}) =>
  fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...opts,
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "jobbot-mode",
    },
  });

async function currentValue() {
  const res = await gh(`/actions/variables/${NAME}`);
  if (res.status === 404) return "false";
  if (!res.ok) throw new Error(`GitHub returned ${res.status} reading the setting. The token needs Variables read access.`);
  return (await res.json()).value;
}

exports.handler = async (event) => {
  if (!process.env.APPLY_PASSWORD || !process.env.GITHUB_TOKEN) {
    return reply(500, { error: "APPLY_PASSWORD or GITHUB_TOKEN is not set on the site." });
  }

  if (event.httpMethod === "GET") {
    try {
      return reply(200, { auto: (await currentValue()).toLowerCase() === "true" });
    } catch (e) {
      return reply(502, { error: e.message });
    }
  }
  if (event.httpMethod !== "POST") return reply(405, { error: "GET or POST only" });

  let data;
  try {
    data = JSON.parse(event.body || "{}");
  } catch {
    return reply(400, { error: "Bad request." });
  }
  if (data.password !== process.env.APPLY_PASSWORD) return reply(401, { error: "Wrong password." });

  const value = data.auto === true ? "true" : "false";
  const exists = (await gh(`/actions/variables/${NAME}`)).status !== 404;
  const res = exists
    ? await gh(`/actions/variables/${NAME}`, { method: "PATCH", body: JSON.stringify({ name: NAME, value }) })
    : await gh(`/actions/variables`, { method: "POST", body: JSON.stringify({ name: NAME, value }) });
  if (!res.ok) {
    return reply(502, { error: `GitHub returned ${res.status}. The token needs Variables read and write access.` });
  }
  return reply(200, { auto: value === "true" });
};
