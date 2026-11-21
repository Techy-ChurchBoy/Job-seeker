// Telegram webhook. Job links start the apply-job workflow.
// Commands (/status, /applied, /matches, /help) read the repo's status files. They never change anything.
// Only the chat ID in TELEGRAM_CHAT_ID is answered; everyone else is ignored.
const REPO = "Techy-ChurchBoy/Job-seeker";
const MAX_PER_DAY = 10;

const HELP = [
  "Commands:",
  "/status - sending on or paused, sends today, last run",
  "/applied - the last 5 applications sent",
  "/matches - the 5 best matches so far",
  "",
  "To apply to a job, send a link. Optional lines: company:, email:, description:",
].join("\n");

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

function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (c !== "\r") field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  if (!rows.length) return [];
  const [head, ...body] = rows;
  return body.filter(r => r.length === head.length)
             .map(r => Object.fromEntries(head.map((h, i) => [h, r[i]])));
}

async function getFile(path) {
  const res = await fetch(`https://api.github.com/repos/${REPO}/contents/${path}`, {
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github.raw",
      "User-Agent": "jobbot-telegram",
    },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`GitHub returned ${res.status} reading ${path}`);
  return await res.text();
}

async function status() {
  const [raw, pause, applied] = await Promise.all([getFile("status.json"), getFile("PAUSE"), getFile("applied.csv")]);
  const st = raw ? JSON.parse(raw) : null;
  const sent = applied ? parseCsv(applied) : [];
  const today = new Date().toISOString().slice(0, 10);
  const sentToday = sent.filter(r => (r.sent_at || "").startsWith(today)).length;
  const lines = [
    pause !== null ? "Sending: PAUSED" : "Sending: on",
    `Sent today: ${sentToday} of ${MAX_PER_DAY}. Sent in total: ${sent.length}`,
    `Last run: ${st ? st.last_run : "never"} UTC`,
  ];
  if (st && Array.isArray(st.summary)) lines.push("", ...st.summary.slice(-15));
  return lines.join("\n").slice(0, 3500);
}

async function applied() {
  const raw = await getFile("applied.csv");
  const rows = raw ? parseCsv(raw) : [];
  if (!rows.length) return "No applications sent yet.";
  return rows.slice(-5).reverse()
    .map(r => `${(r.sent_at || "").slice(0, 16).replace("T", " ")} ${r.company}: ${r.title} (score ${r.score})`)
    .join("\n");
}

async function matches() {
  const raw = await getFile("matches.csv");
  const rows = raw ? parseCsv(raw) : [];
  const top = rows.map(r => ({ ...r, s: Number(r.score) || 0 })).sort((a, b) => b.s - a.s).slice(0, 5);
  if (!top.length) return "No matches yet.";
  return top.map(r => `${r.s}: ${r.title} at ${r.company}`).join("\n");
}

async function reply(chatId, text) {
  const res = await fetch(`https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
  if (!res.ok) console.log("reply failed with status", res.status, "(check TELEGRAM_BOT_TOKEN)");
}

exports.handler = async (event) => {
  const ok = { statusCode: 200, body: "ok" };
  if (event.httpMethod !== "POST") return { statusCode: 405, body: "POST only" };

  // Accept either the secret in the webhook URL (?key=...) or the secret header.
  // The URL form is the one we rely on, because Netlify passes URL parameters reliably.
  const headers = Object.fromEntries(Object.entries(event.headers || {}).map(([k, v]) => [k.toLowerCase(), v]));
  const query = event.queryStringParameters || {};
  const secret = process.env.TELEGRAM_KEY || process.env.TELEGRAM_SECRET;
  const allowed = Boolean(secret) && (query.key === secret || headers["x-telegram-bot-api-secret-token"] === secret);
  if (!allowed) {
    console.log("rejected: key missing or mismatched. TELEGRAM_KEY set:", Boolean(process.env.TELEGRAM_KEY),
                "TELEGRAM_SECRET set:", Boolean(process.env.TELEGRAM_SECRET),
                "query names:", Object.keys(query).join(","), "header names:", Object.keys(headers).join(","));
    return { statusCode: 401, body: "bad key" };
  }

  const update = JSON.parse(event.body || "{}");
  const msg = update.message || update.edited_message;
  if (!msg) {
    console.log("no message in update; update keys:", Object.keys(update).join(","));
    return ok;
  }
  if (String(msg.chat.id) !== String(process.env.TELEGRAM_CHAT_ID)) {
    console.log("ignored: chat id", msg.chat.id, "does not match TELEGRAM_CHAT_ID (set:", Boolean(process.env.TELEGRAM_CHAT_ID), ")");
    return ok;
  }
  const chatId = msg.chat.id;
  const text = (msg.text || "").trim();

  const command = text.split(/\s|@/)[0].toLowerCase();
  if (command.startsWith("/")) {
    let answer;
    try {
      if (command === "/status") answer = await status();
      else if (command === "/applied") answer = await applied();
      else if (command === "/matches") answer = await matches();
      else answer = HELP;
    } catch (e) {
      answer = `${e.message}. Check that the GITHUB_TOKEN has Contents read access.`;
    }
    await reply(chatId, answer);
    return ok;
  }

  const job = parse(text);
  if (!job.url) {
    await reply(chatId, "Send a job link, or /help for commands.");
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
