// Starts the runs workflow (a saved site or a pasted page) when the dashboard password is sent.
// Needs APPLY_PASSWORD and GITHUB_TOKEN, as the other functions do.
const REPO = "Techy-ChurchBoy/Job-seeker";

const reply = (statusCode, obj) => ({
  statusCode,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(obj),
});

const clean = (v, max = 200) => String(v || "").trim().slice(0, max);

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

  const mode = data.mode === "link" ? "link" : "site";
  const siteId = clean(data.site_id, 60);
  const link = clean(data.link_url, 500);
  if (mode === "site" && !/^[a-z0-9-]{1,60}$/i.test(siteId)) return reply(400, { error: "Pick a saved site." });
  if (mode === "link" && !/^https?:\/\/\S+$/.test(link)) return reply(400, { error: "Paste a page link starting with http or https." });
  const country = clean(data.country, 2);
  if (country && !/^[A-Za-z]{2}$/.test(country)) return reply(400, { error: "Country must be two letters, such as US." });

  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/runs.yml/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "jobbot-runs",
    },
    body: JSON.stringify({
      ref: "main",
      inputs: {
        mode,
        site_id: mode === "site" ? siteId : "",
        link_url: mode === "link" ? link : "",
        save_site: data.save_site === true ? "true" : "false",
        site_name: clean(data.site_name, 80),
        keyword: clean(data.keyword, 200),
        category: clean(data.category, 100),
        domain: clean(data.domain, 100),
        language: clean(data.language, 35),
        country: country.toUpperCase(),
        pay_type: clean(data.pay_type, 40),
      },
    }),
  });
  if (!res.ok) return reply(502, { error: `GitHub returned ${res.status}. Check GITHUB_TOKEN on the site.` });
  return reply(200, { message: "Started. Results appear in the list below in a few minutes." });
};
