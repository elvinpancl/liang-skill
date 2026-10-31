#!/usr/bin/env node

import {
  existsSync,
  readFileSync,
  statSync,
} from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const SCHEMA_VERSION = 1;
const MIN_DUPLICATE_CODE_POINTS = 20;

const FILE_CONTRACT = [
  { name: "00_分级与源清单.md", required: true },
  { name: "01_取料记录.md", required: true },
  { name: "02_草案_v1.md", required: true },
  { name: "03_采集清单.md", required: true },
  { name: "04_成卡_v1.md", required: false, conditional: "industry_card_status=READY" },
  { name: "05_源出处表.md", required: true },
  { name: "06_校验报告.md", required: true },
  { name: "07_商户执行前核验清单.md", required: true },
];

const REQUIRED_METADATA = {
  evidence_schema: "v3.1-layered",
  legacy_policy: "forward-only-touch-to-migrate",
};

const METADATA_FILES = [
  "00_分级与源清单.md",
  "05_源出处表.md",
  "06_校验报告.md",
];

const SOURCE_HEADER = [
  "模块",
  "结论要点",
  "用途",
  "等级",
  "源编号／主体",
  "路径／链接",
  "章节／时间点",
  "适用边界",
  "数字属性",
];

const ALLOWED_PURPOSES = new Set([
  "行业判断",
  "操作依据",
  "框架规则",
  "执行建议",
  "案例背景",
  "失效边界",
]);

const DIRECT_LEVELS = new Set(["L1-A", "L1-B", "L1-C", "L1-D", "L2"]);
const ALLOWED_LEVELS = new Set([...DIRECT_LEVELS, "L3", "U", "W", "R"]);

const MERCHANT_CHECKLIST_IDS = [
  "M01_ENTRY_PERMISSION",
  "M02_RESPONSE_OWNERSHIP",
  "M03_CAPACITY_BOTTLENECK",
  "M04_BASELINE_ATTRIBUTION",
  "M05_STOP_RESUME_AUTHORITY",
];

const CARD_HEADINGS = [
  "#### 1. 这门生意现在怎么打",
  "#### 2. 用户分析",
  "#### 3. 客户为什么会买",
  "#### 4. 不同情况分别做什么内容",
  "#### 5. 直接拍什么、怎么拍",
  "#### 6. 流量来了怎么接",
  "#### 7. 第一轮怎么验证",
];

const NUMBER_ATTRIBUTE_RE = /\[数字属性：(明确动作数据|案例背景数据|未经核验的转述数据|执行建议值|不采用数据)\]/u;
const ASCII_DIGIT_RE = /[0-9]/u;
const FULLWIDTH_DIGIT_RE = /[０１２３４５６７８９]/u;
const ASCII_ALPHANUMERIC_ENTITY_RE = /\b(?:B2B|B2C|C2B|C2C|O2O|P2P|G2B|G2C|C2M|2D|3D|4K|5G)\b/gu;

const PLACEHOLDER_RULES = [
  { token: "[缺口", re: /\[缺口/u },
  { token: "[待", re: /\[待/u },
  { token: "本卡尚未", re: /本卡尚未/u },
  { token: "尚未列出", re: /尚未列出/u },
  { token: "本卡未给出", re: /本卡未给出/u },
  { token: "本卡未确认", re: /本卡未确认/u },
  { token: "补齐前不放量", re: /补齐前不放量/u },
  { token: "未选前本卡不可执行", re: /未选前本卡不可执行/u },
  { token: "这张卡先按模块 1", re: /这张卡先按模块 1/u },
  { token: "首轮只验证这笔交易，优先拍", re: /首轮只验证这笔交易，优先拍/u },
  { token: "负责人／时限／容量", re: /负责人／时限／容量/u },
  { token: "预算／截止／最大损失", re: /预算／截止／最大损失/u },
  { token: "TODO／TBD／FIXME", re: /\b(?:TODO|TBD|FIXME|TBC)\b/iu },
  { token: "尖括号待填占位", re: /<[^>]*(?:待填|待确认|待核验|待补|TODO|TBD|FIXME)[^>]*>/iu },
  { token: "结构化字段待填", re: /(?:责任人|入口|容量|证据|当前值|证据路径|核验日期|响应时限|预算|阈值|归因窗口|比例|核验主体|账号|权限)\s*[：:]\s*(?:待确认|待核验|待填写|待填|待补(?:充)?|待定|TODO|TBD|FIXME|TBC|_{2,})/iu },
];

function diagnostic(code, file, line, message, details = undefined) {
  const item = { code, file, line, message };
  if (details !== undefined) item.details = details;
  return item;
}

function linesOf(text) {
  return text.split(/\r?\n/u);
}

export function codePointLength(value) {
  return Array.from(value).length;
}

function stripInlineMarkdown(value) {
  return value
    .trim()
    .replace(/^`+|`+$/gu, "")
    .replace(/\*\*|__|~~/gu, "")
    .trim();
}

export function normalizeSubstantiveLine(rawLine) {
  let line = rawLine.normalize("NFC").trim();
  if (!line || /^#{1,6}(?:\s|$)/u.test(line) || /^(?:`{3,}|~{3,})/u.test(line)) {
    return null;
  }

  line = line
    .replace(/^(?:>\s*)+/u, "")
    .replace(/^[-*+]\s+/u, "")
    .replace(/^(?:\(?[0-9]+[.)、．）]|[（(][0-9]+[）)])\s*/u, "")
    .replace(/\*\*|__|~~|`/gu, "")
    .replace(/\s+/gu, " ")
    .trim();

  if (/^[\p{P}\p{S}\s]+$/u.test(line)) return null;
  return line || null;
}

function classifiedMarkdownLines(text) {
  const output = [];
  let fence = null;
  for (const [index, raw] of linesOf(text).entries()) {
    const markerMatch = raw.match(/^ {0,3}(`{3,}|~{3,})(.*)$/u);
    if (markerMatch !== null) {
      const marker = markerMatch[1];
      const markerChar = marker[0];
      const remainder = markerMatch[2];
      if (fence === null) {
        fence = { char: markerChar, length: marker.length };
        output.push({ line: index + 1, raw, in_fence: true, fence_marker: true });
        continue;
      }
      const closesFence = markerChar === fence.char
        && marker.length >= fence.length
        && remainder.trim() === "";
      if (closesFence) {
        fence = null;
        output.push({ line: index + 1, raw, in_fence: true, fence_marker: true });
        continue;
      }
    }
    output.push({ line: index + 1, raw, in_fence: fence !== null, fence_marker: false });
  }
  return output;
}

function markdownLinesOutsideFences(text) {
  return classifiedMarkdownLines(text).filter((entry) => !entry.in_fence && !entry.fence_marker);
}

function markdownContentLines(text) {
  return classifiedMarkdownLines(text).filter((entry) => !entry.fence_marker);
}

function tableStructuralLineNumbers(text) {
  const lines = linesOf(text);
  const structural = new Set();
  for (let index = 0; index < lines.length; index += 1) {
    const cells = splitMarkdownRow(lines[index]);
    if (!cells) continue;
    if (cells.every(isSeparatorCell)) {
      structural.add(index + 1);
      if (index > 0 && splitMarkdownRow(lines[index - 1])) structural.add(index);
    }
  }
  return structural;
}

function tableSerialColumnsByLine(text) {
  const lines = linesOf(text);
  const result = new Map();
  const serialHeader = /^(?:序号|编号|模块|步骤|项次|no\.?|number)$/iu;
  for (let separatorIndex = 1; separatorIndex < lines.length; separatorIndex += 1) {
    const headerCells = splitMarkdownRow(lines[separatorIndex - 1]);
    const separatorCells = splitMarkdownRow(lines[separatorIndex]);
    if (!headerCells || !separatorCells || headerCells.length !== separatorCells.length || !separatorCells.every(isSeparatorCell)) {
      continue;
    }
    const serialColumns = new Set();
    for (const [column, header] of headerCells.entries()) {
      if (serialHeader.test(stripInlineMarkdown(header))) serialColumns.add(column);
    }
    if (serialColumns.size === 0) continue;
    for (let rowIndex = separatorIndex + 1; rowIndex < lines.length; rowIndex += 1) {
      const cells = splitMarkdownRow(lines[rowIndex]);
      if (!cells || cells.length !== headerCells.length) break;
      result.set(rowIndex + 1, serialColumns);
    }
  }
  return result;
}

function inspectDuplicateLines(text, file, errors) {
  const groups = new Map();
  const structuralLines = tableStructuralLineNumbers(text);
  for (const entry of markdownContentLines(text)) {
    if (structuralLines.has(entry.line)) continue;
    const normalized = normalizeSubstantiveLine(entry.raw);
    if (!normalized || codePointLength(normalized) < MIN_DUPLICATE_CODE_POINTS) continue;
    const occurrences = groups.get(normalized) ?? [];
    occurrences.push({ file, line: entry.line, text: entry.raw.trim() });
    groups.set(normalized, occurrences);
  }

  const duplicates = [];
  for (const [normalized, occurrences] of groups) {
    if (occurrences.length < 2) continue;
    duplicates.push({
      normalized,
      code_points: codePointLength(normalized),
      occurrences,
    });
    for (const occurrence of occurrences.slice(1)) {
      errors.push(diagnostic(
        "DUPLICATE_SUBSTANTIVE_LINE",
        occurrence.file,
        occurrence.line,
        "规范化后与同文件中的实质行重复。",
        { first_line: occurrences[0].line, normalized },
      ));
    }
  }

  return {
    ok: duplicates.length === 0,
    minimum_code_points: MIN_DUPLICATE_CODE_POINTS,
    measurement: "Array.from(normalized_line).length",
    items: duplicates,
  };
}

function stripStructuralNumbering(rawLine) {
  return rawLine
    .trim()
    .replace(/^[-*+]\s+/u, "")
    .replace(/^(?:\(?[0-9]+[.)、．）]|[（(][0-9]+[）)])\s*/u, "")
    .trim();
}

function inspectDigits(text, file, errors) {
  const fullwidthFormatErrors = [];
  const halfwidthUnattributed = [];
  const structuralLines = tableStructuralLineNumbers(text);
  const serialColumns = tableSerialColumnsByLine(text);

  for (const entry of markdownContentLines(text)) {
    if (structuralLines.has(entry.line)) continue;
    const trimmed = entry.raw.trim();
    if (!trimmed || /^#{1,6}(?:\s|$)/u.test(trimmed)) continue;

    const tableCells = splitMarkdownRow(trimmed);
    const digitText = tableCells
      ? tableCells.filter((cell, index) => {
        const isSerialColumn = serialColumns.get(entry.line)?.has(index) === true;
        const isPureSerial = /^[0-9０-９]+$/u.test(stripInlineMarkdown(cell));
        return !(isSerialColumn && isPureSerial);
      }).join(" | ")
      : stripStructuralNumbering(trimmed);

    if (FULLWIDTH_DIGIT_RE.test(digitText)) {
      const item = { file, line: entry.line, text: entry.raw.trim() };
      fullwidthFormatErrors.push(item);
      errors.push(diagnostic(
        "FULLWIDTH_DIGIT_FORMAT_ERROR",
        file,
        entry.line,
        "检测到全角数字；项目数字格式只允许半角数字。",
      ));
    }

    const quantityCandidate = digitText.replace(ASCII_ALPHANUMERIC_ENTITY_RE, "");
    if (ASCII_DIGIT_RE.test(quantityCandidate) && !NUMBER_ATTRIBUTE_RE.test(entry.raw)) {
      const item = { file, line: entry.line, text: trimmed };
      halfwidthUnattributed.push(item);
      errors.push(diagnostic(
        "HALFWIDTH_DIGIT_ATTRIBUTE_MISSING",
        file,
        entry.line,
        "正文半角数字缺少允许的数字属性标签。",
      ));
    }
  }

  return {
    ok: fullwidthFormatErrors.length === 0 && halfwidthUnattributed.length === 0,
    fullwidth_format_errors: fullwidthFormatErrors,
    halfwidth_unattributed: halfwidthUnattributed,
    allowed_attributes: [
      "明确动作数据",
      "案例背景数据",
      "未经核验的转述数据",
      "执行建议值",
      "不采用数据",
    ],
  };
}

export function splitMarkdownRow(line) {
  const trimmed = line.trim();
  if (!trimmed.startsWith("|")) return null;

  const cells = [];
  let cell = "";
  let escaped = false;
  let inCode = false;
  const end = trimmed.endsWith("|") ? trimmed.length - 1 : trimmed.length;

  for (let index = 1; index < end; index += 1) {
    const char = trimmed[index];
    if (escaped) {
      cell += char;
      escaped = false;
      continue;
    }
    if (char === "\\") {
      escaped = true;
      cell += char;
      continue;
    }
    if (char === "`") {
      inCode = !inCode;
      cell += char;
      continue;
    }
    if (char === "|" && !inCode) {
      cells.push(cell.trim());
      cell = "";
      continue;
    }
    cell += char;
  }
  cells.push(cell.trim());
  return cells;
}

function isSeparatorCell(value) {
  return /^:?-{3,}:?$/u.test(value.replace(/\s+/gu, ""));
}

function parseLevels(raw) {
  const cleaned = stripInlineMarkdown(raw);
  const levels = cleaned.split(/[／/+＋、,，\s]+/u).filter(Boolean);
  const invalid = levels.filter((level) => !ALLOWED_LEVELS.has(level));
  return { levels, invalid };
}

function sourceRoles(levels, purpose) {
  const roles = [];
  if (levels.some((level) => level.startsWith("L1-"))) roles.push("L1");
  if (levels.includes("L2")) roles.push("L2");
  if (purpose === "框架规则") roles.push("F");
  if (purpose === "执行建议") roles.push("E");
  return roles;
}

export function parseSourceTable(text, file, errors = []) {
  const lines = linesOf(text);
  const outsideLineNumbers = new Set(markdownLinesOutsideFences(text).map((entry) => entry.line));
  let headerIndex = -1;
  let observedHeader = null;

  for (const [index, line] of lines.entries()) {
    if (!outsideLineNumbers.has(index + 1)) continue;
    const cells = splitMarkdownRow(line);
    if (!cells) continue;
    const normalized = cells.map(stripInlineMarkdown);
    if (normalized[0] === "模块" && normalized[1] === "结论要点") {
      headerIndex = index;
      observedHeader = normalized;
      break;
    }
  }

  if (headerIndex < 0) {
    errors.push(diagnostic(
      "SOURCE_TABLE_HEADER_MISSING",
      file,
      null,
      "未找到以「模块｜结论要点」开头的源出处主表。",
    ));
    return {
      ok: false,
      header: null,
      header_line: null,
      row_count: 0,
      rows: [],
      role_counts: { L1: 0, L2: 0, F: 0, E: 0 },
      module_coverage: [],
      all_modules_ready: false,
    };
  }

  const headerLine = headerIndex + 1;
  if (observedHeader.length !== SOURCE_HEADER.length || observedHeader.some((cell, index) => cell !== SOURCE_HEADER[index])) {
    errors.push(diagnostic(
      "SOURCE_TABLE_HEADER_INVALID",
      file,
      headerLine,
      "源出处主表必须使用固定 9 列表头。",
      { expected: SOURCE_HEADER, actual: observedHeader },
    ));
  }

  const separatorLine = headerIndex + 2;
  const separator = outsideLineNumbers.has(separatorLine)
    ? splitMarkdownRow(lines[headerIndex + 1] ?? "")
    : null;
  if (!separator || separator.length !== SOURCE_HEADER.length || !separator.every(isSeparatorCell)) {
    errors.push(diagnostic(
      "SOURCE_TABLE_SEPARATOR_INVALID",
      file,
      headerLine + 1,
      "9 列表头后必须紧跟 9 列 Markdown 分隔行。",
    ));
  }

  const rows = [];
  for (let index = headerIndex + 2; index < lines.length; index += 1) {
    if (!outsideLineNumbers.has(index + 1)) break;
    const raw = lines[index];
    if (!raw.trim() || !raw.trim().startsWith("|")) break;
    const cells = splitMarkdownRow(raw);
    if (!cells || cells.length !== SOURCE_HEADER.length) {
      errors.push(diagnostic(
        "SOURCE_TABLE_ROW_WIDTH_INVALID",
        file,
        index + 1,
        "源出处表数据行必须恰好包含 9 列。",
        { actual_columns: cells?.length ?? 0 },
      ));
      continue;
    }

    const [moduleRaw, conclusion, purposeRaw, levelRaw, source, path, location, boundary, numberAttribute] = cells.map(stripInlineMarkdown);
    const module = Number(moduleRaw);
    const purpose = purposeRaw;
    const parsedLevels = parseLevels(levelRaw);

    if (!Number.isInteger(module) || module < 1 || module > 7) {
      errors.push(diagnostic(
        "SOURCE_TABLE_MODULE_INVALID",
        file,
        index + 1,
        "模块列必须是 1 至 7 的整数。",
        { value: moduleRaw },
      ));
    }
    if (!ALLOWED_PURPOSES.has(purpose)) {
      errors.push(diagnostic(
        "SOURCE_TABLE_PURPOSE_INVALID",
        file,
        index + 1,
        "用途列不是允许的证据用途。",
        { value: purpose, allowed: [...ALLOWED_PURPOSES] },
      ));
    }
    if (parsedLevels.levels.length === 0 || parsedLevels.invalid.length > 0) {
      errors.push(diagnostic(
        "SOURCE_TABLE_LEVEL_INVALID",
        file,
        index + 1,
        "等级列只能包含 L1-A／B／C／D、L2、L3、U、W、R。",
        { value: levelRaw, invalid: parsedLevels.invalid },
      ));
    }

    const positioned = source !== "" && path !== "" && location !== "";
    if (!positioned) {
      errors.push(diagnostic(
        "SOURCE_TABLE_POSITION_MISSING",
        file,
        index + 1,
        "每条来源必须同时给出源编号／主体、路径／链接与章节／时间点。",
      ));
    }

    const direct = parsedLevels.levels.some((level) => DIRECT_LEVELS.has(level));
    rows.push({
      line: index + 1,
      module: Number.isInteger(module) ? module : null,
      conclusion,
      purpose,
      level: levelRaw,
      levels: parsedLevels.levels,
      roles: sourceRoles(parsedLevels.levels, purpose),
      source,
      path,
      location,
      boundary,
      number_attribute: numberAttribute,
      positioned,
      direct,
    });
  }

  const moduleCoverage = [];
  for (let module = 1; module <= 7; module += 1) {
    const moduleRows = rows.filter((row) => row.module === module && row.positioned);
    const pathARows = moduleRows.filter((row) => row.direct && ["行业判断", "操作依据"].includes(row.purpose));
    const frameworkRows = moduleRows.filter((row) => row.direct && row.purpose === "框架规则");
    const industryBoundaryRows = moduleRows.filter((row) => row.direct && ["行业判断", "失效边界"].includes(row.purpose));
    const pathA = pathARows.length > 0;
    const pathB = frameworkRows.length > 0 && industryBoundaryRows.length > 0;
    moduleCoverage.push({
      module,
      ready: pathA || pathB,
      path_a: pathA,
      path_b: pathB,
      path_a_lines: pathARows.map((row) => row.line),
      framework_lines: frameworkRows.map((row) => row.line),
      industry_boundary_lines: industryBoundaryRows.map((row) => row.line),
      execution_recommendation_lines: moduleRows.filter((row) => row.purpose === "执行建议").map((row) => row.line),
    });
  }

  const roleCounts = { L1: 0, L2: 0, F: 0, E: 0 };
  for (const row of rows) {
    for (const role of row.roles) roleCounts[role] += 1;
  }

  const parseErrors = errors.filter((error) => error.code.startsWith("SOURCE_TABLE_"));
  return {
    ok: parseErrors.length === 0,
    header: observedHeader,
    header_line: headerLine,
    row_count: rows.length,
    rows,
    role_counts: roleCounts,
    allowed_purposes: [...ALLOWED_PURPOSES],
    module_coverage: moduleCoverage,
    all_modules_ready: moduleCoverage.every((entry) => entry.ready),
  };
}

function readStatus(text, file, key, allowedValues, errors) {
  const occurrences = [];
  for (const entry of markdownLinesOutsideFences(text)) {
    const line = entry.raw;
    if (!line.includes(key)) continue;
    const tokens = line.match(/[A-Z][A-Z_]*/gu) ?? [];
    const values = tokens.filter((token) => allowedValues.includes(token));
    for (const value of values) occurrences.push({ value, line: entry.line });
  }

  const unique = [...new Set(occurrences.map((entry) => entry.value))];
  if (unique.length === 0) {
    const keyLine = markdownLinesOutsideFences(text).find((entry) => entry.raw.includes(key))?.line ?? null;
    errors.push(diagnostic(
      "STATUS_MISSING_OR_INVALID",
      file,
      keyLine,
      `${key} 必须明确写为 ${allowedValues.join(" 或 ")}。`,
    ));
    return { value: "UNKNOWN", line: keyLine };
  }
  if (unique.length > 1) {
    errors.push(diagnostic(
      "STATUS_CONFLICT",
      file,
      occurrences[0].line,
      `${key} 同时出现互相冲突的状态。`,
      { values: unique },
    ));
    return { value: "UNKNOWN", line: occurrences[0].line };
  }
  return { value: unique[0], line: occurrences[0].line };
}

function parseMetadataLine(line, key) {
  const normalized = line
    .trim()
    .replace(/^[-*+]\s+/u, "")
    .replace(/^`+|`+$/gu, "")
    .trim();
  const match = normalized.match(new RegExp(`^${key}:\\s*\`?([^\`\\s]+)\`?\\s*$`, "u"));
  return match?.[1] ?? null;
}

function inspectSchemaMetadata(contents, errors) {
  const files = {};
  for (const file of METADATA_FILES) {
    const text = contents.get(file);
    if (text === undefined) {
      files[file] = { ok: false, values: {} };
      continue;
    }
    const values = {};
    let fileOk = true;
    for (const [key, expected] of Object.entries(REQUIRED_METADATA)) {
      const matches = [];
      for (const entry of markdownLinesOutsideFences(text)) {
        const value = parseMetadataLine(entry.raw, key);
        if (value !== null) matches.push({ value, line: entry.line });
      }
      if (matches.length === 0) {
        fileOk = false;
        errors.push(diagnostic(
          "SCHEMA_METADATA_MISSING",
          file,
          null,
          `${key} 必须明确写为 ${expected}。`,
        ));
        values[key] = null;
        continue;
      }
      const unique = [...new Set(matches.map((entry) => entry.value))];
      values[key] = unique.length === 1 ? unique[0] : unique;
      if (unique.length !== 1 || unique[0] !== expected) {
        fileOk = false;
        errors.push(diagnostic(
          "SCHEMA_METADATA_INVALID",
          file,
          matches[0].line,
          `${key} 的值必须精确等于 ${expected}。`,
          { actual: unique },
        ));
      }
    }
    files[file] = { ok: fileOk, values };
  }
  return {
    ok: Object.values(files).every((entry) => entry.ok),
    required: REQUIRED_METADATA,
    files,
  };
}

function inspectCardStructure(text, file, errors) {
  const entries = markdownLinesOutsideFences(text);
  const headings = CARD_HEADINGS.map((heading) => {
    const lineNumbers = [];
    for (const entry of entries) {
      if (entry.raw.trim() === heading) lineNumbers.push(entry.line);
    }
    if (lineNumbers.length !== 1) {
      errors.push(diagnostic(
        "CARD_HEADING_COUNT_INVALID",
        file,
        lineNumbers[0] ?? null,
        `标题「${heading}」必须恰好出现 1 次。`,
        { count: lineNumbers.length },
      ));
    }
    return { heading, count: lineNumbers.length, lines: lineNumbers };
  });
  return { ok: headings.every((entry) => entry.count === 1), headings };
}

function inspectPlaceholders(text, file, blocking, errors) {
  const items = [];
  for (const [index, line] of linesOf(text).entries()) {
    const matches = PLACEHOLDER_RULES.filter((rule) => rule.re.test(line));
    if (matches.length === 0) continue;
    const item = {
      file,
      line: index + 1,
      token: matches[0].token,
      tokens: matches.map((rule) => rule.token),
      text: line.trim(),
    };
    items.push(item);
    if (blocking) {
      errors.push(diagnostic(
        "FINAL_CARD_PLACEHOLDER",
        file,
        index + 1,
        `正式卡仍含过程占位语「${matches[0].token}」。`,
        { matched_tokens: item.tokens },
      ));
    }
  }
  return { ok: !blocking || items.length === 0, blocking, items };
}

function inspectMerchantChecklist(text, file, reportStatus, errors) {
  const lines = linesOf(text);
  const outsideLineNumbers = new Set(markdownLinesOutsideFences(text).map((entry) => entry.line));
  const titleLines = [];
  const sectionLines = [];
  for (const [index, line] of lines.entries()) {
    if (!outsideLineNumbers.has(index + 1)) continue;
    if (line.trim() === "# 商户执行前核验清单") titleLines.push(index + 1);
    if (line.trim() === "## 核验项") sectionLines.push(index + 1);
  }

  if (titleLines.length !== 1) {
    errors.push(diagnostic(
      "MERCHANT_CHECKLIST_TITLE_INVALID",
      file,
      titleLines[0] ?? null,
      "07 文件必须且只能包含一个「# 商户执行前核验清单」标题。",
      { count: titleLines.length },
    ));
  }
  if (sectionLines.length !== 1) {
    errors.push(diagnostic(
      "MERCHANT_CHECKLIST_SECTION_INVALID",
      file,
      sectionLines[0] ?? null,
      "07 文件必须且只能包含一个「## 核验项」章节。",
      { count: sectionLines.length },
    ));
  }

  const localErrors = [];
  const status = readStatus(text, file, "merchant_readiness", ["NOT_CALIBRATED", "READY"], localErrors);
  errors.push(...localErrors);
  if (reportStatus.value !== "UNKNOWN" && status.value !== "UNKNOWN" && reportStatus.value !== status.value) {
    errors.push(diagnostic(
      "MERCHANT_STATUS_MISMATCH",
      file,
      status.line,
      "06 与 07 的 merchant_readiness 必须一致。",
      { report: reportStatus.value, checklist: status.value },
    ));
  }

  const checked = [];
  const unchecked = [];
  const itemsById = new Map();
  if (sectionLines.length > 0) {
    const start = sectionLines[0];
    for (let index = start; index < lines.length; index += 1) {
      if (!outsideLineNumbers.has(index + 1)) continue;
      const line = lines[index];
      if (index + 1 > start && /^##\s+/u.test(line)) break;
      const match = line.match(/^\s*-\s+\[([ xX])\]\s+(.+)$/u);
      if (!match) continue;
      const id = match[2].match(/\b(M[0-9]{2}_[A-Z_]+)\b/u)?.[1] ?? null;
      const item = { file, line: index + 1, id, text: match[2].trim() };
      if (match[1].toLowerCase() === "x") checked.push(item);
      else unchecked.push(item);
      if (id !== null) {
        const occurrences = itemsById.get(id) ?? [];
        occurrences.push(item);
        itemsById.set(id, occurrences);
      }
    }
  }

  if (checked.length + unchecked.length === 0) {
    errors.push(diagnostic(
      "MERCHANT_CHECKLIST_ITEMS_MISSING",
      file,
      sectionLines[0] ?? null,
      "「## 核验项」下至少需要一个 Markdown checkbox。",
    ));
  }

  const allItems = [...checked, ...unchecked];
  for (const item of allItems.filter((entry) => entry.id === null || !MERCHANT_CHECKLIST_IDS.includes(entry.id))) {
    errors.push(diagnostic(
      "MERCHANT_CHECKLIST_ITEM_ID_INVALID",
      file,
      item.line,
      "每个核验 checkbox 必须使用固定的 M01 至 M05 契约 ID。",
      { value: item.id, required_ids: MERCHANT_CHECKLIST_IDS },
    ));
  }
  for (const id of MERCHANT_CHECKLIST_IDS) {
    const occurrences = itemsById.get(id) ?? [];
    if (occurrences.length === 1) continue;
    errors.push(diagnostic(
      occurrences.length === 0 ? "MERCHANT_CHECKLIST_REQUIRED_ITEM_MISSING" : "MERCHANT_CHECKLIST_ITEM_DUPLICATED",
      file,
      occurrences[0]?.line ?? sectionLines[0] ?? null,
      `固定核验项 ${id} 必须且只能出现 1 次。`,
      { id, count: occurrences.length },
    ));
  }
  if (allItems.length !== MERCHANT_CHECKLIST_IDS.length) {
    errors.push(diagnostic(
      "MERCHANT_CHECKLIST_ITEM_COUNT_INVALID",
      file,
      sectionLines[0] ?? null,
      `核验清单必须恰好包含 ${MERCHANT_CHECKLIST_IDS.length} 个固定 checkbox。`,
      { actual: allItems.length, required: MERCHANT_CHECKLIST_IDS.length },
    ));
  }

  if (status.value === "READY" && unchecked.length > 0) {
    for (const item of unchecked) {
      errors.push(diagnostic(
        "MERCHANT_READY_WITH_UNCHECKED_ITEM",
        file,
        item.line,
        "merchant_readiness 为 READY 时不能保留未勾选核验项。",
      ));
    }
  }
  if (status.value === "NOT_CALIBRATED" && allItems.length > 0 && unchecked.length === 0) {
    errors.push(diagnostic(
      "MERCHANT_NOT_CALIBRATED_WITH_ALL_CHECKED",
      file,
      status.line,
      "5 个固定核验项已全部勾选时，merchant_readiness 必须写为 READY。",
    ));
  }

  return {
    ok: !errors.some((error) => error.file === file && error.code.startsWith("MERCHANT_")),
    status: status.value,
    status_line: status.line,
    title_lines: titleLines,
    section_lines: sectionLines,
    checked,
    unchecked,
    required_ids: MERCHANT_CHECKLIST_IDS,
    item_ids: allItems.map((item) => item.id),
  };
}

function readRunFiles(runDir, errors) {
  const contents = new Map();
  const files = {};
  for (const spec of FILE_CONTRACT) {
    const absolute = join(runDir, spec.name);
    const exists = existsSync(absolute);
    let regular = false;
    if (exists) {
      try {
        regular = statSync(absolute).isFile();
      } catch {
        regular = false;
      }
    }
    files[spec.name] = {
      required: spec.required,
      conditional: spec.conditional ?? null,
      exists,
      regular,
    };

    if (spec.required && !exists) {
      errors.push(diagnostic("FILE_MISSING", spec.name, null, "运行目录缺少必需文件。"));
      continue;
    }
    if (exists && !regular) {
      errors.push(diagnostic("FILE_NOT_REGULAR", spec.name, null, "契约路径必须是普通文件。"));
      continue;
    }
    if (regular) {
      try {
        contents.set(spec.name, readFileSync(absolute, "utf8"));
      } catch (error) {
        errors.push(diagnostic("FILE_READ_ERROR", spec.name, null, `无法读取文件：${error.message}`));
      }
    }
  }
  return { contents, files };
}

export function validateRun(inputDirectory) {
  const runDir = resolve(inputDirectory);
  const errors = [];
  const warnings = [];

  if (!existsSync(runDir)) {
    return {
      schema_version: SCHEMA_VERSION,
      ok: false,
      run_dir: runDir,
      environment: environmentReport(),
      industry_card_status: "UNKNOWN",
      merchant_readiness: "UNKNOWN",
      files: {},
      checks: {},
      errors: [diagnostic("RUN_DIRECTORY_MISSING", ".", null, "运行目录不存在。")],
      warnings,
    };
  }
  try {
    if (!statSync(runDir).isDirectory()) {
      return {
        schema_version: SCHEMA_VERSION,
        ok: false,
        run_dir: runDir,
        environment: environmentReport(),
        industry_card_status: "UNKNOWN",
        merchant_readiness: "UNKNOWN",
        files: {},
        checks: {},
        errors: [diagnostic("RUN_PATH_NOT_DIRECTORY", ".", null, "CLI 参数必须指向运行目录。")],
        warnings,
      };
    }
  } catch (error) {
    return {
      schema_version: SCHEMA_VERSION,
      ok: false,
      run_dir: runDir,
      environment: environmentReport(),
      industry_card_status: "UNKNOWN",
      merchant_readiness: "UNKNOWN",
      files: {},
      checks: {},
      errors: [diagnostic("RUN_DIRECTORY_STAT_ERROR", ".", null, error.message)],
      warnings,
    };
  }

  const { contents, files } = readRunFiles(runDir, errors);
  const reportText = contents.get("06_校验报告.md") ?? "";
  const industryStatus = readStatus(
    reportText,
    "06_校验报告.md",
    "industry_card_status",
    ["NOT_READY", "READY"],
    errors,
  );
  const merchantStatus = readStatus(
    reportText,
    "06_校验报告.md",
    "merchant_readiness",
    ["NOT_CALIBRATED", "READY"],
    errors,
  );

  const cardExists = files["04_成卡_v1.md"]?.regular === true;
  if (industryStatus.value === "READY" && !cardExists) {
    errors.push(diagnostic(
      "READY_CARD_MISSING",
      "04_成卡_v1.md",
      null,
      "industry_card_status 为 READY 时必须存在正式成卡。",
    ));
  }
  if (industryStatus.value === "NOT_READY" && cardExists) {
    errors.push(diagnostic(
      "NOT_READY_CARD_PRESENT",
      "04_成卡_v1.md",
      1,
      "industry_card_status 为 NOT_READY 时不应存在正式成卡。",
    ));
  }

  const metadata = inspectSchemaMetadata(contents, errors);
  const sourceTable = parseSourceTable(contents.get("05_源出处表.md") ?? "", "05_源出处表.md", errors);
  if (industryStatus.value === "READY") {
    for (const coverage of sourceTable.module_coverage) {
      if (coverage.ready) continue;
      errors.push(diagnostic(
        "INDUSTRY_MODULE_EVIDENCE_MISSING",
        "05_源出处表.md",
        sourceTable.header_line,
        `模块 ${coverage.module} 未满足 3A 路径 A 或路径 B。`,
        { module: coverage.module },
      ));
    }
  } else if (!sourceTable.all_modules_ready) {
    for (const coverage of sourceTable.module_coverage.filter((entry) => !entry.ready)) {
      warnings.push(diagnostic(
        "INDUSTRY_MODULE_NOT_READY",
        "05_源出处表.md",
        sourceTable.header_line,
        `模块 ${coverage.module} 尚未满足 3A；NOT_READY 运行允许保留该缺口。`,
      ));
    }
  }

  const checkFile = cardExists ? "04_成卡_v1.md" : "02_草案_v1.md";
  const checkText = contents.get(checkFile) ?? "";
  const duplicateLines = inspectDuplicateLines(checkText, checkFile, errors);
  const digits = inspectDigits(checkText, checkFile, errors);
  const cardStructure = inspectCardStructure(checkText, checkFile, errors);
  const placeholders = inspectPlaceholders(checkText, checkFile, cardExists, errors);

  let merchantChecklist = {
    ok: false,
    status: "UNKNOWN",
    status_line: null,
    title_lines: [],
    section_lines: [],
    checked: [],
    unchecked: [],
  };
  if (contents.has("07_商户执行前核验清单.md")) {
    merchantChecklist = inspectMerchantChecklist(
      contents.get("07_商户执行前核验清单.md"),
      "07_商户执行前核验清单.md",
      merchantStatus,
      errors,
    );
  }

  const fileContract = {
    ok: !errors.some((error) => ["FILE_MISSING", "FILE_NOT_REGULAR", "FILE_READ_ERROR", "READY_CARD_MISSING", "NOT_READY_CARD_PRESENT"].includes(error.code)),
    files,
  };

  const result = {
    schema_version: SCHEMA_VERSION,
    ok: errors.length === 0,
    run_dir: runDir,
    check_file: checkFile,
    environment: environmentReport(),
    industry_card_status: industryStatus.value,
    merchant_readiness: merchantStatus.value,
    files,
    checks: {
      file_contract: fileContract,
      schema_metadata: metadata,
      duplicate_lines: duplicateLines,
      digits,
      source_table: sourceTable,
      card_structure: cardStructure,
      placeholders,
      merchant_checklist: merchantChecklist,
      semantic_fact_recall: {
        evaluated: false,
        blocking: false,
        reason: "语义事实召回、unsupported claim 与来源是否真正支持结论必须由独立评审完成；本脚本不使用关键词正则冒充语义判断。",
      },
    },
    errors,
    warnings,
  };
  return result;
}

function environmentReport() {
  return {
    node: process.version,
    platform: process.platform,
    arch: process.arch,
    locale: {
      LANG: process.env.LANG ?? null,
      LC_ALL: process.env.LC_ALL ?? null,
      LC_CTYPE: process.env.LC_CTYPE ?? null,
      effective: process.env.LC_ALL ?? process.env.LC_CTYPE ?? process.env.LANG ?? null,
    },
  };
}

function invocationError(message) {
  return {
    schema_version: SCHEMA_VERSION,
    ok: false,
    run_dir: null,
    environment: environmentReport(),
    industry_card_status: "UNKNOWN",
    merchant_readiness: "UNKNOWN",
    files: {},
    checks: {},
    errors: [diagnostic("CLI_USAGE_ERROR", ".", null, message)],
    warnings: [],
  };
}

function main() {
  const args = process.argv.slice(2);
  if (args.length !== 1) {
    process.stdout.write(`${JSON.stringify(invocationError("用法：node check-run.mjs <运行目录>"), null, 2)}\n`);
    process.exitCode = 2;
    return;
  }

  try {
    const result = validateRun(args[0]);
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    process.exitCode = result.ok ? 0 : 1;
  } catch (error) {
    const result = invocationError(`校验器异常：${error.stack ?? error.message}`);
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    process.exitCode = 2;
  }
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) main();
