import type {APIRoute} from 'astro';
import {buildAccountabilityFeedXml} from '../../lib/archive-feed.ts';

const releaseFiles = import.meta.glob('../../../../../docs/releases/*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

export const GET: APIRoute = ({site}) => {
  const body = buildAccountabilityFeedXml({
    releaseFiles,
    site,
    baseUrl: import.meta.env.BASE_URL,
  });

  return new Response(body, {
    headers: {
      'Content-Type': 'application/atom+xml; charset=utf-8',
    },
  });
};
