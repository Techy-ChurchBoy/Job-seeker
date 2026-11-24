// Vercel entry point. The logic lives in netlify/functions/feed.js, so both hosts run the same code.
const { handler } = require("../netlify/functions/feed.js");

module.exports = async (req, res) => {
  const out = await handler({ httpMethod: req.method, headers: req.headers || {}, queryStringParameters: req.query || {}, body: "" });
  res.status(out.statusCode).setHeader("Content-Type", "application/json").send(out.body);
};
