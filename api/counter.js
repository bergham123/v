// api/counter.js
const fetch = require("node-fetch");

const OWNER = "bergham123";
const REPO = "v";
const BRANCH = "main";
const FILE = "counter.json";

module.exports = async (req, res) => {
  // Enable CORS so your HTML can call it
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');

  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  try {
    // Fetch the live file directly from GitHub to get the latest number
    const response = await fetch(`https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}/${FILE}`);
    
    if (!response.ok) {
      return res.status(404).json({ error: "Counter file not found" });
    }

    const data = await response.json();

    // Return the count to your website
    return res.status(200).json(data);

  } catch (error) {
    return res.status(500).json({ error: "Failed to load counter" });
  }
};
