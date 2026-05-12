# Document Generation Service

## SS1 — Application Service (SheshaAppServiceBase)

Use this approach when you want the endpoint auto-registered by the Shesha module system. No manual route configuration needed.

### Template

```csharp
using Abp.Domain.Repositories;
using Abp.UI;
using Aspose.Words.MailMerging;
using AutoMapper;
using Microsoft.AspNetCore.Mvc;
using NHibernate.Linq;
using {Namespace}.PdfDocuments.{DocumentName}.Dtos;
using Shesha.Enterprise.DocumentProcessing.Domain;
using Shesha.Services;
using System;
using System.Data;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace {Namespace}.PdfDocuments.{DocumentName}
{
    /// <summary>
    /// Application service for generating {DocumentName} PDF documents
    /// </summary>
    public class {DocumentName}AppService : SheshaAppServiceBase
    {
        private const string TEMPLATE_NAME = "{TemplateName}";

        private readonly DocumentProcessManager _documentProcessManager;
        private readonly IRepository<{EntityType}, Guid> _entityRepository;
        private readonly IMapper _objectMapper;

        public {DocumentName}AppService(
            DocumentProcessManager documentProcessManager,
            IRepository<{EntityType}, Guid> entityRepository,
            IMapper objectMapper)
        {
            _documentProcessManager = documentProcessManager;
            _entityRepository = entityRepository;
            _objectMapper = objectMapper;
        }

        /// <summary>
        /// Generates and downloads a {DocumentName} PDF document
        /// </summary>
        [HttpGet]
        public async Task<FileStreamResult> GenerateAndDownloadPdfAsync(Guid {entityParam}Id)
        {
            if ({entityParam}Id == Guid.Empty)
                throw new UserFriendlyException("Invalid {EntityName} ID.");

            // 1. Load entity and related data
            var entity = await _entityRepository.GetAsync({entityParam}Id);

            // 2. Build PDF DTO
            var pdfDto = _objectMapper.Map<{DocumentName}PdfDto>(entity);

            // 3. Populate fields that require manual logic
            // pdfDto.{ComputedField} = await Compute{Field}Async(entity);

            // 4. Populate repeating regions (if any)
            // var items = await Get{RegionName}ItemsAsync(entity);
            // pdfDto.{RegionName} = _documentProcessManager.GetDataTable(items, "{RegionName}");

            // 5. Generate PDF
            using var documentStream = await _documentProcessManager.GenerateAsync(pdfDto, TEMPLATE_NAME);
            using var memoryStream = new MemoryStream();
            await documentStream.CopyToAsync(memoryStream);
            memoryStream.Position = 0;

            var fileName = GenerateFileName(entity);
            return new FileStreamResult(new MemoryStream(memoryStream.ToArray()), "application/pdf")
            {
                FileDownloadName = fileName
            };
        }

        private static string GenerateFileName({EntityType} entity)
        {
            var identifier = entity.{IdentifierProperty}?.ToString() ?? "Unknown";
            var fileName = $"{DocumentName}_{identifier}_{DateTime.Now:yyyyMMdd}.pdf";
            return string.Join("_", fileName.Split(Path.GetInvalidFileNameChars()));
        }
    }
}
```

### Guidance

- `SheshaAppServiceBase` auto-registers the service as a REST endpoint. The route is determined by the module's `CreateControllersForAppServices` call.
- Use `FileStreamResult` for returning files from app services. `IActionResult File(...)` is for controllers.
- Inject `IMapper` for AutoMapper, or use `ObjectMapper` from the ABP base class.

---

## SS2 — Controller (ControllerBase)

Use this approach when you need explicit route control or when the PDF generation doesn't fit the app service pattern.

### Template

```csharp
using Abp.Dependency;
using Abp.Domain.Repositories;
using Abp.UI;
using AutoMapper;
using Microsoft.AspNetCore.Mvc;
using NHibernate.Linq;
using {Namespace}.PdfDocuments.{DocumentName}.Dtos;
using Shesha.Enterprise.DocumentProcessing.Domain;
using Shesha.Services;
using System;
using System.Data;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace {Namespace}.PdfDocuments.{DocumentName}
{
    /// <summary>
    /// Controller for generating {DocumentName} PDF documents
    /// </summary>
    [Route("api/[controller]")]
    [ApiController]
    public class {DocumentName}Controller : ControllerBase, ITransientDependency
    {
        private const string TEMPLATE_NAME = "{TemplateName}";

        private readonly DocumentProcessManager _documentProcessManager;
        private readonly IRepository<{EntityType}, Guid> _entityRepository;
        private readonly IMapper _objectMapper;
        private readonly IStoredFileService _storedFileService;

        public {DocumentName}Controller(
            DocumentProcessManager documentProcessManager,
            IRepository<{EntityType}, Guid> entityRepository,
            IMapper objectMapper,
            IStoredFileService storedFileService)
        {
            _documentProcessManager = documentProcessManager;
            _entityRepository = entityRepository;
            _objectMapper = objectMapper;
            _storedFileService = storedFileService;
        }

        /// <summary>
        /// Generates and downloads a {DocumentName} PDF document
        /// </summary>
        [HttpGet("GenerateAndDownloadPdf")]
        public async Task<IActionResult> GenerateAndDownloadPdfAsync(Guid {entityParam}Id)
        {
            try
            {
                if ({entityParam}Id == Guid.Empty)
                    throw new UserFriendlyException("Invalid {EntityName} ID.");

                // 1. Load entity and related data
                var entity = await _entityRepository.GetAsync({entityParam}Id);

                // 2. Build PDF DTO via AutoMapper
                var pdfDto = _objectMapper.Map<{DocumentName}PdfDto>(entity);

                // 3. Populate fields that require manual logic
                // pdfDto.{ComputedField} = await Compute{Field}Async(entity);

                // 4. Populate signature fields (if any)
                // await AddSignatureAsync(pdfDto, "{SignatureFieldName}", person);

                // 5. Populate repeating regions (if any)
                // var items = await Get{RegionName}ItemsAsync(entity);
                // pdfDto.{RegionName} = _documentProcessManager.GetDataTable(items, "{RegionName}");

                // 6. Generate PDF and return
                using var documentStream = await _documentProcessManager.GenerateAsync(pdfDto, TEMPLATE_NAME);
                using var memoryStream = new MemoryStream();
                await documentStream.CopyToAsync(memoryStream);
                var bytes = memoryStream.ToArray();

                var fileName = GenerateFileName(entity);
                return File(bytes, "application/pdf", fileName);
            }
            catch (Exception ex)
            {
                throw new UserFriendlyException($"Failed to generate PDF: {ex.Message}");
            }
        }

        private static string GenerateFileName({EntityType} entity)
        {
            var identifier = entity.{IdentifierProperty}?.ToString() ?? "Unknown";
            var fileName = $"{DocumentName}_{identifier}_{DateTime.Now:yyyyMMdd}.pdf";
            return string.Join("_", fileName.Split(Path.GetInvalidFileNameChars()));
        }

        /// <summary>
        /// Helper to load a person's signature as byte[] for the DTO
        /// </summary>
        private async Task AddSignatureAsync({DocumentName}PdfDto dto, string fieldName, Shesha.Domain.Person person)
        {
            if (person?.SignatureFile == null) return;

            try
            {
                using var sigStream = await _storedFileService.GetStreamAsync(person.SignatureFile);
                if (sigStream == null) return;

                using var ms = new MemoryStream();
                await sigStream.CopyToAsync(ms);

                // Use reflection or a switch to set the correct property
                var prop = typeof({DocumentName}PdfDto).GetProperty(fieldName);
                prop?.SetValue(dto, ms.ToArray());
            }
            catch
            {
                // Signature not available — leave field empty
            }
        }
    }
}
```

### Guidance

- Controllers must implement `ITransientDependency` for ABP DI registration.
- Use `[Route("api/[controller]")]` and `[ApiController]` attributes.
- Action methods use `[HttpGet("ActionName")]` for explicit routing.
- Wrap the entire action in try/catch and throw `UserFriendlyException` for user-visible errors.
- The `AddSignatureAsync` helper uses reflection to set signature bytes by field name. For a small number of signatures, direct property assignment is cleaner.

---

## SS3 — Dictionary-Based Controller (Direct Aspose)

Use this approach when merge fields are highly dynamic, don't map cleanly to a typed DTO, or when you need full control over the Aspose mail merge process.

### Template

```csharp
using Abp.Dependency;
using Abp.Domain.Repositories;
using Aspose.Words;
using Aspose.Words.MailMerging;
using Microsoft.AspNetCore.Mvc;
using NHibernate.Linq;
using Shesha.Enterprise.DocumentProcessing.Domain;
using Shesha.Services;
using System;
using System.Collections.Generic;
using System.Data;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace {Namespace}.PdfDocuments
{
    [Route("api/[controller]")]
    [ApiController]
    public class {DocumentName}Controller : ControllerBase, ITransientDependency
    {
        private const string TEMPLATE_NAME = "{TemplateName}";

        private readonly DocumentProcessManager _documentProcessManager;
        private readonly IRepository<{EntityType}, Guid> _entityRepository;
        private readonly IStoredFileService _storedFileService;
        private readonly IRepository<StoredFile, Guid> _storedFileRepo;

        public {DocumentName}Controller(
            DocumentProcessManager documentProcessManager,
            IRepository<{EntityType}, Guid> entityRepository,
            IStoredFileService storedFileService,
            IRepository<StoredFile, Guid> storedFileRepo)
        {
            _documentProcessManager = documentProcessManager;
            _entityRepository = entityRepository;
            _storedFileService = storedFileService;
            _storedFileRepo = storedFileRepo;
        }

        [HttpGet("GenerateAndDownloadPdf")]
        public async Task<IActionResult> GenerateAndDownloadPdfAsync(Guid {entityParam}Id)
        {
            try
            {
                var entity = await _entityRepository.GetAsync({entityParam}Id);

                // Build all fields as dictionary
                var fields = new Dictionary<string, object>();
                await PopulateFieldsAsync(fields, entity);

                // Generate document from dictionary
                using var documentStream = await GenerateFromDictionaryAsync(fields, TEMPLATE_NAME);
                documentStream.Position = 0;

                var fileName = GenerateFileName(entity);
                return File(documentStream, "application/pdf", fileName);
            }
            catch (Exception ex)
            {
                return BadRequest($"Failed to generate PDF: {ex.Message}");
            }
        }

        private async Task PopulateFieldsAsync(Dictionary<string, object> dict, {EntityType} entity)
        {
            // Simple text fields
            dict["{MergeField1}"] = entity.{Property1} ?? "";
            dict["{MergeField2}"] = entity.{Navigation}?.{Property} ?? "";

            // Date fields — format as string
            dict["{DateField}"] = entity.{DateProperty}?.ToString("dd/MM/yyyy") ?? "";

            // Checkbox fields — "X" or ""
            dict["{CheckboxField}"] = entity.{BoolProperty} == true ? "X" : "";

            // Signature fields — byte[]
            // await AddSignatureToDictionaryAsync(dict, "{SignatureField}", person);

            // Individual character fields (e.g., ID number split into cells)
            // SetDigitFields(dict, "{FieldPrefix}", entity.{NumberString}, expectedLength: 8);
        }

        private async Task<MemoryStream> GenerateFromDictionaryAsync(
            Dictionary<string, object> fields, string templateName)
        {
            // Resolve template
            var templateId = await GetTemplateIdAsync(templateName);
            var templateFile = await _storedFileRepo.GetAsync(templateId);
            using var templateStream = await _storedFileService.GetStreamAsync(templateFile.LastVersion());

            // Create Aspose document
            var document = new Document(templateStream);
            var builder = new DocumentBuilder(document);

            // Configure cleanup
            builder.Document.MailMerge.CleanupOptions =
                MailMergeCleanupOptions.RemoveEmptyParagraphs |
                MailMergeCleanupOptions.RemoveUnusedFields |
                MailMergeCleanupOptions.RemoveUnusedRegions;

            // Execute simple field merge
            builder.Document.MailMerge.Execute(
                fields.Select(x => x.Key).ToArray(),
                fields.Select(x => x.Value).ToArray());

            // Execute region merges for any DataTable values
            foreach (var field in fields.Where(f => f.Value is DataTable))
            {
                builder.Document.MailMerge.ExecuteWithRegions((DataTable)field.Value);
            }

            // Save as PDF
            var memoryStream = new MemoryStream();
            document.Save(memoryStream, SaveFormat.Pdf);
            memoryStream.Seek(0, SeekOrigin.Begin);
            return memoryStream;
        }

        private async Task<Guid> GetTemplateIdAsync(string templateName)
        {
            var repository = StaticContext.IocManager.Resolve<IRepository<FileTemplateConfiguration, Guid>>();
            var config = await repository.FirstOrDefaultAsync(r => r.Name == templateName);
            if (config?.DocumentTemplate == null)
                throw new Exception($"Template '{templateName}' not found");
            return config.DocumentTemplate.Id;
        }

        /// <summary>
        /// Splits a string into individual character fields: {Prefix}0, {Prefix}1, etc.
        /// Useful for forms with individual character boxes (e.g., ID numbers, PERSAL numbers).
        /// </summary>
        private static void SetDigitFields(Dictionary<string, object> dict, string prefix, string value, int expectedLength)
        {
            for (var i = 0; i < expectedLength; i++)
            {
                dict[$"{prefix}{i}"] = (value != null && value.Length > i) ? value[i].ToString() : " ";
            }
        }

        private static string GenerateFileName({EntityType} entity)
        {
            var identifier = entity.{IdentifierProperty}?.ToString() ?? "Unknown";
            var fileName = $"{DocumentName}_{identifier}_{DateTime.Now:yyyyMMdd}.pdf";
            return string.Join("_", fileName.Split(Path.GetInvalidFileNameChars()));
        }
    }
}
```

### Guidance

- Dictionary keys are merge field names from the Word template. Values are `object` — strings for text, `byte[]` for images, `DataTable` for regions.
- This approach gives full control over the Aspose API. Use it when fields are highly dynamic or when the template has complex form layouts (individual character boxes, conditional sections).
- `StaticContext.IocManager.Resolve<>()` is used for resolving `FileTemplateConfiguration` repository inline. This is acceptable in controller context but avoid in domain services.
- The `SetDigitFields` helper is useful for government forms that split numbers into individual cells.

---

## SS5 — Word Document Output (No PDF Conversion)

Use this approach when you need to return a populated Word document (.docx) instead of converting to PDF. This preserves editability — useful when users need to make final adjustments before printing or when PDF conversion is not required.

Since `DocumentProcessManager.GenerateAsync()` always returns PDF, this approach uses Aspose directly to perform the mail merge and save as `.docx`.

### Template (Application Service)

```csharp
using Abp.Domain.Repositories;
using Abp.UI;
using Aspose.Words;
using Aspose.Words.MailMerging;
using AutoMapper;
using Microsoft.AspNetCore.Mvc;
using NHibernate.Linq;
using {Namespace}.PdfDocuments.{DocumentName}.Dtos;
using Shesha.Enterprise.DocumentProcessing.Domain;
using Shesha.Services;
using System;
using System.Data;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace {Namespace}.PdfDocuments.{DocumentName}
{
    /// <summary>
    /// Application service for generating {DocumentName} documents
    /// </summary>
    public class {DocumentName}AppService : SheshaAppServiceBase
    {
        private const string TEMPLATE_NAME = "{TemplateName}";

        private readonly IRepository<{EntityType}, Guid> _entityRepository;
        private readonly IMapper _objectMapper;
        private readonly IRepository<FileTemplateConfiguration, Guid> _templateRepository;
        private readonly IStoredFileService _storedFileService;
        private readonly IRepository<StoredFile, Guid> _storedFileRepo;

        public {DocumentName}AppService(
            IRepository<{EntityType}, Guid> entityRepository,
            IMapper objectMapper,
            IRepository<FileTemplateConfiguration, Guid> templateRepository,
            IStoredFileService storedFileService,
            IRepository<StoredFile, Guid> storedFileRepo)
        {
            _entityRepository = entityRepository;
            _objectMapper = objectMapper;
            _templateRepository = templateRepository;
            _storedFileService = storedFileService;
            _storedFileRepo = storedFileRepo;
        }

        /// <summary>
        /// Generates and downloads a {DocumentName} Word document
        /// </summary>
        [HttpGet]
        public async Task<FileStreamResult> GenerateAndDownloadDocxAsync(Guid {entityParam}Id)
        {
            if ({entityParam}Id == Guid.Empty)
                throw new UserFriendlyException("Invalid {EntityName} ID.");

            // 1. Load entity
            var entity = await _entityRepository.GetAsync({entityParam}Id);

            // 2. Build DTO
            var dto = _objectMapper.Map<{DocumentName}PdfDto>(entity);

            // 3. Populate fields that require manual logic
            // dto.{ComputedField} = await Compute{Field}Async(entity);

            // 4. Populate repeating regions (if any)
            // var items = await Get{RegionName}ItemsAsync(entity);
            // dto.{RegionName} = DocumentProcessManager.GetDataTable(items, "{RegionName}");

            // 5. Resolve template and perform mail merge
            var document = await LoadTemplateAsync();
            ExecuteMailMerge(document, dto);

            // 6. Save as Word document
            using var memoryStream = new MemoryStream();
            document.Save(memoryStream, SaveFormat.Docx);
            memoryStream.Position = 0;

            var fileName = GenerateFileName(entity, ".docx");
            return new FileStreamResult(new MemoryStream(memoryStream.ToArray()),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            {
                FileDownloadName = fileName
            };
        }

        private async Task<Document> LoadTemplateAsync()
        {
            var config = await _templateRepository.FirstOrDefaultAsync(r => r.Name == TEMPLATE_NAME);
            if (config?.DocumentTemplate == null)
                throw new UserFriendlyException($"Template '{TEMPLATE_NAME}' not found.");

            var templateFile = await _storedFileRepo.GetAsync(config.DocumentTemplate.Id);
            using var templateStream = await _storedFileService.GetStreamAsync(templateFile.LastVersion());
            return new Document(templateStream);
        }

        private static void ExecuteMailMerge(Document document, object dto)
        {
            var properties = dto.GetType().GetProperties();
            var fieldNames = properties
                .Where(p => p.PropertyType != typeof(DataTable) && p.PropertyType != typeof(DataSet))
                .Select(p => p.Name).ToArray();
            var fieldValues = properties
                .Where(p => p.PropertyType != typeof(DataTable) && p.PropertyType != typeof(DataSet))
                .Select(p => p.GetValue(dto)).ToArray();

            document.MailMerge.CleanupOptions =
                MailMergeCleanupOptions.RemoveEmptyParagraphs |
                MailMergeCleanupOptions.RemoveUnusedFields |
                MailMergeCleanupOptions.RemoveUnusedRegions;

            // Simple field merge
            document.MailMerge.Execute(fieldNames, fieldValues);

            // Region merges for DataTable properties
            foreach (var prop in properties.Where(p => p.PropertyType == typeof(DataTable)))
            {
                var table = prop.GetValue(dto) as DataTable;
                if (table != null)
                    document.MailMerge.ExecuteWithRegions(table);
            }

            // DataSet merges for nested regions
            foreach (var prop in properties.Where(p => p.PropertyType == typeof(DataSet)))
            {
                var dataSet = prop.GetValue(dto) as DataSet;
                if (dataSet != null)
                    document.MailMerge.ExecuteWithRegions(dataSet);
            }
        }

        private static string GenerateFileName({EntityType} entity, string extension)
        {
            var identifier = entity.{IdentifierProperty}?.ToString() ?? "Unknown";
            var fileName = $"{DocumentName}_{identifier}_{DateTime.Now:yyyyMMdd}{extension}";
            return string.Join("_", fileName.Split(Path.GetInvalidFileNameChars()));
        }
    }
}
```

### Controller variant

For controllers, use the same `LoadTemplateAsync` and `ExecuteMailMerge` pattern but return `IActionResult`:

```csharp
[HttpGet("GenerateAndDownloadDocx")]
public async Task<IActionResult> GenerateAndDownloadDocxAsync(Guid {entityParam}Id)
{
    // ... load entity and build DTO (same as PDF variant) ...

    var document = await LoadTemplateAsync();
    ExecuteMailMerge(document, dto);

    using var memoryStream = new MemoryStream();
    document.Save(memoryStream, SaveFormat.Docx);
    var bytes = memoryStream.ToArray();

    var fileName = GenerateFileName(entity, ".docx");
    return File(bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        fileName);
}
```

### Guidance

- `DocumentProcessManager.GenerateAsync()` always outputs PDF. For Word output, use Aspose `Document` directly with `SaveFormat.Docx`.
- The `LoadTemplateAsync` method resolves the template from `FileTemplateConfiguration` the same way `DocumentProcessManager` does internally.
- The `ExecuteMailMerge` helper uses reflection to extract field names and values from the DTO, handling `DataTable` regions and `DataSet` nested regions automatically.
- For embedded resource templates, replace `LoadTemplateAsync` with `GetTemplate()` from `AsposeBuilderBase` (see SS4).
- When offering **both** PDF and Word endpoints, share the DTO-building and mail merge logic in private methods and only vary the final `document.Save(...)` call and content type.

---

## SS4 — Embedded Resource Template Variant

Use this when the Word template is bundled in the assembly as an embedded resource instead of being uploaded via the admin UI. This is useful for default/fallback templates or when templates should be version-controlled with the code.

### Setup

1. Add the `.docx` file to the project (e.g., `PdfDocuments/{DocumentName}/Templates/{TemplateName}.docx`)
2. Set Build Action to **Embedded Resource** in the `.csproj`:

```xml
<ItemGroup>
  <EmbeddedResource Include="PdfDocuments\{DocumentName}\Templates\{TemplateName}.docx" />
</ItemGroup>
```

3. Load using `AsposeBuilderBase.GetResourceTemplate()`:

### Template (inheriting AsposeBuilderBase)

```csharp
using Abp.Dependency;
using Aspose.Words;
using Microsoft.AspNetCore.Mvc;
using Shesha.Enterprise.DocumentProcessing;
using System;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;

namespace {Namespace}.PdfDocuments.{DocumentName}
{
    [Route("api/[controller]")]
    [ApiController]
    public class {DocumentName}Controller : AsposeBuilderBase, ITransientDependency
    {
        public {DocumentName}Controller() : base("{TemplateName}", null)
        {
        }

        [HttpGet("GenerateAndDownloadPdf")]
        public async Task<IActionResult> GenerateAndDownloadPdfAsync(Guid {entityParam}Id)
        {
            // GetTemplate tries StoredFile first, falls back to embedded resource
            var document = await GetTemplate();
            var builder = new DocumentBuilder(document);

            // Populate merge fields
            builder.Document.MailMerge.Execute(
                new[] { "{Field1}", "{Field2}" },
                new object[] { "Value1", "Value2" });

            // Save as PDF
            using var memoryStream = new MemoryStream();
            document.Save(memoryStream, Aspose.Words.SaveFormat.Pdf);
            var bytes = memoryStream.ToArray();

            return new FileContentResult(bytes, "application/pdf")
            {
                FileDownloadName = "{DocumentName}.pdf"
            };
        }
    }
}
```

### Guidance

- `GetTemplate()` (from `AsposeBuilderBase`) first tries to load by `TemplateFileId`, then falls back to `GetResourceTemplate()` which searches the assembly's embedded resources for a file matching the template name.
- The embedded resource name is the full namespace path with dots. Ensure the resource name matches what `GetResourceTemplate` expects.
- This approach is ideal for templates that are part of the codebase and should be version-controlled alongside the code.
- You can combine this with `FileTemplateConfiguration` — upload a template via admin UI to override the embedded default.

---

## SS6 — StoredFile Template Source (Direct Aspose)

Use this approach when the Word template is stored as a `StoredFile` on a domain entity (e.g., a configuration entity's template field) rather than in a `FileTemplateConfiguration` or embedded resource. Common for configurable document generation where administrators upload templates per workflow/config.

### Template

```csharp
using Abp.Dependency;
using Abp.Domain.Repositories;
using Aspose.Words;
using Aspose.Words.MailMerging;
using Castle.Core.Logging;
using Shesha.Services;
using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace {Namespace}.Services.{DocumentName}
{
    /// <summary>
    /// Generates documents from a Word template stored as a StoredFile on a domain entity,
    /// performs Aspose mail merge, and saves the result as a new StoredFile.
    /// </summary>
    public class {DocumentName}Generator : I{DocumentName}Generator, ITransientDependency
    {
        private readonly IStoredFileService _storedFileService;
        private readonly IRepository<{OwnerEntity}, Guid> _ownerRepository;
        private readonly IRepository<{DataEntity}, Guid> _dataRepository;

        public ILogger Logger { get; set; } = NullLogger.Instance;

        public {DocumentName}Generator(
            IStoredFileService storedFileService,
            IRepository<{OwnerEntity}, Guid> ownerRepository,
            IRepository<{DataEntity}, Guid> dataRepository)
        {
            _storedFileService = storedFileService;
            _ownerRepository = ownerRepository;
            _dataRepository = dataRepository;
        }

        public async Task GenerateAsync({OwnerEntity} owner)
        {
            if (owner == null)
                throw new ArgumentNullException(nameof(owner));

            // 1. Get template StoredFile from the entity/config
            var template = owner.{TemplateProperty}
                ?? throw new InvalidOperationException("No template configured.");

            // 2. Load template stream
            using var templateStream = await _storedFileService.GetStreamAsync(template);
            if (templateStream == null)
            {
                Logger.Warn($"Could not retrieve template stream. Skipping document generation.");
                return;
            }

            using var templateMemory = new MemoryStream();
            await templateStream.CopyToAsync(templateMemory);
            templateMemory.Position = 0;

            // 3. Build DTO and extract field names/values
            var dto = await BuildDtoAsync(owner);
            var fieldNames = dto.GetType().GetProperties().Select(p => p.Name).ToArray();
            var fieldValues = dto.GetType().GetProperties().Select(p => p.GetValue(dto) ?? "").ToArray();

            // 4. Open template, perform mail merge
            var document = new Document(templateMemory);

            document.MailMerge.CleanupOptions =
                MailMergeCleanupOptions.RemoveEmptyParagraphs
                | MailMergeCleanupOptions.RemoveUnusedFields
                | MailMergeCleanupOptions.RemoveUnusedRegions;

            document.MailMerge.Execute(fieldNames, fieldValues);

            // 5. Save as PDF
            using var pdfStream = new MemoryStream();
            document.Save(pdfStream, SaveFormat.Pdf);
            pdfStream.Position = 0;

            // 6. Persist as StoredFile
            var fileName = $"{DocumentName}_{DateTime.Now:yyyyMMdd}.pdf";
            var storedFile = await _storedFileService.SaveFileAsync(
                pdfStream,
                fileName,
                file => file.FileType = "application/pdf");

            // 7. Assign to entity and save
            owner.{OutputProperty} = storedFile;
            await _ownerRepository.UpdateAsync(owner);

            Logger.Info($"Generated document '{fileName}' for {OwnerEntity} {owner.Id}.");
        }

        private async Task<{DocumentName}PdfDto> BuildDtoAsync({OwnerEntity} owner)
        {
            var dto = new {DocumentName}PdfDto();
            // Populate DTO fields from owner and related entities
            // dto.{Field} = owner.{Property}?.ToString() ?? "";
            return dto;
        }
    }
}
```

### Interface

```csharp
using System.Threading.Tasks;

namespace {Namespace}.Services.{DocumentName}
{
    public interface I{DocumentName}Generator
    {
        Task GenerateAsync({OwnerEntity} owner);
    }
}
```

### Guidance

- Use `IStoredFileService.GetStreamAsync(StoredFile)` to load the template — returns `Task<Stream>` (can be null).
- Use `IStoredFileService.SaveFileAsync(Stream, string, Action<StoredFile>)` to persist the output — returns `Task<StoredFile>`.
- **Do not use** `CreateFileAsync` — the correct method is `SaveFileAsync`.
- Copy the template stream to a `MemoryStream` before passing to `new Document(stream)` — the original stream from `GetStreamAsync` may not be seekable.
- This pattern is ideal for configuration-driven document generation where templates vary by config record (e.g., different approval types each have their own template).
- The generator gracefully skips when no template is configured (returns without error), making it safe to call unconditionally.
- Register the interface via `ITransientDependency` for auto-discovery by ABP's IoC container.
