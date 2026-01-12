// api/run-workflow.js
import fetch from "node-fetch";

// GitHub info
const OWNER = "bergham123";
const REPO = "v";
const WORKFLOW_FILE = "run-param.yml";
const BRANCH = "main";
const STATE_FILE_PATH = "workflow-state.json";
const MAX_RUNS = 100;

// Helper: Check if any workflow is currently running or queued
async function isWorkflowRunning(token) {
  const response = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/runs?status=in_progress&status=queued`,
    {
      headers: {
        Authorization: `token ${token}`,
        Accept: "application/vnd.github+json",
      },
    }
  );
  const data = await response.json();
  return data.total_count > 0;
}

// Helper: Read state file
async function getState(token) {
  const response = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/contents/${STATE_FILE_PATH}`,
    {
      headers: {
        Authorization: `token ${token}`,
        Accept: "application/vnd.github+json",
      },
    }
  );
  if (!response.ok) throw new Error("Failed to read state file");
  const fileData = await response.json();
  const content = JSON.parse(Buffer.from(fileData.content, "base64").toString("utf-8"));
  return { content, sha: fileData.sha };
}

// Helper: Update state file
async function updateState(token, content, sha) {
  const response = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/contents/${STATE_FILE_PATH}`,
    {
      method: "PUT",
      headers: {
        Authorization: `token ${token}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: "Update workflow run count",
        content: Buffer.from(JSON.stringify(content, null, 2)).toString("base64"),
        sha: sha,
        branch: BRANCH,
      }),
    }
  );
  if (!response.ok) throw new Error("Failed to update state file");
}

export default async function handler(req, res) {
  try {
    const { api } = req.query;
    if (!api) return res.status(400).json({ error: "Missing api parameter" });

    const token = process.env.GITHUB_TOKEN;

    // 1. Check if GitHub is currently running a workflow
    const running = await isWorkflowRunning(token);
    if (running) {
      return res.status(429).json({ 
        error: "Workflow is currently running. Please wait until it finishes." 
      });
    }

    // 2. Get current run count
    const { content: state, sha } = await getState(token);

    if (state.runs >= MAX_RUNS) {
      return res.status(403).json({ error: "Run limit reached (100)." });
    }

    // 3. Trigger the new workflow
    const triggerResponse = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
      {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `token ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ref: BRANCH,
          inputs: { api_param: api },
        }),
      }
    );

    if (!triggerResponse.ok) {
      return res.status(500).json({ error: "Failed to trigger workflow" });
    }

    // 4. Increment run count
    state.runs += 1;
    await updateState(token, state, sha);

    return res.json({
      message: "Workflow triggered successfully",
      api_param: api,
      runs_done: state.runs,
      runs_left: MAX_RUNS - state.runs,
    });

  } catch (error) {
    console.error(error);
    return res.status(500).json({ error: error.message });
  }
}
