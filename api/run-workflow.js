import fetch from "node-fetch";

// GitHub info
const OWNER = "bergham123";
const REPO = "v";
const WORKFLOW_FILE = "run-param.yml";
const BRANCH = "main";
const STATE_FILE_PATH = "workflow-state.json";
const MAX_RUNS = 100;

export default async function handler(req, res) {
  try {
    const { api } = req.query;
    if (!api) return res.status(400).json({ error: "Missing api parameter" });

    // Step 1: Get current workflow state from GitHub
    const getFileResponse = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/contents/${STATE_FILE_PATH}`,
      {
        headers: {
          Authorization: `token ${process.env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
        },
      }
    );

    if (!getFileResponse.ok)
      return res.status(getFileResponse.status).json({ error: "Failed to get state file" });

    const fileData = await getFileResponse.json();
    let state = JSON.parse(Buffer.from(fileData.content, "base64").toString("utf-8"));
    const sha = fileData.sha; // needed to update file

    // Step 2: Check limits
    if (state.runs >= MAX_RUNS)
      return res.status(403).json({ error: "Run limit reached. Workflow will not run." });

    if (state.running)
      return res.status(429).json({ error: "Workflow is currently running. Try later." });

    // Step 3: Mark workflow as running
    state.running = true;
    await updateStateFile(state, sha);

    // Step 4: Trigger GitHub workflow
    const triggerResponse = await fetch(
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

    if (!triggerResponse.ok) {
      state.running = false;
      await updateStateFile(state, sha);
      return res.status(triggerResponse.status).json({
        error: "Failed to trigger workflow",
        details: await triggerResponse.text(),
      });
    }

    // Step 5: Increment runs and reset running
    state.runs += 1;
    state.running = false;
    await updateStateFile(state, sha);

    return res.json({
      message: "Workflow triggered successfully",
      api_param: api,
      runs_done: state.runs,
      runs_left: MAX_RUNS - state.runs,
    });

  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
}

// Helper to update JSON file in GitHub repo
async function updateStateFile(state, sha) {
  const response = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/contents/${STATE_FILE_PATH}`,
    {
      method: "PUT",
      headers: {
        Authorization: `token ${process.env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: "Update workflow state",
        content: Buffer.from(JSON.stringify(state, null, 2)).toString("base64"),
        sha,
        branch: BRANCH,
      }),
    }
  );

  if (!response.ok) {
    throw new Error("Failed to update workflow state file");
  }
}
