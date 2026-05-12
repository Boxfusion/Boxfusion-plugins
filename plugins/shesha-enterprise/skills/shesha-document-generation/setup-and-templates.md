# Setup and Word Template Design

## SS1 — Module and NuGet Setup

### NuGet Package Reference

Add the `Shesha.Enterprise.DocumentProcessing` package to your Application project's `.csproj`:

```xml
<ItemGroup>
  <PackageReference Include="Shesha.Enterprise.DocumentProcessing" Version="$(SheshaEnterpriseVersion)" />
</ItemGroup>
```

> **Important:** This is a Shesha **Enterprise** package, so use `$(SheshaEnterpriseVersion)` — not `$(SheshaVersion)`. Check `Directory.Build.props` for the correct variable name. Look at existing `Shesha.Enterprise.*` package references in the `.csproj` to confirm which version variable to use.

### Module Dependency

Add the `DocumentProcessingModule` to your Application module's `[DependsOn]`:

```csharp
using Shesha.Enterprise.DocumentProcessing;

[DependsOn(
    typeof({ModuleName}Module),
    typeof(DocumentProcessingModule)  // Add this
)]
public class {ModuleName}ApplicationModule : SheshaSubModule<{ModuleName}Module>
{
    // ...
}
```

### Aspose License

Aspose.Words requires a license for production use (without it, documents have evaluation watermarks). The license is typically configured in `Startup.cs` or the module's `Initialize()` method. Check if the project already has Aspose license setup — if so, no additional configuration is needed.

### FileTemplateConfiguration (Admin UI Setup)

Templates are registered in the Shesha admin UI as `FileTemplateConfiguration` items:

1. Navigate to the admin portal Configuration Items section
2. Create a new File Template configuration
3. Set the **Name** to match the `TEMPLATE_NAME` constant in your code (e.g., `"InvoiceTemplate"`)
4. Upload the `.docx` Word template file
5. Publish the configuration item

The `DocumentProcessManager.GenerateAsync()` method resolves templates by this name at runtime.

---

## SS2 — Word Template Design Guide

### Merge Field Basics

Aspose mail merge replaces `MERGEFIELD` fields in Word documents with values from the DTO properties or dictionary keys.

**To insert a merge field in Word:**
1. Go to Insert > Quick Parts > Field (or press Alt+F9 to toggle field codes)
2. Select `MergeField` from the field list
3. Enter the field name matching your DTO property name exactly (case-sensitive)

**Field code format:**
```
{ MERGEFIELD FieldName }
```

> The curly braces are Word field delimiters, not regular text. Use Insert > Field to create them, not by typing `{` and `}`.

### Simple Text Fields

Map directly to `string` properties on the DTO or string values in the dictionary.

| Word Template | DTO Property | Value Example |
|---------------|-------------|---------------|
| `{ MERGEFIELD EmployeeName }` | `public string EmployeeName { get; set; }` | `"John Smith"` |
| `{ MERGEFIELD CreatedDate }` | `public string CreatedDate { get; set; }` | `"15/03/2025"` |
| `{ MERGEFIELD Status }` | `public string Status { get; set; }` | `"Approved"` |

### Image Fields (Signatures, Logos)

Map to `byte[]` properties. Aspose automatically detects `byte[]` values and inserts them as images into the merge field location.

| Word Template | DTO Property |
|---------------|-------------|
| `{ MERGEFIELD EmployeeSignature }` | `public byte[] EmployeeSignature { get; set; }` |

**Image sizing:** The image fills the merge field's container. To control size, format the merge field in Word with a specific width/height, or resize the `byte[]` in code before assignment.

**Signature loading pattern:**
```csharp
using var stream = await _storedFileService.GetStreamAsync(person.SignatureFile);
using var ms = new MemoryStream();
await stream.CopyToAsync(ms);
dto.EmployeeSignature = ms.ToArray();
```

### Checkbox Fields

Word doesn't have native checkbox merge fields. Use a text merge field with `"X"` or `""`:

| Word Template | DTO/Dictionary |
|---------------|---------------|
| `[ { MERGEFIELD IsApproved } ]` | `dict["IsApproved"] = isApproved ? "X" : "";` |

Format the merge field with a checkbox-style font (e.g., Wingdings) if you want a visual checkbox appearance, or use square brackets around the field.

### Individual Character Fields (Form Boxes)

For government forms with individual character boxes (e.g., ID numbers, PERSAL numbers), split the string into individual merge fields:

**Word template:**
```
| { MERGEFIELD P0 } | { MERGEFIELD P1 } | { MERGEFIELD P2 } | ...
```

**Code:**
```csharp
for (var i = 0; i < 8; i++)
{
    dict[$"P{i}"] = (persalNo != null && persalNo.Length > i)
        ? persalNo[i].ToString() : " ";
}
```

### Repeating Regions (DataTable)

Regions define repeating blocks in the template. They use special merge fields to mark start and end:

**Word template:**
```
{ MERGEFIELD TableStart:ItemSection }
| { MERGEFIELD Index } | { MERGEFIELD Name } | { MERGEFIELD Amount } |
{ MERGEFIELD TableEnd:ItemSection }
```

**DTO:**
```csharp
public DataTable ItemSection { get; set; }
```

**Code:**
```csharp
var items = entities.Select((e, i) => new ItemSection
{
    Index = i + 1,
    Name = e.Name ?? "",
    Amount = e.Amount?.ToString("N2") ?? ""
}).ToList();

dto.ItemSection = _documentProcessManager.GetDataTable(items, "ItemSection");
```

**Rules:**
- The region name in `TableStart:{Name}` and `TableEnd:{Name}` must match the DataTable's `TableName` property.
- The `GetDataTable()` method sets the `TableName` automatically from the second parameter.
- Merge fields inside the region match the item class property names.
- The entire block between `TableStart` and `TableEnd` is repeated for each row.

### Nested Regions (DataSet with Relationships)

For parent-child relationships (e.g., categories with sub-items), use a `DataSet` with a `DataRelation`:

**Word template:**
```
{ MERGEFIELD TableStart:CategorySection }
Category: { MERGEFIELD CategoryName }

  { MERGEFIELD TableStart:ItemSection }
  - { MERGEFIELD ItemName }: { MERGEFIELD ItemValue }
  { MERGEFIELD TableEnd:ItemSection }

{ MERGEFIELD TableEnd:CategorySection }
```

**DTO:**
```csharp
public DataTable CategorySection { get; set; }
public DataTable ItemSection { get; set; }
public DataSet CategoryItemDataSet { get; set; }
```

**Code:**
```csharp
// Build parent items with a unique ID
var categories = categoryEntities.Select(c => new CategorySection
{
    CategorySectionId = c.Id,
    CategoryName = c.Name ?? ""
}).ToList();

// Build child items with FK to parent
var items = itemEntities.Select(i => new ItemSection
{
    CategorySectionId = i.Category.Id,  // FK matches parent PK
    ItemName = i.Name ?? "",
    ItemValue = i.Value?.ToString() ?? ""
}).ToList();

// Create DataSet with relationship
var parentTable = _documentProcessManager.GetDataTable(categories, "CategorySection");
var childTable = _documentProcessManager.GetDataTable(items, "ItemSection");

var dataSet = new DataSet();
dataSet.Tables.Add(parentTable.Copy());
dataSet.Tables.Add(childTable.Copy());
dataSet.Relations.Add(new DataRelation("CategoryItemRelation",
    dataSet.Tables["CategorySection"].Columns["CategorySectionId"],
    dataSet.Tables["ItemSection"].Columns["CategorySectionId"]));

dto.CategorySection = dataSet.Tables["CategorySection"];
dto.ItemSection = dataSet.Tables["ItemSection"];
dto.CategoryItemDataSet = dataSet;
```

**Rules:**
- Both tables must share a column with the same name for the `DataRelation` FK.
- Use `.Copy()` when adding tables to the `DataSet` to avoid "table already belongs to another DataSet" errors.
- The child region must be physically nested inside the parent region in the Word template.
- Store the `DataSet` on the DTO so the garbage collector doesn't dispose it before mail merge runs.

### Cleanup Options

Configure how Aspose handles unmerged fields:

| Option | Effect |
|--------|--------|
| `RemoveEmptyParagraphs` | Removes paragraphs that become empty after merge |
| `RemoveUnusedFields` | Removes merge fields that weren't matched to any data |
| `RemoveUnusedRegions` | Removes entire region blocks that had no data |
| `RemoveContainingFields` | Removes fields containing nested merge fields |

**Default recommendation:**
```csharp
document.MailMerge.CleanupOptions =
    MailMergeCleanupOptions.RemoveEmptyParagraphs |
    MailMergeCleanupOptions.RemoveUnusedFields |
    MailMergeCleanupOptions.RemoveUnusedRegions;
```

> Be careful with `RemoveEmptyParagraphs` if your template intentionally has blank lines for spacing. Test the output carefully.

### HTML Content in Merge Fields

If your entity stores rich text as HTML and you want it rendered in the PDF, use `AsposeBuilderBase.ReplaceRichTextField()` or strip the HTML:

**Option A — Strip HTML to plain text:**
```csharp
dto.Comments = Regex.Replace(entity.CommentsHtml ?? "", "<.*?>", "").Trim();
```

**Option B — Render HTML (requires AsposeBuilderBase):**
```csharp
// In a class inheriting AsposeBuilderBase
ReplaceRichTextField(builder, "Comments", entity.CommentsHtml);
```

### Template Design Tips

1. **Test early** — Generate a test PDF as soon as you have the template and basic DTO wired up. Don't wait until all fields are populated.
2. **Use placeholder text** — Fill merge fields with sample values in the Word template for visual design, then test with actual data.
3. **Table alignment** — For repeating regions inside Word tables, place `TableStart` and `TableEnd` fields in separate rows or in the same row as data fields. The entire row is repeated.
4. **Page breaks** — For multi-page regions, consider inserting page breaks inside the region template.
5. **Font consistency** — Set fonts on the merge fields in Word. The merged text inherits the formatting of the merge field.
6. **Field naming** — Use PascalCase for field names matching C# property names. Avoid spaces or special characters.
7. **Debug merge fields** — Press Alt+F9 in Word to toggle between field codes and results. This helps verify field names.
