import assert from "node:assert/strict";
import { appendFileSync, cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { codePointLength, parseSourceTable, validateRun } from "../scripts/check-run.mjs";

const fixtureDirectory = fileURLToPath(new URL("./fixtures/ready-not-calibrated/", import.meta.url));
const checker = fileURLToPath(new URL("../scripts/check-run.mjs", import.meta.url));
const syntheticEvaluatorFixture = fileURLToPath(new URL("./evaluator/synthetic-regression.v1.json", import.meta.url));

function runCli(directory, environment = {}) {
  const result = spawnSync(process.execPath, [checker, directory], {
    encoding: "utf8",
    env: { ...process.env, ...environment },
  });
  assert.equal(result.stderr, "");
  return { ...result, json: JSON.parse(result.stdout) };
}

function copyFixture() {
  const directory = mkdtempSync(join(tmpdir(), "liang-playbook-check-run-"));
  cpSync(fixtureDirectory, directory, { recursive: true });
  return directory;
}

test("LC_ALL=C 时纯中文不被误判为数字，Unicode 长度按码点计算", () => {
  const result = runCli(fixtureDirectory, { LC_ALL: "C", LC_CTYPE: "C" });

  assert.equal(result.status, 0);
  assert.equal(result.json.ok, true);
  assert.equal(result.json.environment.locale.LC_ALL, "C");
  assert.deepEqual(result.json.checks.digits.fullwidth_format_errors, []);
  assert.deepEqual(result.json.checks.digits.halfwidth_unattributed, []);
  assert.equal(codePointLength("七个汉字测试啊"), 7);
  assert.equal(codePointLength("12345678901234567890"), 20);
});

test("全角数字只报告格式错误，不混入半角数字属性错误", () => {
  const directory = copyFixture();
  try {
    appendFileSync(
      join(directory, "04_成卡_v1.md"),
      "\n本行包含全角数字１，应当触发独立格式错误。\n",
      "utf8",
    );
    const result = runCli(directory, { LC_ALL: "C" });

    assert.equal(result.status, 1);
    assert.equal(result.json.ok, false);
    assert.equal(result.json.errors.filter((item) => item.code === "FULLWIDTH_DIGIT_FORMAT_ERROR").length, 1);
    assert.equal(result.json.errors.filter((item) => item.code === "HALFWIDTH_DIGIT_ATTRIBUTE_MISSING").length, 0);
    assert.equal(result.json.errors.find((item) => item.code === "FULLWIDTH_DIGIT_FORMAT_ERROR").file, "04_成卡_v1.md");
    assert.equal(typeof result.json.errors.find((item) => item.code === "FULLWIDTH_DIGIT_FORMAT_ERROR").line, "number");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("B2B／C2C／3D 等白名单实体不当作数量，单位和 Q1 仍要求数字属性", () => {
  const directory = copyFixture();
  try {
    appendFileSync(
      join(directory, "04_成卡_v1.md"),
      "\n本行业存在 B2B 与 C2C 交易，也会展示 3D 对象，这些实体编号不表示数量。\n首轮观察 7 天但没有数字属性。\n服务半径写成 5km 也必须标属性。\n周期写成 7days 也不能绕过。\n季度写成 Q1 仍属于时间属性。\n承诺 24H 内响应不能当成实体。\n首轮观察 7D 也属于周期。\n",
      "utf8",
    );
    const result = runCli(directory);
    const numberErrors = result.json.errors.filter((item) => item.code === "HALFWIDTH_DIGIT_ATTRIBUTE_MISSING");

    assert.equal(result.status, 1);
    assert.equal(numberErrors.length, 6);
    assert.match(numberErrors[0].message, /数字属性/u);
    assert.equal(result.json.checks.digits.halfwidth_unattributed[0].text.includes("7 天"), true);
    assert.equal(result.json.checks.digits.halfwidth_unattributed.some((item) => item.text.includes("5km")), true);
    assert.equal(result.json.checks.digits.halfwidth_unattributed.some((item) => item.text.includes("7days")), true);
    assert.equal(result.json.checks.digits.halfwidth_unattributed.some((item) => item.text.includes("Q1")), true);
    assert.equal(result.json.checks.digits.halfwidth_unattributed.some((item) => item.text.includes("24H")), true);
    assert.equal(result.json.checks.digits.halfwidth_unattributed.some((item) => item.text.includes("7D")), true);
    assert.equal(result.json.checks.digits.halfwidth_unattributed.some((item) => item.text.includes("B2B")), false);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("纯标点重复不进入实质整行检测", () => {
  const directory = copyFixture();
  try {
    appendFileSync(
      join(directory, "04_成卡_v1.md"),
      "\n！！！！！！！！！！！！！！！！！！！！\n！！！！！！！！！！！！！！！！！！！！\n",
      "utf8",
    );
    const result = runCli(directory);

    assert.equal(result.status, 0);
    assert.equal(result.json.checks.duplicate_lines.items.length, 0);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("9 列源表解析 L1、L2、F、E，并支持 3A 路径 B", () => {
  const result = validateRun(fixtureDirectory);
  const table = result.checks.source_table;
  const moduleOne = table.module_coverage.find((entry) => entry.module === 1);

  assert.equal(table.ok, true);
  assert.equal(table.header.length, 9);
  assert.equal(table.row_count, 9);
  assert.ok(table.role_counts.L1 > 0);
  assert.ok(table.role_counts.L2 > 0);
  assert.equal(table.role_counts.F, 1);
  assert.equal(table.role_counts.E, 1);
  assert.equal(moduleOne.path_a, false);
  assert.equal(moduleOne.path_b, true);
  assert.equal(moduleOne.ready, true);
});

test("低等级框架行不能参与 3A 路径 B", () => {
  const errors = [];
  const table = parseSourceTable(`
| 模块 | 结论要点 | 用途 | 等级 | 源编号／主体 | 路径／链接 | 章节／时间点 | 适用边界 | 数字属性 |
|---:|---|---|---|---|---|---|---|---|
| 1 | 通用结构 | 框架规则 | R | F001／研究者 | /fixture/research.md | 结构段 | 不能单独放行 | 不适用 |
| 1 | 行业边界 | 失效边界 | L1-A | I001／行业源 | /fixture/source.txt | 边界段 | 只适用于目标交易 | 不适用 |
`, "05_源出处表.md", errors);
  const moduleOne = table.module_coverage.find((entry) => entry.module === 1);

  assert.equal(moduleOne.path_b, false);
  assert.equal(moduleOne.ready, false);
});

test("代码围栏中的伪源表不能参与 3A", () => {
  const errors = [];
  const table = parseSourceTable(`
\`\`\`markdown
| 模块 | 结论要点 | 用途 | 等级 | 源编号／主体 | 路径／链接 | 章节／时间点 | 适用边界 | 数字属性 |
|---:|---|---|---|---|---|---|---|---|
| 1 | 围栏伪证据 | 行业判断 | L1-A | I001／伪源 | /fixture/fake.md | 伪章节 | 不得参与放行 | 不适用 |
\`\`\`
`, "05_源出处表.md", errors);

  assert.equal(table.row_count, 0);
  assert.equal(table.all_modules_ready, false);
  assert.equal(errors.some((item) => item.code === "SOURCE_TABLE_HEADER_MISSING"), true);
});

test("带尾随文字的围栏标记不是合法闭栏，后续伪源表仍被隔离", () => {
  const errors = [];
  const table = parseSourceTable(`
\`\`\`markdown
\`\`\`not-a-close
| 模块 | 结论要点 | 用途 | 等级 | 源编号／主体 | 路径／链接 | 章节／时间点 | 适用边界 | 数字属性 |
|---:|---|---|---|---|---|---|---|---|
| 1 | 围栏伪证据 | 行业判断 | L1-A | I001／伪源 | /fixture/fake.md | 伪章节 | 不得参与放行 | 不适用 |
\`\`\`
`, "05_源出处表.md", errors);

  assert.equal(table.row_count, 0);
  assert.equal(table.all_modules_ready, false);
  assert.equal(errors.some((item) => item.code === "SOURCE_TABLE_HEADER_MISSING"), true);
});

test("表格正文仍参与数字属性与重复整行检查", () => {
  const directory = copyFixture();
  try {
    appendFileSync(
      join(directory, "04_成卡_v1.md"),
      "\n| 类型 | 内容 |\n|---|---|\n| 测试 | 这条表格正文需要观察 7 天且故意重复用于回归检查 |\n| 测试 | 这条表格正文需要观察 7 天且故意重复用于回归检查 |\n",
      "utf8",
    );
    const result = runCli(directory);

    assert.equal(result.status, 1);
    assert.equal(result.json.errors.filter((item) => item.code === "HALFWIDTH_DIGIT_ATTRIBUTE_MISSING").length, 2);
    assert.equal(result.json.errors.filter((item) => item.code === "DUPLICATE_SUBSTANTIVE_LINE").length, 1);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("只排除显式序号列，表格首列的年份仍要求数字属性", () => {
  const directory = copyFixture();
  try {
    appendFileSync(
      join(directory, "04_成卡_v1.md"),
      "\n| 序号 | 动作 |\n|---:|---|\n| 1 | 该序号只表示结构顺序 |\n\n| 年份 | 事实 |\n|---:|---|\n| 2026 | 该年份没有数字属性 |\n",
      "utf8",
    );
    const result = runCli(directory);
    const numberErrors = result.json.errors.filter((item) => item.code === "HALFWIDTH_DIGIT_ATTRIBUTE_MISSING");

    assert.equal(result.status, 1);
    assert.equal(numberErrors.length, 1);
    assert.equal(numberErrors[0].line > 0, true);
    assert.equal(result.json.checks.digits.halfwidth_unattributed[0].text.includes("2026"), true);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("围栏内状态、标题和 checkbox 不参与结构契约", () => {
  const directory = copyFixture();
  try {
    appendFileSync(
      join(directory, "04_成卡_v1.md"),
      "\n\`\`\`markdown\n#### 1. 这门生意现在怎么打\n\`\`\`\n",
      "utf8",
    );
    appendFileSync(
      join(directory, "06_校验报告.md"),
      "\n\`\`\`text\nindustry_card_status: NOT_READY\nmerchant_readiness: READY\n\`\`\`\n",
      "utf8",
    );
    appendFileSync(
      join(directory, "07_商户执行前核验清单.md"),
      "\n\`\`\`markdown\n- [x] M99_FAKE_ITEM 围栏伪核验项\n\`\`\`\n",
      "utf8",
    );
    const result = runCli(directory);

    assert.equal(result.status, 0);
    assert.equal(result.json.industry_card_status, "READY");
    assert.equal(result.json.merchant_readiness, "NOT_CALIBRATED");
    assert.equal(result.json.checks.card_structure.ok, true);
    assert.equal(result.json.checks.merchant_checklist.item_ids.length, 5);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("正式卡中的结构化待填与 ASCII 占位必须失败", () => {
  const directory = copyFixture();
  try {
    appendFileSync(
      join(directory, "04_成卡_v1.md"),
      "\n入口：TODO\n责任人：待确认\n容量：TBD\n证据：<待填>\n",
      "utf8",
    );
    const result = runCli(directory);
    const placeholderLines = new Set(
      result.json.checks.placeholders.items.map((item) => item.text),
    );

    assert.equal(result.status, 1);
    assert.equal(placeholderLines.has("入口：TODO"), true);
    assert.equal(placeholderLines.has("责任人：待确认"), true);
    assert.equal(placeholderLines.has("容量：TBD"), true);
    assert.equal(placeholderLines.has("证据：<待填>"), true);
    assert.equal(result.json.errors.filter((item) => item.code === "FINAL_CARD_PLACEHOLDER").length, 4);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("NOT_CALIBRATED 不阻断 READY 行业卡", () => {
  const result = runCli(fixtureDirectory);

  assert.equal(result.status, 0);
  assert.equal(result.json.industry_card_status, "READY");
  assert.equal(result.json.merchant_readiness, "NOT_CALIBRATED");
  assert.equal(result.json.checks.merchant_checklist.unchecked.length, 5);
  assert.equal(result.json.errors.some((item) => item.code === "MERCHANT_READY_WITH_UNCHECKED_ITEM"), false);
  assert.equal(result.json.checks.semantic_fact_recall.evaluated, false);
});

test("商户清单缺固定项时不能用单个已勾选项伪装 READY", () => {
  const directory = copyFixture();
  try {
    const reportPath = join(directory, "06_校验报告.md");
    const checklistPath = join(directory, "07_商户执行前核验清单.md");
    writeFileSync(
      reportPath,
      readFileSync(reportPath, "utf8").replace("merchant_readiness）：NOT_CALIBRATED", "merchant_readiness）：READY"),
      "utf8",
    );
    writeFileSync(
      checklistPath,
      "# 商户执行前核验清单\n\n商户落地状态（merchant_readiness）：READY\n\n## 核验项\n\n- [x] 任意一项。\n",
      "utf8",
    );
    const result = runCli(directory);

    assert.equal(result.status, 1);
    assert.equal(result.json.errors.some((item) => item.code === "MERCHANT_CHECKLIST_REQUIRED_ITEM_MISSING"), true);
    assert.equal(result.json.errors.some((item) => item.code === "MERCHANT_CHECKLIST_ITEM_COUNT_INVALID"), true);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("5 项全勾选时 NOT_CALIBRATED 与 READY 双向一致", () => {
  const directory = copyFixture();
  try {
    const reportPath = join(directory, "06_校验报告.md");
    const checklistPath = join(directory, "07_商户执行前核验清单.md");
    writeFileSync(
      checklistPath,
      readFileSync(checklistPath, "utf8").replaceAll("- [ ]", "- [x]"),
      "utf8",
    );
    let result = runCli(directory);
    assert.equal(result.status, 1);
    assert.equal(result.json.errors.some((item) => item.code === "MERCHANT_NOT_CALIBRATED_WITH_ALL_CHECKED"), true);

    writeFileSync(
      reportPath,
      readFileSync(reportPath, "utf8").replace("merchant_readiness）：NOT_CALIBRATED", "merchant_readiness）：READY"),
      "utf8",
    );
    writeFileSync(
      checklistPath,
      readFileSync(checklistPath, "utf8").replace("merchant_readiness）：NOT_CALIBRATED", "merchant_readiness）：READY"),
      "utf8",
    );
    result = runCli(directory);
    assert.equal(result.status, 0);
    assert.equal(result.json.merchant_readiness, "READY");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("评估夹具为关键事实与整体内容提供独立分母", () => {
  const fixture = JSON.parse(readFileSync(syntheticEvaluatorFixture, "utf8"));
  const items = fixture.content_recall.items;
  const criticalItems = items.filter((item) => item.critical === true);

  assert.ok(criticalItems.length > 0);
  assert.ok(criticalItems.length < items.length);
  assert.equal(fixture.threshold.active_gate, false);
  assert.equal(fixture.threshold.critical_fact_candidate_target, 1);
  assert.equal(fixture.threshold.minimum_critical_fact_recall, null);
  assert.equal(fixture.threshold.minimum_overall_content_recall, null);
  assert.notEqual(
    fixture.content_recall.metric_definitions.critical_fact_recall,
    fixture.content_recall.metric_definitions.overall_content_recall,
  );
});
