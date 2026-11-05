import { agentInstructions } from '../../lib/mcp-setup';

export function GET() {
  return new Response(agentInstructions, {
    headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
  });
}
