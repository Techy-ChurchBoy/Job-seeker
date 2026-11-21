// Starts the apply-job workflow on GitHub when the correct password is sent.
// Needs two Netlify environment variables: APPLY_PASSWORD and GITHUB_TOKEN.
const REPO = "Techy-ChurchBoy/Job-seeker";

const reply = (statusCode, obj) => ({
  statusCode,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(obj),
});

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") return reply(405, { error: "POST only" });
  if (!process.env.APPLY_PASSWORD) return reply(500, { error: "APPLY_PASSWORD is not set on the site." });

  let data;
  try {
    data = JSON.parse(event.body || "{}");
  } catch {
    return reply(400, { error: "Bad request." });
  }
  if (data.password !== process.env.APPLY_PASSWORD) return reply(401, { error: "Wrong password." });

  const url = String(data.job_url || "").trim();
  if (!/^https?:\/\/\S+$/.test(url)) return reply(400, { error: "Add a job link starting with http or https." });

  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/apply-job.yml/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "jobbot-apply",
    },
    body: JSON.stringify({
      ref: "main",
      inputs: {
        job_url: url,
        company: String(data.company || ""),
        email: String(data.email || ""),
        job_description: String(data.job_description || ""),
      },
    }),
  });
  if (!res.ok) return reply(502, { error: `GitHub returned ${res.status}. Check GITHUB_TOKEN on the site.` });

  return reply(200, { message: "Started. Results appear in the run summary on GitHub and in the dashboard." });
};
