import release from '../../../explorer_mcp/server.json';
import researchSkill from '../../../explorer_mcp/skills/explore-congress/SKILL.md?raw';

export { release };
export const repository = release.repository.url;
export const remoteMcp = release.remotes[0].url;
export const releaseUrl = `${repository}/releases/tag/congress-mcp-v${release.version}`;
export const pypiUrl = `https://pypi.org/project/congressional-explorer-mcp/${release.version}/`;
const downloads = `${repository}/releases/download/congress-mcp-v${release.version}`;
export const desktopBundle = `${downloads}/congress-explorer-${release.version}.mcpb`;
export const pluginBundle = `${downloads}/congress-explorer-${release.version}.plugin.zip`;
export const webPluginBundle = `${downloads}/congress-explorer-web-${release.version}.plugin.zip`;
export const codexSetup = `codex plugin marketplace add civictechdc/congressional-tech --ref congress-mcp-v${release.version} --sparse .agents/plugins --sparse apps/explorer_mcp\ncodex plugin add congress-explorer@congressional-tech`;
export const claudeSetup = 'claude plugin install congress-explorer --marketplace civictechdc/congressional-tech';
export const skillSetup = 'npx skills add civictechdc/congressional-tech --skill explore-congress';
export const install = `uv tool install --python 3.12 congressional-explorer-mcp==${release.version}`;

const code = (text: string) => '```sh\n' + text + '\n```';

// Share release values with the human page and reuse the plugin's maintained skill.
export const agentInstructions = `# Congress Explorer: setup and research instructions

Help the user connect Congress Explorer in their chosen AI app, then continue their congressional research. If their app or browser/desktop environment is unclear, ask before choosing an installation. Explain each step in plain language. Preserve existing client settings.

Software version: ${release.version}
Human setup page: ${release.websiteUrl}
Release downloads: ${releaseUrl}

## ChatGPT in a browser

Use the hosted MCP server: ${remoteMcp}
Transport: Streamable HTTP. Authentication: none.

Guide the user to https://chatgpt.com/plugins → Add custom MCP server. Name it Congress Explorer Web, enter the URL, choose No authentication, then create and install the plugin and select it in a conversation. The user must complete account setup; copying this guide does not register or connect a server. Browser setup needs no local Python, Node.js, uv, or desktop app.

For supported plugin import workflows, the web plugin ZIP includes the remote connection and research skill: ${webPluginBundle}

## Desktop setup (macOS or Linux)

Local Windows installation is not supported. The web connection is available without a local installation. Use the local congress-explorer plugin for desktop sessions and congress-explorer-web for hosted access; they do not automatically switch transports.

### Claude Desktop chat

Use a current Claude Desktop with uv-based extension support. Download ${desktopBundle}, open it in Claude Desktop, and select Install. Alternatively: Settings → Desktop app → Extensions → Advanced settings → Install Extension. The app manages Python and dependencies.

### Claude Code and Cowork

Install uv from https://docs.astral.sh/uv/getting-started/installation/ and use a current Claude Code:

${code(claudeSetup)}

In Cowork desktop, open Customize → Plugins and upload ${pluginBundle}. Start a local task and run /congress-explorer:explore-congress.

### ChatGPT and Codex desktop

Install uv and the Codex CLI (https://developers.openai.com/codex/cli/), then run:

${code(codexSetup)}

Start a local conversation and select Congress Explorer. This is a repository marketplace installation; a public plugin directory listing is separate.

### Manual installation and other clients

${code(`${install}\ncongress-explorer-mcp prepare\ncongress-explorer-mcp check`)}

The check must report status ok and six tools. If the shell cannot find the command, run uv tool update-shell and open a new terminal.

Run congress-explorer-mcp config --client CLIENT, choosing claude-desktop, codex, cursor, or claude-code. The command prints configuration; it does not edit files. Merge the congress entry into mcpServers for Claude Desktop or Cursor, or [mcp_servers.congress] in ~/.codex/config.toml for Codex. For Claude Code, save the JSON and launch with --mcp-config /absolute/path/to/file.json. Preserve other entries and restart the connection. Use the same --data-dir for prepare, check, and config if customized.

### Optional research skill

The full plugin includes the research skill. To install only the instructions with Node.js 22.20 or later:

${code(skillSetup)}

This does not connect or install the MCP server. Choose the user's agent; add --global only if they want the skill across projects.

## Research, data updates, and troubleshooting

${researchSkill.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '').trim()}
`;
