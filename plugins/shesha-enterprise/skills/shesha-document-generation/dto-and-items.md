# DTO and Item Classes

## SS1 — PDF DTO

The PDF DTO is the top-level object passed to `DocumentProcessManager.GenerateAsync()`. Each public property maps to a merge field in the Word template. Property names must match merge field names exactly (case-sensitive).

### Property type rules

| C# Type | Word Template Usage |
|---------|-------------------|
| `string` | Simple text merge field |
| `byte[]` | Image merge field (signatures, logos) |
| `DataTable` | Repeating region (`<<TableStart:RegionName>>` ... `<<TableEnd:RegionName>>`) |
| `DataSet` | Nested regions with parent-child relationships |

### Template

```csharp
using System.Data;

namespace {Namespace}.PdfDocuments.{DocumentName}.Dtos
{
    public class {DocumentName}PdfDto
    {
        // Simple text fields — match merge field names in Word template
        public string {FieldName1} { get; set; }
        public string {FieldName2} { get; set; }

        // Date fields — format as string before assignment
        // e.g., entity.CreatedDate?.ToString("dd/MM/yyyy") ?? ""
        public string {DateFieldName} { get; set; }

        // Numeric fields — format as string before assignment
        // e.g., entity.Score?.ToString("0.00") ?? ""
        public string {NumericFieldName} { get; set; }

        // Image/signature fields — byte[] rendered as image in merge field
        public byte[] {SignatureFieldName} { get; set; }

        // Repeating region — DataTable for simple flat lists
        public DataTable {RegionName} { get; set; }

        // Nested regions — DataSet holds parent+child tables with a relationship
        public DataSet {ParentChildDataSetName} { get; set; }

        // If using nested regions, also expose individual tables
        public DataTable {ParentRegionName} { get; set; }
        public DataTable {ChildRegionName} { get; set; }
    }
}
```

### Guidance

- Pre-format all values as strings in the service/controller before assigning to the DTO. The DTO should contain display-ready values, not raw domain types.
- For nullable fields, use the null-coalescing pattern: `entity.Field?.ToString() ?? ""`.
- For reference list values, resolve the display text using `ReferenceListHelper.GetItemDisplayText()` before assignment.
- For checkbox-style fields in Word, use `"X"` for checked and `""` for unchecked.
- Keep the DTO flat — avoid navigation properties. Flatten entity graphs in the service layer.

---

## SS2 — Item Class (for Regions)

Item classes represent rows in a repeating region. Each public property maps to a merge field inside the `<<TableStart:RegionName>>` ... `<<TableEnd:RegionName>>` block.

### Template

```csharp
using System;

namespace {Namespace}.PdfDocuments.{DocumentName}.Dtos
{
    public class {ItemName}Section
    {
        // Row index (1-based) — useful for numbered lists in the template
        public int Index { get; set; }

        // Foreign key for nested regions — must match parent table's key column
        // Only needed if this is a child in a DataSet relationship
        public Guid {ParentRegionName}Id { get; set; }

        // Item fields — match merge field names inside the region
        public string {FieldName1} { get; set; }
        public string {FieldName2} { get; set; }

        // Nested child region (optional) — only if this item has its own sub-table
        // public DataTable {ChildRegionName} { get; set; }
    }
}
```

### Nested Region Example

For a parent-child relationship (e.g., Categories with Items):

```csharp
// Parent item
public class {ParentName}Section
{
    public int Index { get; set; }
    public Guid {ParentName}SectionId { get; set; }  // PK for relationship
    public string Name { get; set; }
    public string Description { get; set; }
}

// Child item
public class {ChildName}Section
{
    public Guid {ParentName}SectionId { get; set; }  // FK matching parent PK
    public string Name { get; set; }
    public string Value { get; set; }
}
```

### Guidance

- The `Index` property is useful for numbered lists. Assign it sequentially when building the list: `items.Select((e, i) => new Section { Index = i + 1, ... })`.
- For nested regions, the FK column name must match exactly between parent and child tables. The `DataRelation` links on this column.
- All properties should be `string` except `Index` (int), FK columns (Guid), and nested `DataTable` properties.

---

## SS3 — AutoMapper Profile

Use an AutoMapper profile when the DTO fields map closely to entity properties. This avoids manual property-by-property assignment for the common fields, while still allowing manual overrides for computed or formatted fields.

### Template

```csharp
using AutoMapper;
using {Namespace}.PdfDocuments.{DocumentName}.Dtos;

namespace {Namespace}.PdfDocuments.{DocumentName}
{
    public class {DocumentName}MappingProfile : Profile
    {
        public {DocumentName}MappingProfile()
        {
            // Main entity -> PDF DTO
            CreateMap<{EntityType}, {DocumentName}PdfDto>()
                // Direct string mappings
                .ForMember(d => d.{FieldName1}, opt => opt.MapFrom(s => s.{EntityProperty1} ?? ""))
                // Navigation property flattening
                .ForMember(d => d.{FieldName2}, opt => opt.MapFrom(s => s.{Navigation}?.{Property} ?? ""))
                // Date formatting
                .ForMember(d => d.{DateField}, opt => opt.MapFrom(s =>
                    s.{DateProperty}.HasValue ? s.{DateProperty}.Value.ToString("dd/MM/yyyy") : ""))
                // Numeric formatting
                .ForMember(d => d.{NumericField}, opt => opt.MapFrom(s =>
                    s.{NumericProperty}.HasValue ? s.{NumericProperty}.Value.ToString("0.00") : ""))
                // Ignore fields populated manually (signatures, regions, computed fields)
                .ForMember(d => d.{SignatureField}, opt => opt.Ignore())
                .ForMember(d => d.{RegionName}, opt => opt.Ignore());

            // Entity -> Region item (if applicable)
            CreateMap<{ChildEntityType}, {ItemName}Section>()
                .ForMember(d => d.Name, opt => opt.MapFrom(s => s.{NameProperty} ?? ""))
                .ForMember(d => d.Index, opt => opt.Ignore()); // Set manually with sequential index
        }
    }
}
```

### Guidance

- Inherit from `Profile` (AutoMapper), not `ShaProfile` — PDF mapping profiles are standalone.
- **However**, if you want the profile to be auto-discovered by Shesha's module system, inherit from `ShaProfile` instead.
- Always `.Ignore()` properties that are populated manually: signatures (`byte[]`), regions (`DataTable`), computed fields.
- Format dates and numbers in the `MapFrom` expression so the DTO is display-ready.
- Use `?? ""` for all string mappings to avoid null merge field values in the Word template.
