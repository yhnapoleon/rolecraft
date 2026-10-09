"""The real v4 test result renderer keeps modes and historical versions explicit."""

import subprocess
from pathlib import Path


def test_bilingual_test_result_modes_and_versions() -> None:
    root = Path(__file__).resolve().parents[3]
    script = r"""
import assert from 'node:assert/strict';
import { createServer } from 'vite';
const server = await createServer({
  server: { middlewareMode: true, hmr: false }, appType: 'custom',
});
try {
  const { testRunView } = await server.ssrLoadModule('/src/app/test-set-view.js');
  const { setPreference } = await server.ssrLoadModule('/src/app/i18n.ts');
  const modes = {
    extractive: ['原文抽取', 'Source extraction'], llm: ['模型生成', 'Model generation'],
    unavailable: ['未配置模型', 'Model not configured'], failed: ['失败', 'Failed'],
  };
  for (const [i, language] of ['zh', 'en'].entries()) {
    setPreference(language);
    for (const [mode, labels] of Object.entries(modes)) {
      const run = {
        id: 'saved-run', answer: 'Original answer', caseRevision: 1, configVersion: 2,
        policyVersion: 3, indexVersion: 1, mode,
        effectiveConfig: { update_strategy: 'daily', generator: 'llm' },
        citations: [{ id: 'policy', version: 1, title: 'Travel policy' }],
      };
      const before = JSON.stringify(run);
      const html = testRunView({run, runs: [run], item: {id: 'case', revision: 2},
        work: {adopted: true}, session: {testNotes: {}, world: {status: 'active'}}, md: (s) => s});
      assert.ok(html.includes(labels[i]), mode + ':' + language);
      assert.ok(html.includes('data-generation-mode="' + mode + '"'));
      assert.ok(html.includes('Travel policy v1'));
      assert.ok(html.includes('daily'));
      const configLabel = language === 'zh'
        ? '本次有效配置' : 'Effective configuration for this run';
      assert.ok(html.includes(configLabel));
      assert.equal(JSON.stringify(run), before);
    }
  }
} finally { await server.close(); }
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=root / "apps/web",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
