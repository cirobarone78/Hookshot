export async function getLatestRelease(fetcher = fetch) {
  try {
    const response = await fetcher('https://api.github.com/repos/NotRexed/Hookshot/releases/latest', {
      headers: { Accept: 'application/vnd.github+json' },
      credentials: 'omit',
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    const release = await response.json();
    if (release.draft !== false || release.prerelease !== false ||
        typeof release.tag_name !== 'string' || !release.tag_name.trim()) return null;
    return {
      version: release.tag_name,
      url: `https://github.com/NotRexed/Hookshot/releases/tag/${encodeURIComponent(release.tag_name)}`,
    };
  } catch {
    // Keep the permanent latest-release link usable if GitHub is unavailable or rate-limited.
    return null;
  }
}
