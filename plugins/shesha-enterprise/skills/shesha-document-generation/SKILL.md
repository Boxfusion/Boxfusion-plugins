---
name: shesha-document-generation
description: Generates Shesha document generation artifacts for producing PDFs or Word documents from Word templates via Aspose mail merge. Creates DTOs, item classes, AutoMapper profiles, application services, controllers, Word template guidance, and sample Word document templates with proper merge fields. Use when the user asks to create, scaffold, or implement document generation, mail merge, Word-to-PDF conversion, Word document generation, document processing, or Word document templates in a Shesha project.
---

# Shesha Document Generation

Generate document generation artifacts for a Shesha/.NET application that uses `Shesha.Enterprise.DocumentProcessing` to produce PDFs or Word documents from Word templates via Aspose mail merge, based on $ARGUMENTS.

## Instructions

- Inspect nearby files to determine the correct namespace root.
- Ask the user which **template source** approach to use if not specified:
  1. **FileTemplateConfiguration by name** (default) — template uploaded via admin UI, resolved by name at runtime
  2. **Embedded resource** — template bundled in the assembly as an embedded resource, uses `AsposeBuilderBase.GetTemplate()`
  3. **Direct Aspose with dictionary** — manual template lookup, field names as string keys, most control
  4. **Save to StoredFile** — same as (1) or (2) but also persists the generated PDF to a `StoredFile` on the entity
  5. **StoredFile as template source** — template loaded from a `StoredFile` property on an entity (e.g., a config entity's template field), uses `IStoredFileService.GetStreamAsync()` to load and Aspose directly for mail merge
- Ask the user which **output format** to use if not specified:
  1. **PDF** (default) — generates a PDF via `document.Save(stream, SaveFormat.Pdf)`
  2. **Word (.docx)** — returns the populated Word document via `document.Save(stream, SaveFormat.Docx)`, preserving editability
  3. **Both** — generates separate endpoints for PDF and Word download
- Ask the user which **exposure** approach to use if not specified:
  1. **Application Service** (default) — inherits `SheshaAppServiceBase`, auto-registered as API endpoint
  2. **Controller** — inherits `ControllerBase`, manual `[Route]`/`[HttpGet]` attributes
  3. **Dictionary-based controller** — inherits `ControllerBase`, uses `Dictionary<string, object>` instead of a typed DTO
- When the output format is **Word only**, use `DocumentDto` instead of `PdfDto` in class names and `Documents` instead of `PdfDocuments` in folder names. When **PDF** or **Both**, keep `PdfDto`/`PdfDocuments`.
- All entity properties on DTOs should be `string` (pre-formatted) unless they are `byte[]` (signatures/images) or `DataTable`/`DataSet` (regions).
- DTO property names must match Word template merge field names exactly.
- Use `{Placeholder}` tokens throughout generated code so the user can replace them with project-specific values.
- **After generating document generation code artifacts, ALWAYS ask the user:** "Would you like me to generate a sample Word document template (`.docx`) with the correct merge fields for easy testing and subsequent modification?" If yes, generate the template using [word-template-generator.md](word-template-generator.md).
- When creating or updating Word templates, use the **complex field character** approach (`w:fldChar` begin/separate/end) — never `w:fldSimple`. See [word-template-generator.md](word-template-generator.md) for the full reference.

### Word Template Generation Rules

When generating sample `.docx` templates:

1. **Merge fields** must use `w:fldChar` complex field characters (begin → instrText → separate → display → end). The `w:fldSimple` element does NOT produce real merge fields recognized by Word or Aspose.
2. **Repeating regions** use `TableStart:RegionName` and `TableEnd:RegionName` merge fields. Place them in separate table rows around the data row. The data row (containing field merge fields) is the one that repeats. Aspose removes the marker rows during mail merge.
3. **Nested regions** (parent-child): the child `TableStart`/`TableEnd` must be physically nested inside the parent's start/end markers.
4. **Individual character boxes** (ID numbers, PERSAL numbers): split into individual merge fields with a prefix and zero-based index (e.g., `P0`, `P1`, ..., `P7`).
5. **Field names** must be PascalCase and match the DTO property names exactly (case-sensitive).
6. The generated template should be placed alongside the generated code artifacts or in the project root for easy access.
7. Clean up `node_modules`, `package-lock.json`, and the generator script after template generation.

## Artifact Catalog

| # | Artifact | Layer | Template |
|---|----------|-------|----------|
| 1 | PDF DTO | Application | [dto-and-items.md](dto-and-items.md) SS1 |
| 2 | Item Class (for regions) | Application | [dto-and-items.md](dto-and-items.md) SS2 |
| 3 | AutoMapper Profile | Application | [dto-and-items.md](dto-and-items.md) SS3 |
| 4 | Application Service | Application | [document-service.md](document-service.md) SS1 |
| 5 | Controller | Application | [document-service.md](document-service.md) SS2 |
| 6 | Dictionary-based Controller | Application | [document-service.md](document-service.md) SS3 |
| 7 | Word Document Output (no PDF) | Application | [document-service.md](document-service.md) SS5 |
| 8 | Embedded Resource variant | Application | [document-service.md](document-service.md) SS4 |
| 9 | StoredFile template source | Application | [document-service.md](document-service.md) SS6 |
| 10 | Module/NuGet setup | Domain/Application | [setup-and-templates.md](setup-and-templates.md) SS1 |
| 11 | Word template design guide | N/A | [setup-and-templates.md](setup-and-templates.md) SS2 |
| 12 | Sample Word template (.docx) | N/A | [word-template-generator.md](word-template-generator.md) |

## Folder Structure

```
{ModuleName}.Application/
  PdfDocuments/{DocumentName}/
    {DocumentName}AppService.cs          -- or {DocumentName}Controller.cs
    Dtos/
      {DocumentName}PdfDto.cs
      {ItemName}Section.cs               -- one per repeating region
    {DocumentName}MappingProfile.cs       -- if using typed DTO + AutoMapper
```

## Quick Reference

### Key Types from `Shesha.Enterprise.DocumentProcessing`

| Type | Purpose |
|------|---------|
| `DocumentProcessManager` | Main service — `GenerateAsync<T>(dto, templateName)` returns `Stream`, `GetDataTable<T>(list, tableName)` returns `DataTable` |
| `FileTemplateConfiguration` | Maps a template name (string) to a `StoredFile` in the database |
| `AsposeBuilderBase` | Base class with `GetTemplate()`, `AddPersonSignature()`, `ReplaceRichTextField()`, embedded resource support |
| `BaseDocumentProcessor` | Extended base with field settings parsing, cleanup options, rich text items |

### DocumentProcessManager API

```csharp
// Generate PDF stream from typed DTO + template name
Stream stream = await _documentProcessManager.GenerateAsync(pdfDto, "TemplateName");

// Convert a list of items to a DataTable for mail merge regions
DataTable table = _documentProcessManager.GetDataTable(items, "RegionName");

// Save generated PDF as a StoredFile
StoredFile file = await _documentProcessManager.SaveFileAsync(stream, ownerType, ownerId, "TemplateName");
```

### Aspose Mail Merge Cleanup Options

**Important:** `MailMergeCleanupOptions` requires `using Aspose.Words.MailMerging;` — this is a separate namespace from `Aspose.Words`.

```csharp
using Aspose.Words.MailMerging; // Required for MailMergeCleanupOptions

builder.Document.MailMerge.CleanupOptions =
    MailMergeCleanupOptions.RemoveEmptyParagraphs |
    MailMergeCleanupOptions.RemoveUnusedFields |
    MailMergeCleanupOptions.RemoveUnusedRegions;
```

### Signature Pattern

```csharp
// DTO property — byte[] rendered as image in merge field
public byte[] {Role}Signature { get; set; }

// Loading signature bytes from a Person's StoredFile
using var sigStream = await _storedFileService.GetStreamAsync(person.SignatureFile);
using var ms = new MemoryStream();
await sigStream.CopyToAsync(ms);
dto.{Role}Signature = ms.ToArray();
```

### DataTable Region (Repeating Rows)

```csharp
// DTO property
public DataTable {RegionName} { get; set; }

// Building the table
var items = entities.Select(e => new {RegionItem}
{
    Name = e.Name,
    Value = e.Value?.ToString() ?? ""
}).ToList();

dto.{RegionName} = _documentProcessManager.GetDataTable(items, "{RegionName}");
```

### Nested Region (Parent-Child DataSet)

```csharp
// Create parent and child tables
var parentTable = _documentProcessManager.GetDataTable(parentItems, "ParentRegion");
var childTable = _documentProcessManager.GetDataTable(childItems, "ChildRegion");

// Build DataSet with relationship
var dataSet = new DataSet();
dataSet.Tables.Add(parentTable.Copy());
dataSet.Tables.Add(childTable.Copy());
dataSet.Relations.Add(new DataRelation("ParentChildRelation",
    dataSet.Tables["ParentRegion"].Columns["ParentId"],
    dataSet.Tables["ChildRegion"].Columns["ParentId"]));

// Store in DTO
dto.ParentRegion = dataSet.Tables["ParentRegion"];
dto.ChildRegion = dataSet.Tables["ChildRegion"];
dto.ParentChildDataSet = dataSet;
```

### HTML Stripping (for rich text fields stored as HTML)

```csharp
using System.Text.RegularExpressions;

private static string StripHtml(string html)
{
    if (string.IsNullOrEmpty(html)) return "";
    return Regex.Replace(html, "<.*?>", string.Empty).Trim();
}
```

## Common Patterns

**Return PDF as download:**
```csharp
using var documentStream = await _documentProcessManager.GenerateAsync(pdfDto, templateName);
using var memoryStream = new MemoryStream();
await documentStream.CopyToAsync(memoryStream);
var bytes = memoryStream.ToArray();
return File(bytes, "application/pdf", fileName);
```

**Return Word document as download (no PDF conversion):**
```csharp
// Use Aspose directly — DocumentProcessManager.GenerateAsync() always returns PDF
var document = new Document(templateStream); // load from FileTemplateConfiguration or embedded resource
document.MailMerge.Execute(fieldNames, fieldValues);
using var memoryStream = new MemoryStream();
document.Save(memoryStream, SaveFormat.Docx);
var bytes = memoryStream.ToArray();
var fileName = $"{DocumentName}_{DateTime.Now:yyyyMMdd}.docx";
return File(bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", fileName);
```
See [document-service.md](document-service.md) SS5 for the full application service and controller templates.

**Save PDF to entity StoredFile property:**
```csharp
using var documentStream = await _documentProcessManager.GenerateAsync(pdfDto, templateName);
using var memoryStream = new MemoryStream();
await documentStream.CopyToAsync(memoryStream);
memoryStream.Position = 0;

var storedFile = await _storedFileService.SaveFileAsync(
    memoryStream,
    fileName,
    file => { file.FileType = "application/pdf"; });

entity.PdfDocument = storedFile;
await _repository.UpdateAsync(entity);
```

**Generate safe file name:**
```csharp
private static string GenerateFileName(string prefix, string identifier)
{
    var fileName = $"{prefix}_{identifier}_{DateTime.Now:yyyyMMdd}.pdf";
    return string.Join("_", fileName.Split(Path.GetInvalidFileNameChars()));
}
```

Now generate the requested artifact(s) based on: $ARGUMENTS
