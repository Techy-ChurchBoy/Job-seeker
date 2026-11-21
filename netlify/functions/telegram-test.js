// Runs each step of the Telegram path from the dashboard, one at a time, and reports which step fails.
// Steps: settings present, webhook status, bot can message you, apply-job workflow starts.
// It starts a test run with no email, so nothing is sent to an employer.
const REPO = "Techy-ChurchBoy/Job-seeker";

const TEST_DESCRIPTION = [
  "Job title: Junior Accountant (test posting)",
  "This is a test posting used to check the apply pipeline. Reconcile bank accounts, support month-end close,",
  "and prepare schedules. Requirements: accounting degree, Excel, and a QuickBooks or Sage background.",
  "This posting is not real and no email is sent for it.",
].join("\n");

const reply = (statusCode, obj) => ({
  statusCode,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(obj),
});

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") return reply(405, { error: "POST only" });
  if (!process.env.APPLY_PASSWORD) return reply(500, { error: "APPLY_PASSWORD is not set on the site." });

  let data;
  try { data = JSON.parse(event.body || "{}"); } catch { return reply(400, { error: "Bad request." }); }
  if (data.password !== process.env.APPLY_PASSWORD) return reply(401, { error: "Wrong password." });

  const steps = [];
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  const github = process.env.GITHUB_TOKEN;

  // 1. Settings present
  const missing = [
    ["TELEGRAM_BOT_TOKEN", token], ["TELEGRAM_CHAT_ID", chatId], ["GITHUB_TOKEN", github],
  ].filter(([, v]) => !v).map(([k]) => k);
  steps.push({ name: "Settings", ok: missing.length === 0,
               detail: missing.length ? `Missing on this site: ${missing.join(", ")}` : "All three are set." });
  if (missing.length) return reply(200, { steps });

  // 2. Webhook status (what Telegram reports about delivering messages to this site)
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/getWebhookInfo`);
    const info = (await res.json()).result || {};
    const failing = Boolean(info.last_error_message);
    steps.push({ name: "Telegram webhook", ok: !failing && res.ok,
                 detail: failing ? `Telegram reports: ${info.last_error_message}` :
                         `Connected. Messages waiting: ${info.pending_update_count || 0}.` });
  } catch (e) {
    steps.push({ name: "Telegram webhook", ok: false, detail: `Could not check: ${e.message}` });
  }

  // 3. Bot can message you
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: "Dashboard test: the bot can reply to you." }),
    });
    steps.push({ name: "Bot replies to you", ok: res.ok,
                 detail: res.ok ? "Message sent. Check Telegram." :
                         `Telegram returned ${res.status}. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.` });
  } catch (e) {
    steps.push({ name: "Bot replies to you", ok: false, detail: e.message });
  }

  // 4. apply-job workflow starts (no email, pasted description, unique link)
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/apply-job.yml/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${github}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "jobbot-test",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          job_url: `https://example.com/jobs/dashboard-test-${Date.now()}`,
          company: "Dashboard Test Ltd",
          email: "",
          job_description: TEST_DESCRIPTION,
        },
      }),
    });
    steps.push({ name: "Workflow starts", ok: res.ok,
                 detail: res.ok ? "Test run started. Results appear in the Actions tab and on Telegram when it finishes." :
                         `GitHub returned ${res.status}. Check GITHUB_TOKEN has Actions read and write.` });
  } catch (e) {
    steps.push({ name: "Workflow starts", ok: false, detail: e.message });
  }

  return reply(200, { steps });
};
