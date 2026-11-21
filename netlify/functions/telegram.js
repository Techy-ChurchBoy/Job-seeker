// Telegram webhook: a message with a job link starts the apply-job workflow on GitHub.
// Only the chat ID in TELEGRAM_CHAT_ID is accepted; everyone else is ignored.
const REPO = "Techy-ChurchBoy/Job-seeker";

function parse(text) {
  const out = { url: "", company: "", email: "", description: "" };
  let mode = "";
  for (const raw of (text || "").split("\n")) {
    const line = raw.trim();
    const m = line.match(/^(link|company|email|description):\s*(.*)$/i);
    if (m) {
      mode = m[1].toLowerCase();
      const value = m[2];
      if (mode === "link") out.url = value.trim();
      else if (mode === "description") out.description = value;
      else out[mode] = value.trim();
      continue;
    }
    if (!out.url) {
      const found = line.match(/https?:\/\/\S+/);
      if (found) { out.url = found[0]; continue; }
    }
    if (mode === "description") out.description += "\n" + raw;
  }
  out.description = out.description.trim();
  return out;
}

async function reply(chatId, text) {
  await fetch(`https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
}

exports.handler = async (event) => {
  const ok = { statusCode: 200, body: "ok" };
  if (event.httpMethod !== "POST") return { statusCode: 405, body: "POST only" };
  if (event.headers["x-telegram-bot-api-secret-token"] !== process.env.TELEGRAM_SECRET) {
    return { statusCode: 401, body: "bad secret" };
  }

  const update = JSON.parse(event.body || "{}");
  const msg = update.message || update.edited_message;
  if (!msg || String(msg.chat.id) !== String(process.env.TELEGRAM_CHAT_ID)) return ok;
  const chatId = msg.chat.id;

  const job = parse(msg.text);
  if (!job.url) {
    await reply(chatId, "Send a job link. Optional lines: company: ..., email: ..., description: ... (paste the description after it).");
    return ok;
  }

  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/apply-job.yml/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "jobbot-telegram",
    },
    body: JSON.stringify({
      ref: "main",
      inputs: { job_url: job.url, company: job.company, email: job.email, job_description: job.description },
    }),
  });

  if (!res.ok) {
    await reply(chatId, `GitHub returned ${res.status}. Check the GITHUB_TOKEN permissions in Netlify.`);
  } else {
    await reply(chatId, `Started applying to ${job.url}. I'll message you when it's done.`);
  }
  return ok;
};
