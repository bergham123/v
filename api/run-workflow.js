// api/run-workflow.js
// We use require here to be safer on Vercel without a package.json
const fetch = require("node-fetch");

const OWNER = "bergham123";
const REPO = "v";
// IMPORTANT: Make sure your workflow file is named exactly 'run-param.yml'
const WORKFLOW_FILE = "run-param.yml"; 
const BRANCH = "main";

module.exports = async (req, res) => {
  // Enable CORS just in case
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  try {
    // Only allow GET requests for the link
    if (req.method !== 'GET') {
      return res.status(405).json({ error: "Method not allowed" });
    }

    const { api } = req.query;
    if (!api) return res.status(400).json({ error: "Missing api parameter" });

    console.log("Triggering workflow with param:", api);

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
      const errorText = await response.text();
      console.error("GitHub Error:", errorText);
      return res.status(500).json({ 
        error: "Failed to trigger workflow", 
        details: errorText,
        status: response.status 
      });
    }

    return res.json({ 
      message: "Workflow started. Check GitHub for status." 
    });

  } catch (error) {
    console.error("Vercel Error:", error);
    return res.status(500).json({ error: error.message });
  }
};
