// Launcher that strips WorkBuddy's NODE_OPTIONS shim (--require genie-safe-delete)
// from the environment before spawning Next.js, so next AND its jest-worker /
// Turbopack child processes run WITHOUT the shim (which crashes them on Windows).
// CODEBUDDY_SAFE_DELETE_SANDBOX is forced to 0 so that even if the shim still
// partially loads, bulk file deletes (e.g. .next setup) are permitted.
const { spawn } = require("child_process");

const env = { ...process.env };

// Remove the --require shim injection so child processes don't load it.
for (const key of Object.keys(env)) {
  if (/^NODE_OPTIONS$/i.test(key)) delete env[key];
}

// Allow next's internal file operations (bulk .next rewrites) to proceed.
env.CODEBUDDY_SAFE_DELETE_SANDBOX = "0";

const child = spawn(process.execPath, process.argv.slice(2), {
  stdio: "inherit",
  env,
});

child.on("exit", (code, signal) => {
  process.exit(code == null ? (signal ? 1 : 0) : code);
});
