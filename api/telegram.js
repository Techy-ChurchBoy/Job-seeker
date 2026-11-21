// Vercel entry point for the Telegram webhook. The logic lives in netlify/functions/telegram.js,
// so both hosts run the same code.
const { handler } = require("../netlify/functions/telegram.js");

module.exports = async (req, res) => {
  const body = typeof req.body === "string" ? req.body : JSON.stringify(req.body || {});
  const out = await handler({
    httpMethod: req.method,
    headers: req.headers || {},
    queryStringParameters: req.query || {},
    body,
  });
  res.status(out.statusCode).send(out.body);
};
