# Congress Explorer Web

This plugin connects to the public Congress Explorer server at
`https://congress-explorer-mcp.mdeeb.workers.dev/mcp` using Streamable HTTP.
Authentication is **None**. It needs no local Python, Node.js, uv, or desktop app.

For ChatGPT web, open [Plugins](https://chatgpt.com/plugins), choose **Add custom
MCP server**, enter the URL, and select **No authentication**. Create and install
the resulting plugin, then ask it to discover the available Congress data.
See the [official connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt).

Use `congress-explorer-web` for hosted sessions and `congress-explorer` for local
desktop sessions. The current plugin format specifies one transport per server;
it does not define automatic browser/desktop selection. Installing both does not
establish a preference. Select the appropriate plugin for the session.

Queries and results pass through the hosted service. The service uses a pinned
public archive release; desktop clients may have selected another release. Always
start with `get_dataset_info`. A cold service may take longer to respond. Local
cache and `prepare` instructions apply only to the desktop plugin.

This directory is a portable plugin source. Its manifests, icons, license, and
research skill are generated from the parent app by `scripts/build_desktop.py`.
Edit the parent sources and regenerate; do not edit the generated copies.
The build emits a separate `congress-explorer-web-VERSION.plugin.zip` containing
only this hosted configuration and its instructions. Repository registration and
ZIP generation do not install or publish a plugin in ChatGPT's directory.
