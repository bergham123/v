// api/run-workflow.js

import fetch from "node-fetch";

// Replace with your repo info
const OWNER = "bergham123";
const REPO = "v";
const WORKFLOW_FILE = "run-param.yml"; // your workflow file name
const BRANCH = "main"; // branch to run workflow

// Max runs allowed
const MAX_RUNS = 100;

// Simple in-memory state (Vercel keeps it per instance)
// For persistence across deployments, consider a JSON file or Vercel KV
let workflowState = {
  runs: 0,
  running: false,
};

export default async function handler(req, res) {
  try {
    const { api } = req.query;

    if (!api) {
      return res.status(400).json({ error: "Missing api parameter" });
    }

    // Check run limit
    if (workflowState.runs >= MAX_RUNS) {
      return res
        .status(403)
        .json({ error: "Run limit reached. Workflow will not run." });
    }

    // Check if workflow is already running
    if (workflowState.running) {
      return res
        .status(429)
        .json({ error: "Workflow is currently running. Try later." });
    }

    // Mark workflow as running
    workflowState.running = true;

    // Call GitHub workflow_dispatch API
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
          inputs: {
            api_param: api,
          },
        }),
      }
    );

    if (!response.ok) {
      workflowState.running = false;
      return res.status(response.status).json({
        error: "Failed to trigger workflow",
        details: await response.text(),
      });
    }

    // Increment runs
    workflowState.runs += 1;

    // After triggering, set running to false
    workflowState.running = false;

    return res.json({
      message: "Workflow triggered successfully",
      api_param: api,
      runs_done: workflowState.runs,
      runs_left: MAX_RUNS - workflowState.runs,
    });
  } catch (error) {
    workflowState.running = false;
    return res.status(500).json({ error: error.message });
  }
}
