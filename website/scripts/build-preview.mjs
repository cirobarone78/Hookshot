import { spawnSync } from 'node:child_process';
const env = {
  ...process.env,
  DOCS_SITE_URL: 'https://bibigurl-yum.github.io',
  DOCS_SOURCE_REPOSITORY: 'bibigurl-yum/Hookshot',
  DOCS_SOURCE_BRANCH: 'docs/starlight-preview',
};
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
for (const task of ['build', 'check']) {
  const result = spawnSync(npm, ['run', task], { env, stdio: 'inherit', shell: process.platform === 'win32' });
  if (result.status !== 0) process.exit(result.status ?? 1);
}
