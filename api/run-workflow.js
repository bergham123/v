const fetch = require("node-fetch");

const OWNER = "bergham123";
const REPO = "v";
const WORKFLOW_FILE = "run-param.yml";
const BRANCH = "main";

module.exports = async (req, res) => {
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  try {
    if (req.method !== 'GET') return res.status(405).json({ error: "Method not allowed" });

    const { api } = req.query;
    if (!api) return res.status(400).json({ error: "Missing api parameter" });

    const response = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
      {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `token ${process.env.GITHUB_TOKEN}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ref: BRANCH,
          inputs: { api_param: api },
        }),
      }
    );

    if (!response.ok) {
      return res.status(500).json({ error: "Failed to trigger GitHub" });
    }

    return res.json({ message: "Workflow started. Check GitHub Actions tab." });

  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
};
