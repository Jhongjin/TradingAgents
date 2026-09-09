// Run the Vercel CLI with an ASCII hostname.
//
// Vercel CLI 59.x puts os.hostname() into an HTTP header. On a Windows PC whose
// computer name contains Hangul this fails with
// "Cannot convert argument to a ByteString because the character at index 0
// has a value of 51204". Usage (same arguments as `vercel`):
//
//   NODE_USE_SYSTEM_CA=1 node scripts/vercel_ascii_host.cjs deploy --prod --yes
//
const os = require("os");
os.hostname = () => "vercel-cli-host";
const cli = require("path").join(process.env.APPDATA || "", "npm", "node_modules", "vercel", "dist", "index.js");
process.argv[1] = cli; // keep argv shape: [node, cli, ...args]
require(cli);
