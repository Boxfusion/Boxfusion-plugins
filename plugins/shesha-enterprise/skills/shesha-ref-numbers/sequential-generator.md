# Sequential Reference Number Generator

## §1. Sequential Ref Number Usage

Inject `SequentialRefNumberGenerator` and call `Generate()` with a settings object.

```csharp
using Shesha.Enterprise.Domain.Service.RefNumberGenerator;
using Shesha.Workflow.RefNumberGenerator;

public class {ServiceName}AppService : SheshaAppServiceBase
{
    private readonly SequentialRefNumberGenerator _refNumberGenerator;

    public {ServiceName}AppService(SequentialRefNumberGenerator refNumberGenerator)
    {
        _refNumberGenerator = refNumberGenerator;
    }

    public string GetNext{EntityName}Number()
    {
        var settings = new SequentialRefNumberGeneratorSettings
        {
            SequenceName = "{EntityName}Numbers",
            RefNumberFormat = "{Prefix}-{FormatPlaceholders}",
            SequenceResetCycle = RefListSequenceResetCycle.{ResetCycle},
            // Include these based on chosen ResetCycle:
            // ResetMonth = RefListResetMonth.{Month},
            // ResetDayOfMonth = {Day},
            // ResetDay = RefListResetDay.{DayOfWeek},
            // Starting = {StartNumber},
            // FYStartMonth = RefListResetMonth.{Month},  // override global FY
        };

        return _refNumberGenerator.Generate(settings);
    }
}
```

**Settings properties:**

| Property | Required | Description |
|----------|----------|-------------|
| `SequenceName` | Yes | Unique counter name — each name gets its own independent counter |
| `RefNumberFormat` | Yes | Format string with `{0}` (date) and `{1}` (sequence) placeholders |
| `SequenceResetCycle` | Yes | When the counter resets (see SKILL.md quick reference) |
| `ResetMonth` | Conditional | Month to reset (for `EveryYear`) |
| `ResetDayOfMonth` | Conditional | Day of month to reset (for `EveryMonth`, `EveryYear`) |
| `ResetDay` | Conditional | Day of week to reset (for `EveryWeek`) |
| `Starting` | No | First number in sequence (default: `1`) |
| `FYStartMonth` | No | Override global financial year start month for this generator |

**Key rules:**
- `SequenceName` must be unique across the application — different entities need different names
- The generator is thread-safe; concurrent calls produce unique numbers
- Counters are database-backed and persist across restarts
- For financial year placeholders (`{FY}`, `{FY-1}`, etc.), ensure the `Financial Year End Month` setting is configured in Shesha admin, or set `FYStartMonth` explicitly

**Typical assignment pattern — set ref number on entity creation:**

```csharp
public async Task<{EntityName}> Create{EntityName}Async({EntityName}CreateDto input)
{
    var entity = ObjectMapper.Map<{EntityName}>(input);

    // Generate and assign the reference number
    entity.ReferenceNumber = GetNext{EntityName}Number();

    await _repository.InsertAsync(entity);
    return entity;
}
```

---

## §2. Generator Manager Usage

`IRefNumberGeneratorManager` looks up any registered generator by its identifier. This is how the workflow engine calls generators internally, and is useful when the generator type is determined at runtime.

```csharp
using Newtonsoft.Json;
using Shesha.Enterprise.Domain.Service.RefNumberGenerator;
using Shesha.Workflow.RefNumberGenerator;

public class {ServiceName}AppService : SheshaAppServiceBase
{
    private readonly IRefNumberGeneratorManager _refNumberManager;

    public {ServiceName}AppService(IRefNumberGeneratorManager refNumberManager)
    {
        _refNumberManager = refNumberManager;
    }

    public string CreateRefNumber()
    {
        var settingsJson = JsonConvert.SerializeObject(new SequentialRefNumberGeneratorSettings
        {
            SequenceName = "{EntityName}Numbers",
            RefNumberFormat = "{Prefix}-{FormatPlaceholders}",
            SequenceResetCycle = RefListSequenceResetCycle.{ResetCycle},
            ResetMonth = RefListResetMonth.{Month},
            ResetDayOfMonth = {Day}
        });

        // "sequential" is the built-in identifier for SequentialRefNumberGenerator
        return _refNumberManager.Generate("sequential", settingsJson);
    }

    public void ListAvailableGenerators()
    {
        var types = _refNumberManager.GeneratorTypes;
        foreach (var gen in types)
        {
            // gen.Uid = identifier, gen.Label = display name
        }
    }
}
```

**Key rules:**
- Use the manager when the generator type is dynamic or configured externally
- The built-in sequential generator identifier is `"sequential"`
- Settings must be serialized to JSON when using the manager
- Custom generators are automatically discovered and available via their `[ClassUid]` value
