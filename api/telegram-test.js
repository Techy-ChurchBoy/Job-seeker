// Vercel entry point. The logic lives in netlify/functions/telegram-test.js, so both hosts run the same code.
const { handler } = require("../netlify/functions/telegram-test.js");

module.exports = async (req, res) => {
  const body = typeof req.body === "string" ? req.body : JSON.stringify(req.body || {});
  const out = await handler({
    httpMethod: req.method,
    headers: req.headers || {},
    queryStringParameters: req.query || {},
    body,
  });
  res.status(out.statusCode).setHeader("Content-Type", "application/json").send(out.body);
};
