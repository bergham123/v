// api/run-workflow.js
import fetch from "node-fetch";

const OWNER = "bergham123";
const REPO = "v";
const WORKFLOW_FILE = "run-param.yml"; // Make sure this matches your file name
const BRANCH = "main";

export default async function handler(req, res) {
  try {
    const { api } = req.query;
    if (!api) return res.status(400).json({ error: "Missing api parameter" });

    // Just trigger the workflow. We let GitHub handle the logic.
    const response = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
      {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `token ${process.env.GITHUB_TOKEN}`, // Your 'workflow' token
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ref: BRANCH,
          inputs: { api_param: api },
        }),
      }
    );

    if (!response.ok) {
      return res.status(500).json({ error: "Failed to trigger" });
    }

    return res.json({ message: "Workflow started. Check GitHub for status." });

  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
}
