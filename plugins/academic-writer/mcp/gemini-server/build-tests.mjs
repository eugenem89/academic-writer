#!/usr/bin/env node
/**
 * build-tests.mjs — transpiles+bundles tests/*.test.ts (and their src/
 * imports, including the .md prompt template) into dist-test/*.test.mjs so
 * they can be run with plain `node --test`. Ported from the gemini_ocr
 * staging pass (a2-ocr-staging/build-tests.mjs); this repo has no other TS
 * test runner wired up yet.
 */
import { build } from 'esbuild';
import { readdirSync, mkdirSync } from 'node:fs';

mkdirSync('./dist-test', { recursive: true });

const testFiles = readdirSync('./tests').filter((f) => f.endsWith('.test.ts'));

await build({
  entryPoints: testFiles.map((f) => `./tests/${f}`),
  outdir: './dist-test',
  bundle: true,
  format: 'esm',
  platform: 'node',
  target: 'node20',
  sourcemap: 'inline',
  external: ['@modelcontextprotocol/sdk', '@google/genai'],
  loader: { '.md': 'text' },
});

console.log(`Built ${testFiles.length} test file(s) into dist-test/`);
