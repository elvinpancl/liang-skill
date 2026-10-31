#!/usr/bin/env node

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const checkInstalled = process.argv.includes("--installed");
const errors = [];

const skillDirs = fs
  .readdirSync(path.join(repoRoot, "skills"), { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => path.join(repoRoot, "skills", entry.name))
  .filter((dir) => fs.existsSync(path.join(dir, "SKILL.md")))
  .sort();

const allowedFrontmatterKeys = new Set([
  "name",
  "description",
  "license",
  "allowed-tools",
  "metadata",
  "argument-hint",
]);
const names = new Set();
for (const dir of skillDirs) {
  const file = path.join(dir, "SKILL.md");
  const text = fs.readFileSync(file, "utf8");
  const frontmatter = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!frontmatter) {
    errors.push(`missing frontmatter: ${file}`);
    continue;
  }
  const frontmatterLines = frontmatter[1].split(/\r?\n/);
  const keys = frontmatterLines
    .map((line) => line.match(/^([a-zA-Z0-9-]+):/)?.[1])
    .filter(Boolean);
  for (const key of keys) {
    if (!allowedFrontmatterKeys.has(key)) {
      errors.push(`unsupported frontmatter key: ${file}:${key}`);
    }
  }

  const name = frontmatter[1].match(/^name:\s*(.+?)\s*$/m)?.[1]?.replace(/^["']|["']$/g, "");
  const descriptionLine = frontmatterLines.findIndex((line) => line.startsWith("description:"));
  let description;
  if (descriptionLine >= 0) {
    const inline = frontmatterLines[descriptionLine].replace(/^description:\s*/, "");
    if (inline === "|" || inline === ">") {
      const block = [];
      for (const line of frontmatterLines.slice(descriptionLine + 1)) {
        if (!/^\s+/.test(line)) break;
        block.push(line.trim());
      }
      description = block.join(" ");
    } else {
      description = inline.replace(/^["']|["']$/g, "");
    }
  }
  if (!name) errors.push(`missing name: ${file}`);
  if (!description) errors.push(`missing description: ${file}`);
  if (name !== path.basename(dir)) {
    errors.push(`name/folder mismatch: ${file}: ${name}`);
  }
  if (name && !/^[a-z0-9-]+$/.test(name)) {
    errors.push(`invalid skill name: ${file}:${name}`);
  }
  if (name && (name.startsWith("-") || name.endsWith("-") || name.includes("--"))) {
    errors.push(`invalid hyphen placement: ${file}:${name}`);
  }
  if (name && name.length > 64) {
    errors.push(`skill name too long: ${file}:${name.length}`);
  }
  if (description?.includes("<") || description?.includes(">")) {
    errors.push(`description contains angle brackets: ${file}`);
  }
  if (description && description.length > 1024) {
    errors.push(`description too long: ${file}:${description.length}`);
  }
  if (names.has(name)) errors.push(`duplicate skill name: ${name}`);
  names.add(name);
}

const required = [
  "skills/liang-content/references/blind-prediction-protocol.md",
  "skills/liang-content/assets/starter-rubrics/process-demo-zero.md",
  "skills/liang-content/hooks/prediction-immutability.sh",
  "skills/liang-content/LICENSE-MIT.txt",
  "skills/liang-content/adapters/perf-data/douyin-session/run.sh",
  "skills/liang-content/adapters/perf-data/xhs-explore/run.sh",
  "skills/liang-content/adapters/perf-data/linkedin-session/run.sh",
  "skills/liang-content/adapters/perf-data/bilibili-stat/run.sh",
  "skills/liang-content/adapters/script-extraction/whisper/run.sh",
  "skills/liang-content/references/resonance-framework.md",
  "skills/liang-content-logic/agents/openai.yaml",
  "skills/liang-resonate/agents/openai.yaml",
  "skills/liang-spread/agents/openai.yaml",
  "skills/liang-playbook/判别规则表_脱敏版.md",
  "skills/liang-playbook/取料栈_脱敏版.md",
  "skills/liang-playbook/提问模板_脱敏版.md",
  "skills/liang-playbook/校验闸门_脱敏版.md",
  "skills/liang-promo-plan/references/录屏清单模板.md",
  "skills/liang-promo-footage/references/实录对照模板.md",
  "skills/liang-promo-footage/scripts/extract_frames.py",
  "skills/liang-promo-footage/scripts/ocr.js",
  "skills/liang-promo-footage/scripts/ocr_frames.py",
  "skills/liang-promo-footage/scripts/novel_lines.py",
  "skills/liang-promo-footage/scripts/export_stills.py",
  "skills/liang-promo-footage/scripts/scan_sensitive.py",
  "skills/liang-promo-footage/scripts/selftest.sh",
  "skills/liang-promo-article/references/文章骨架.md",
  "skills/liang-promo-article/scripts/check_article.py",
  "skills/liang-promo-article/scripts/check_article_test.sh",
  "skills/liang-promo-edit/references/剪辑台本模板.md",
  "skills/liang-promo-edit/references/旁白写法_脱敏版.md",
  "skills/liang-wechat-layout/references/样式规格.md",
  "skills/liang-wechat-layout/themes/default.json",
  "skills/liang-wechat-layout/scripts/render_wechat.py",
  "skills/liang-wechat-layout/scripts/selftest.sh",
  "skills/liang-wechat-layout/scripts/fixtures/样例稿.md",
  "skills/liang-promo-edit/references/包装规范_脱敏版.md",
  "skills/liang-promo-edit/references/发布前检查_脱敏版.md",
  "skills/liang-promo-edit/references/校准记录_脱敏版.md",
  "skills/liang-promo-edit/scripts/_common.py",
  "skills/liang-promo-edit/scripts/ocr_boxes.js",
  "skills/liang-promo-edit/scripts/index_clips.py",
  "skills/liang-promo-edit/scripts/build_roughcut.py",
  "skills/liang-promo-edit/scripts/make_subtitles.py",
  "skills/liang-promo-edit/scripts/render_slides.py",
  "skills/liang-promo-edit/scripts/qa_export.py",
  "skills/liang-promo-edit/scripts/retro_compare.py",
  "skills/liang-promo-edit/scripts/reverse_edl.py",
  "skills/liang-promo-edit/scripts/selftest.sh",
  "THIRD_PARTY_NOTICES.md",
  "LICENSES/XBUILDERLAB-CONTENT-MIT.txt",
];

for (const relative of required) {
  if (!fs.existsSync(path.join(repoRoot, relative))) {
    errors.push(`required file missing: ${relative}`);
  }
}

const contentGuard = fs.readFileSync(
  path.join(repoRoot, "skills/liang-content/hooks/prediction-immutability.sh"),
  "utf8",
);
if (!contentGuard.includes("exit 2")) {
  errors.push("content immutability hook has no blocking exit 2");
}
if (!contentGuard.includes("bets/")) {
  errors.push("content immutability hook does not target bets/");
}

const resonanceFramework = fs.readFileSync(
  path.join(repoRoot, "skills/liang-content/references/resonance-framework.md"),
  "utf8",
);
for (const marker of [
  "沉默的螺旋",
  "Noelle-Neumann",
  "使用与满足理论",
  "Katz",
  "框架理论",
  "Entman",
  "两级传播",
  "Lazarsfeld",
  "认知失调理论",
  "Festinger",
]) {
  if (!resonanceFramework.includes(marker)) {
    errors.push(`resonance framework missing authority marker: ${marker}`);
  }
}
for (const name of ["liang-resonate", "liang-spread"]) {
  const skillText = fs.readFileSync(
    path.join(repoRoot, "skills", name, "SKILL.md"),
    "utf8",
  );
  if (!skillText.includes("references/resonance-framework.md")) {
    errors.push(`${name} does not reference shared resonance framework`);
  }
}

const playbookSkill = fs.readFileSync(
  path.join(repoRoot, "skills/liang-playbook/SKILL.md"),
  "utf8",
);
for (const reference of ["判别规则表_脱敏版.md", "取料栈_脱敏版.md", "提问模板_脱敏版.md", "校验闸门_脱敏版.md"]) {
  if (!playbookSkill.includes(`](${reference})`)) {
    errors.push(`liang-playbook does not reference ${reference}`);
  }
}

const liangRouter = fs.readFileSync(
  path.join(repoRoot, "skills/liang/SKILL.md"),
  "utf8",
);
if (!liangRouter.includes("/liang-playbook")) {
  errors.push("liang router does not route to /liang-playbook");
}
for (const name of ["liang-promo-plan", "liang-promo-footage", "liang-promo-edit", "liang-promo-article", "liang-wechat-layout"]) {
  if (!liangRouter.includes(`/${name}`)) {
    errors.push(`liang router does not route to /${name}`);
  }
}

const legacyNames = [
  "cheat-on-content",
  "cheat-on-money",
  "cheat-on-skill",
  "cheat-bump",
  "cheat-init",
  "cheat-learn-from",
  "cheat-migrate",
  "cheat-persona",
  "cheat-predict",
  "cheat-publish",
  "cheat-recommend",
  "cheat-retro",
  "cheat-score",
  "cheat-score-blind",
  "cheat-seed",
  "cheat-shoot",
  "cheat-status",
  "cheat-trends",
  "liang-money",
  "liang-money-intake",
  "liang-money-scout",
  "liang-money-vet",
  "liang-money-pledge",
  "liang-money-settle",
  "liang-career",
  "liang-career-intake",
  "liang-career-scan",
  "liang-career-plan",
  "liang-career-coach",
];

if (checkInstalled) {
  const roots = [
    path.join(os.homedir(), ".claude", "skills"),
    path.join(os.homedir(), ".codex", "skills"),
  ];

  for (const root of roots) {
    for (const dir of skillDirs) {
      const name = path.basename(dir);
      const link = path.join(root, name);
      if (!fs.existsSync(path.join(link, "SKILL.md"))) {
        errors.push(`installed skill missing: ${link}`);
      }
    }
    for (const name of legacyNames) {
      const legacy = path.join(root, name);
      let isSymbolicLink = false;
      try {
        isSymbolicLink = fs.lstatSync(legacy).isSymbolicLink();
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      if (fs.existsSync(legacy) || isSymbolicLink) {
        errors.push(`legacy skill still live: ${legacy}`);
      }
    }

    for (const registryName of ["skills-source-index.json", "skills-lock.json"]) {
      const registryPath = path.join(root, registryName);
      const registry = JSON.parse(fs.readFileSync(registryPath, "utf8"));
      for (const name of legacyNames) {
        if (Object.hasOwn(registry.skills ?? {}, name)) {
          errors.push(`legacy registry entry: ${registryPath}:${name}`);
        }
      }
      for (const name of ["cheat-on-content", "cheat-on-money", "cheat-on-skill"]) {
        if (Object.hasOwn(registry.sources ?? {}, name)) {
          errors.push(`legacy source registry entry: ${registryPath}:${name}`);
        }
      }
      for (const dir of skillDirs) {
        const name = path.basename(dir);
        if (!Object.hasOwn(registry.skills ?? {}, name)) {
          errors.push(`missing registry entry: ${registryPath}:${name}`);
        }
      }
    }
  }
}

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log(
  JSON.stringify({
    ok: true,
    skills: skillDirs.length,
    installedChecked: checkInstalled,
  }),
);
