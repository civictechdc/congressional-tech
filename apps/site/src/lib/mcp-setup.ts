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
export const setupDocs = {
  claudeDesktop: 'https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop',
  claudeWeb: 'https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp',
  claudeConnectors: 'https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities',
  codex: 'https://developers.openai.com/codex/plugins',
  codexMarketplace: 'https://learn.chatgpt.com/docs/developer-commands#codex-plugin-marketplace',
  chatgpt: 'https://developers.openai.com/api/docs/guides/custom-mcp-server',
};

const code = (text: string) => '```sh\n' + text + '\n```';

// Share release values with the human page and reuse the plugin's maintained skill.
export const agentInstructions = `# Congress Explorer: setup and research instructions

Help the user connect Congress Explorer in their chosen AI app, then continue their congressional research. If their app or browser/desktop environment is unclear, ask before choosing an installation. Explain each step in plain language. Preserve existing client settings.

Software version: ${release.version}
Human setup page: ${release.websiteUrl}
Release downloads: ${releaseUrl}

Setup steps checked against the linked official documentation on November 5, 2026.

## Desktop apps (macOS or Linux)

Local Windows installation is not supported. The web connection is available without a local installation. Use the local congress-explorer plugin for desktop sessions and congress-explorer-web for hosted access; they do not automatically switch transports.

### Claude desktop

Download ${desktopBundle}. In a current Claude Desktop, open Settings → Desktop app → Manage beside Extensions → Advanced settings → Install Extension. Select the downloaded .mcpb file and complete installation. Older layouts put Extensions directly under Settings. This bundle uses the app's uv runtime to manage Python and dependencies. In a chat, use + → Connectors to check that Congress Explorer is available.

Official guide: ${setupDocs.claudeDesktop}

### Codex desktop

Install uv and the Codex CLI (https://developers.openai.com/codex/cli/), then run:

${code(codexSetup)}

Open Codex in the ChatGPT desktop app, start a new local conversation, and type @ to select Congress Explorer. This installs from the project's GitHub marketplace; it does not imply a public directory listing.

Official guides: ${setupDocs.codex} and ${setupDocs.codexMarketplace}

## Web browsers

Both browser connections use ${remoteMcp} over Streamable HTTP without authentication. Browser setup needs no local Python, Node.js, uv, or desktop app. The user must complete account setup; copying this guide does not register a connection.

### Claude web

In Claude, open Customize → Connectors. Choose Add → Custom → Web; some accounts instead show Add custom connector. Name it Congress Explorer, paste the server URL, and continue through the settings. Choose No sign in under Authentication; no API key or extra request headers are needed. Finish with Add. In a new conversation, use + → Connectors to enable Congress Explorer. An organization owner or authorized administrator may need to add a work-account connector first. Claude makes remote MCP requests from Anthropic's cloud, not from the user's browser.

Official guides: ${setupDocs.claudeWeb} and ${setupDocs.claudeConnectors}

### ChatGPT web

Open https://chatgpt.com/plugins, select + → Add custom MCP server, and name it Congress Explorer Web. Under Connection, enter the server URL. Choose No authentication, review the warning and acknowledge it, then select Create as a plugin. Review the discovered tools and install the plugin. In a new conversation, type @ and choose Congress Explorer Web. Account and workspace restrictions may limit this option.

Official guide: ${setupDocs.chatgpt}

For supported plugin import workflows, the web ZIP includes the remote connection and research skill: ${webPluginBundle}

## Other desktop options

### Claude Code and Cowork

Install uv from https://docs.astral.sh/uv/getting-started/installation/ and use a current Claude Code:

${code(claudeSetup)}

In Cowork desktop, open Customize → Plugins and upload ${pluginBundle}. Start a local task and run /congress-explorer:explore-congress.

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
