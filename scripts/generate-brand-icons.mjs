import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const target = path.join(root, 'apps/web/public');
const svg = await readFile(path.join(target, 'brand-icon.svg'), 'utf8');
const icons = {
  'icon-1024x1024.png': 1024,
  'android-chrome-192x192.png': 192,
  'android-chrome-512x512.png': 512,
  'apple-touch-icon.png': 180,
  'favicon-16x16.png': 16,
  'favicon-32x32.png': 32,
  'favicon-48x48.png': 48,
  'favicon-96x96.png': 96,
  'maskable-icon-192x192.png': 192,
  'maskable-icon-512x512.png': 512,
  'mstile-150x150.png': 150,
};
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  for (const [name, size] of Object.entries(icons)) {
    await page.setViewportSize({ width: size, height: size });
    const background = name.startsWith('maskable-') ? '#061d48' : 'transparent';
    await page.setContent(`<style>html,body{margin:0;background:${background}}svg{display:block;width:100vw;height:100vh}</style>${svg}`);
    await page.screenshot({ path: path.join(target, name), omitBackground: true });
  }
  // ICO supports PNG payloads; retain the existing 16/32/48 px favicon variants.
  const sizes = [16, 32, 48];
  const payloads = await Promise.all(sizes.map(size => readFile(path.join(target, `favicon-${size}x${size}.png`))));
  const directory = Buffer.alloc(6 + 16 * sizes.length);
  directory.writeUInt16LE(1, 2);
  directory.writeUInt16LE(sizes.length, 4);
  let offset = directory.length;
  sizes.forEach((size, index) => {
    const entry = 6 + 16 * index;
    directory[entry] = size;
    directory[entry + 1] = size;
    directory.writeUInt16LE(1, entry + 4);
    directory.writeUInt16LE(32, entry + 6);
    directory.writeUInt32LE(payloads[index].length, entry + 8);
    directory.writeUInt32LE(offset, entry + 12);
    offset += payloads[index].length;
  });
  await writeFile(path.join(target, 'favicon.ico'), Buffer.concat([directory, ...payloads]));
  console.log('Generated miy app icons and favicon from brand-icon.svg.');
} finally {
  await browser.close();
}
