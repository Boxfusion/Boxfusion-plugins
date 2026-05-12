# Word Template Generator

## Overview

This reference enables Claude to generate `.docx` Word document templates with **proper complex merge fields** (`w:fldChar` begin/separate/end) that are recognized by Microsoft Word and Aspose.Words mail merge. Templates are built from raw OOXML and packaged as ZIP archives.

**Important:** The `w:fldSimple` approach does NOT produce real merge fields. Always use the complex field character approach (`w:fldChar` with `begin`/`separate`/`end`) shown below.

## Prerequisites

The generator requires Node.js and the `archiver` npm package. Install temporarily:

```bash
npm install archiver --no-save
```

Clean up after generation:

```bash
rm -rf node_modules package-lock.json package.json
```

## OOXML Building Blocks

### SS1 — Merge Field XML (Complex Field Characters)

A proper Word merge field consists of five runs: begin, instruction, separate, display text, end.

```javascript
function mergeFieldXml(fieldName) {
  return `<w:r><w:fldChar w:fldCharType="begin"/></w:r>` +
    `<w:r><w:instrText xml:space="preserve"> MERGEFIELD ${fieldName} \\* MERGEFORMAT </w:instrText></w:r>` +
    `<w:r><w:fldChar w:fldCharType="separate"/></w:r>` +
    `<w:r><w:rPr><w:color w:val="808080"/></w:rPr><w:t>\u00AB${fieldName}\u00BB</w:t></w:r>` +
    `<w:r><w:fldChar w:fldCharType="end"/></w:r>`;
}
```

The display text uses `«FieldName»` (Unicode guillemets `\u00AB` and `\u00BB`) in grey, matching Word's default merge field display.

### SS2 — Region (TableStart/TableEnd) Merge Fields

Repeating regions use the same complex field character pattern but with `TableStart:` and `TableEnd:` prefixes in the instruction text.

```javascript
function regionStartXml(regionName) {
  return `<w:r><w:fldChar w:fldCharType="begin"/></w:r>` +
    `<w:r><w:instrText xml:space="preserve"> MERGEFIELD TableStart:${regionName} \\* MERGEFORMAT </w:instrText></w:r>` +
    `<w:r><w:fldChar w:fldCharType="separate"/></w:r>` +
    `<w:r><w:rPr><w:color w:val="808080"/></w:rPr><w:t>\u00ABTableStart:${regionName}\u00BB</w:t></w:r>` +
    `<w:r><w:fldChar w:fldCharType="end"/></w:r>`;
}

function regionEndXml(regionName) {
  return `<w:r><w:fldChar w:fldCharType="begin"/></w:r>` +
    `<w:r><w:instrText xml:space="preserve"> MERGEFIELD TableEnd:${regionName} \\* MERGEFORMAT </w:instrText></w:r>` +
    `<w:r><w:fldChar w:fldCharType="separate"/></w:r>` +
    `<w:r><w:rPr><w:color w:val="808080"/></w:rPr><w:t>\u00ABTableEnd:${regionName}\u00BB</w:t></w:r>` +
    `<w:r><w:fldChar w:fldCharType="end"/></w:r>`;
}
```

### SS3 — Text Run and Paragraph Helpers

```javascript
function textRun(text, bold = false, opts = {}) {
  let rPr = "";
  const parts = [];
  if (bold) parts.push("<w:b/>");
  if (opts.italic) parts.push("<w:i/>");
  if (opts.size) parts.push(`<w:sz w:val="${opts.size}"/><w:szCs w:val="${opts.size}"/>`);
  if (opts.color) parts.push(`<w:color w:val="${opts.color}"/>`);
  if (parts.length) rPr = `<w:rPr>${parts.join("")}</w:rPr>`;
  return `<w:r>${rPr}<w:t xml:space="preserve">${escapeXml(text)}</w:t></w:r>`;
}

function escapeXml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

function paragraph(children, { heading, alignment, spacingBefore, spacingAfter } = {}) {
  let pPr = "<w:pPr>";
  if (heading) pPr += `<w:pStyle w:val="${heading}"/>`;
  if (alignment) pPr += `<w:jc w:val="${alignment}"/>`;
  const before = spacingBefore ? ` w:before="${spacingBefore}"` : "";
  const after = spacingAfter ? ` w:after="${spacingAfter}"` : "";
  if (before || after) pPr += `<w:spacing${before}${after}/>`;
  pPr += "</w:pPr>";
  return `<w:p>${pPr}${children}</w:p>`;
}

// Shortcut: label text followed by a merge field
function labelAndField(label, fieldName, opts = {}) {
  return paragraph(textRun(label) + mergeFieldXml(fieldName), { spacingAfter: "100", ...opts });
}
```

### SS4 — Table XML (for Repeating Regions Inside Word Tables)

When a repeating region should render as table rows, wrap the region inside a Word table structure. The `TableStart` and `TableEnd` merge fields go in the first and last data rows.

```javascript
function tableWithRegion(regionName, columns, { headerBold = true, borderColor = "000000" } = {}) {
  // columns: [{ label: "Name", field: "Name", width: 3000 }, ...]
  const totalWidth = columns.reduce((sum, c) => sum + (c.width || 2400), 0);

  const cellBorders = `<w:tcBorders>` +
    `<w:top w:val="single" w:sz="4" w:space="0" w:color="${borderColor}"/>` +
    `<w:bottom w:val="single" w:sz="4" w:space="0" w:color="${borderColor}"/>` +
    `<w:left w:val="single" w:sz="4" w:space="0" w:color="${borderColor}"/>` +
    `<w:right w:val="single" w:sz="4" w:space="0" w:color="${borderColor}"/>` +
    `</w:tcBorders>`;

  // Header row
  const headerCells = columns.map(c => {
    const w = c.width || 2400;
    return `<w:tc><w:tcPr><w:tcW w:w="${w}" w:type="dxa"/>${cellBorders}</w:tcPr>` +
      `<w:p><w:pPr><w:jc w:val="center"/></w:pPr>${textRun(c.label, headerBold)}</w:p></w:tc>`;
  }).join("");
  const headerRow = `<w:tr><w:trPr><w:tblHeader/></w:trPr>${headerCells}</w:tr>`;

  // Data row (repeated by mail merge) — contains TableStart in first cell, fields in each cell, TableEnd in last cell
  // Approach: Put TableStart/TableEnd as separate rows around the data row
  const startRow = `<w:tr>${columns.map((c, i) => {
    const w = c.width || 2400;
    const content = i === 0 ? regionStartXml(regionName) : "";
    return `<w:tc><w:tcPr><w:tcW w:w="${w}" w:type="dxa"/>${cellBorders}</w:tcPr><w:p>${content}</w:p></w:tc>`;
  }).join("")}</w:tr>`;

  const dataCells = columns.map(c => {
    const w = c.width || 2400;
    return `<w:tc><w:tcPr><w:tcW w:w="${w}" w:type="dxa"/>${cellBorders}</w:tcPr>` +
      `<w:p>${mergeFieldXml(c.field)}</w:p></w:tc>`;
  }).join("");
  const dataRow = `<w:tr>${dataCells}</w:tr>`;

  const endRow = `<w:tr>${columns.map((c, i) => {
    const w = c.width || 2400;
    const content = i === 0 ? regionEndXml(regionName) : "";
    return `<w:tc><w:tcPr><w:tcW w:w="${w}" w:type="dxa"/>${cellBorders}</w:tcPr><w:p>${content}</w:p></w:tc>`;
  }).join("")}</w:tr>`;

  return `<w:tbl>` +
    `<w:tblPr><w:tblW w:w="${totalWidth}" w:type="dxa"/>` +
    `<w:tblBorders>` +
    `<w:top w:val="single" w:sz="4" w:space="0" w:color="${borderColor}"/>` +
    `<w:bottom w:val="single" w:sz="4" w:space="0" w:color="${borderColor}"/>` +
    `<w:left w:val="single" w:sz="4" w:space="0" w:color="${borderColor}"/>` +
    `<w:right w:val="single" w:sz="4" w:space="0" w:color="${borderColor}"/>` +
    `<w:insideH w:val="single" w:sz="4" w:space="0" w:color="${borderColor}"/>` +
    `<w:insideV w:val="single" w:sz="4" w:space="0" w:color="${borderColor}"/>` +
    `</w:tblBorders></w:tblPr>` +
    headerRow + startRow + dataRow + endRow +
    `</w:tbl>`;
}
```

**Repeating table convention:** The `TableStart:RegionName` and `TableEnd:RegionName` merge fields are placed in their own rows within the Word table. The row between them containing the data merge fields is the one that repeats for each item. Aspose removes the start/end marker rows during mail merge. This is the standard convention used in Shesha document generation.

### SS5 — Nested Region Table Convention

For parent-child relationships in tables, nest the child `TableStart`/`TableEnd` within the parent region:

```
«TableStart:ParentRegion»
Parent field: «ParentName»

  «TableStart:ChildRegion»
  | «Index» | «ChildName» | «ChildValue» |
  «TableEnd:ChildRegion»

«TableEnd:ParentRegion»
```

The child region must physically appear between the parent's start and end markers.

### SS6 — Document Packaging (ZIP as .docx)

```javascript
import archiver from "archiver";
import { createWriteStream } from "fs";

function createDocx(outputPath, bodyXml) {
  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
  xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
  xmlns:o="urn:schemas-microsoft-com:office:office"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
  xmlns:v="urn:schemas-microsoft-com:vml"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:w10="urn:schemas-microsoft-com:office:word"
  xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
  xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
  mc:Ignorable="w14">
  <w:body>
    ${bodyXml}
    <w:sectPr>
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"
               w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>`;

  const stylesXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:rPr><w:sz w:val="22"/><w:szCs w:val="22"/><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:keepNext/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:keepNext/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading3">
    <w:name w:val="heading 3"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:keepNext/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>
  </w:style>
</w:styles>`;

  const contentTypesXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>`;

  const relsXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`;

  const wordRelsXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
</Relationships>`;

  const settingsXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:defaultTabStop w:val="720"/>
</w:settings>`;

  return new Promise((resolve, reject) => {
    const output = createWriteStream(outputPath);
    const archive = archiver("zip", { zlib: { level: 9 } });
    archive.on("error", reject);
    output.on("close", () => resolve(archive.pointer()));
    archive.pipe(output);
    archive.append(contentTypesXml, { name: "[Content_Types].xml" });
    archive.append(relsXml, { name: "_rels/.rels" });
    archive.append(documentXml, { name: "word/document.xml" });
    archive.append(wordRelsXml, { name: "word/_rels/document.xml.rels" });
    archive.append(stylesXml, { name: "word/styles.xml" });
    archive.append(settingsXml, { name: "word/settings.xml" });
    archive.finalize();
  });
}
```

## Complete Generation Script Pattern

When generating a sample Word template, create a self-contained `.mjs` script that:

1. Defines all helper functions (SS1–SS6) inline
2. Builds the document body using the DTO's fields
3. Writes the `.docx` file to the project directory (next to the generated code artifacts)
4. Cleans up `node_modules` after generation

### Script structure:

```javascript
import archiver from "archiver";
import { createWriteStream } from "fs";

// -- Paste helper functions from SS1, SS2, SS3, SS4, SS6 --

// Build document body from DTO fields
const body = [
  // Title
  paragraph(textRun("Document Title", true), { alignment: "center", spacingAfter: "400" }),

  // Section with simple merge fields
  paragraph(textRun("Section Heading", true), { heading: "Heading2", spacingBefore: "200", spacingAfter: "200" }),
  labelAndField("Employee Name: ", "EmployeeName"),
  labelAndField("Date: ", "CreatedDate"),

  // Repeating region as a table
  paragraph(textRun("Items", true), { heading: "Heading2", spacingBefore: "200", spacingAfter: "200" }),
  tableWithRegion("ItemSection", [
    { label: "#", field: "Index", width: 800 },
    { label: "Description", field: "Name", width: 5000 },
    { label: "Amount", field: "Amount", width: 2400 },
  ]),

  // Signature area
  paragraph(textRun(""), { spacingBefore: "600" }),
  labelAndField("Signature: ", "EmployeeSignature"),
].join("\n");

// Generate the .docx
const bytes = await createDocx("./TemplateName.docx", body);
console.log(`Template created (${bytes} bytes)`);
```

### Running the script:

```bash
cd <project-root>
npm install archiver --no-save
node generate-template.mjs
rm generate-template.mjs
rm -rf node_modules package-lock.json package.json
```

## Individual Character Box Table Convention

For government forms where numbers are split into individual cells (e.g., PERSAL number, ID number):

```javascript
function digitBoxRow(label, fieldPrefix, count, cellWidth = 400) {
  const labelCell = `<w:tc><w:tcPr><w:tcW w:w="3000" w:type="dxa"/>` +
    `<w:tcBorders><w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/></w:tcBorders>` +
    `</w:tcPr><w:p>${textRun(label)}</w:p></w:tc>`;

  const digitCells = Array.from({ length: count }, (_, i) => {
    return `<w:tc><w:tcPr><w:tcW w:w="${cellWidth}" w:type="dxa"/>` +
      `<w:tcBorders>` +
      `<w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>` +
      `<w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>` +
      `<w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>` +
      `<w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>` +
      `</w:tcBorders></w:tcPr>` +
      `<w:p><w:pPr><w:jc w:val="center"/></w:pPr>${mergeFieldXml(`${fieldPrefix}${i}`)}</w:p></w:tc>`;
  }).join("");

  const totalWidth = 3000 + (count * cellWidth);
  return `<w:tbl><w:tblPr><w:tblW w:w="${totalWidth}" w:type="dxa"/></w:tblPr>` +
    `<w:tr>${labelCell}${digitCells}</w:tr></w:tbl>`;
}
```

## Field Name Conventions

| Scenario | Merge Field Name | Convention |
|----------|-----------------|------------|
| Simple text | `EmployeeName` | PascalCase matching DTO property |
| Date | `StartDate` | Pre-formatted as string in DTO |
| Checkbox | `IsApproved` | `"X"` or `""` |
| Signature | `EmployeeSignature` | `byte[]` in DTO |
| Region start | `TableStart:ItemSection` | Region name matches DataTable name |
| Region end | `TableEnd:ItemSection` | Must match start |
| Region field | `Index`, `Name` | Properties on item class |
| Digit box | `P0`, `P1`, ... `P7` | Prefix + zero-based index |
| Nested parent start | `TableStart:CategorySection` | Parent region |
| Nested child start | `TableStart:ItemSection` | Nested inside parent |
