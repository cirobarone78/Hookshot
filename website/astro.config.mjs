import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { siteConfig } from './site.config.mjs';

export default defineConfig({
  site: siteConfig.origin,
  base: siteConfig.base,
  trailingSlash: 'always',
  integrations: [starlight({
    title: 'Hookshot',
    description: 'Hookshot installation instructions, settings, troubleshooting, and contributor documentation.',
    favicon: '/assets/hookshot.png',
    customCss: ['./src/styles/forest.css'],
    components: {
      Header: './src/components/Header.astro',
      Hero: './src/components/Hero.astro',
      Footer: './src/components/Footer.astro',
    },
    editLink: { baseUrl: siteConfig.editBase + 'website/' },
    tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 2 },
    sidebar: [
      { label: 'Overview', slug: '' },
      { label: 'Progress & updates', slug: 'progress' },
      { label: 'Is Hookshot a virus?', slug: 'antivirus' },
      { label: 'Setup and settings', items: [
        { label: 'Check compatibility', slug: 'compatibility' },
        { label: 'Getting started', slug: 'guides/getting-started' },
        { label: 'Graphics & controls', slug: 'guides/graphics-and-controls' },
        { label: 'Updates & saves', slug: 'guides/updates-and-saves' },
        { label: 'Transfer a save', slug: 'guides/saves' },
      ] },
      { label: 'Help and support', items: [
        { label: 'Common issues', slug: 'guides/common-issues', badge: { text: '11 answers', variant: 'note' } },
        { label: 'Report & contribute', slug: 'guides/reporting-and-contributing' },
        { label: 'Report a bug ↗', link: 'https://github.com/NotRexed/Hookshot/issues/new/choose' },
      ] },
      { label: 'Development', collapsed: true, items: [
        { label: 'Reference manual', slug: 'reference/manual' },
        { label: 'Development ↗', link: 'https://github.com/NotRexed/Hookshot/blob/main/docs/development.md' },
        { label: 'Architecture ↗', link: 'https://github.com/NotRexed/Hookshot/blob/main/docs/design.md' },
        { label: 'Contributing', slug: 'reference/contributing' },
        { label: 'Technical notes ↗', link: 'https://github.com/NotRexed/Hookshot/tree/main/docs' },
        { label: 'Versioning ↗', link: 'https://github.com/NotRexed/Hookshot/blob/main/docs/versioning.md' },
        { label: 'Workflow ↗', link: 'https://github.com/NotRexed/Hookshot/blob/main/docs/workflow.md' },
        { label: 'Pipeline lists ↗', link: 'https://github.com/NotRexed/Hookshot/blob/main/assets/pipeline_states/README.md' },
      ] },
      { label: 'About the preview', slug: 'about' },
    ],
  })],
});
