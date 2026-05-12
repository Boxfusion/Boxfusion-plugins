# Custom Reference Number Generator

## §1. Custom Generator Class

Create a custom generator only when sequential numbering doesn't fit (e.g. random IDs, hash-based references, external system lookups).

**File:** `{GeneratorName}RefNumberGenerator.cs` in `Services/RefNumberGenerators/` (Application project)

```csharp
using Abp.Dependency;
using Shesha.Attributes;
using Shesha.Domain;
using Shesha.Enterprise.Domain.Service.RefNumberGenerator;
using System;
using System.ComponentModel.DataAnnotations;

namespace {ModuleNamespace}.Application.Services.RefNumberGenerators
{
    [Display(Name = "{Display Name}")]
    [ClassUid("{generator-uid}")]
    public class {GeneratorName}RefNumberGenerator : IRefNumberGenerator, ITransientDependency
    {
        /// <summary>
        /// Set to true if this generator accepts configuration via settings JSON.
        /// </summary>
        public bool HasParameters => {hasParameters};

        /// <summary>
        /// Optional: a Shesha form for configuring settings in the UI designer.
        /// Return null if no configuration form is needed.
        /// </summary>
        public FormIdentifier? ParametersForm => {parametersForm};

        public string Generate(string? settingsJson)
        {
            // Parse settings if HasParameters is true:
            // var settings = JsonConvert.DeserializeObject<{SettingsClass}>(settingsJson);

            // Generate and return the reference number
            {GenerationLogic}
        }
    }
}
```

**The IRefNumberGenerator interface:**

```csharp
public interface IRefNumberGenerator
{
    bool HasParameters { get; }
    FormIdentifier? ParametersForm { get; }
    string Generate(string? settingsJson);
}
```

**Auto-discovery requirements — the generator is automatically registered if it:**
- Implements `IRefNumberGenerator`
- Is public and not abstract
- Implements `ITransientDependency` (registers in IoC container)
- Has a `[ClassUid("identifier")]` attribute

**Key rules:**
- `[ClassUid]` value is the identifier used to call this generator via `IRefNumberGeneratorManager.Generate(uid, settings)`
- `[Display(Name)]` sets the friendly name shown in the workflow designer and generator listings
- Implement `ITransientDependency` — the IoC container must be able to resolve the class
- If `HasParameters` is true, provide a `ParametersForm` pointing to a Shesha configurable form for UI-based configuration
- If `HasParameters` is false, set `ParametersForm` to `null`
- Settings arrive as a JSON string — deserialize to a custom class if needed

**Example — parameterless random generator:**

```csharp
[Display(Name = "Random Reference Number Generator")]
[ClassUid("random")]
public class RandomRefNumberGenerator : IRefNumberGenerator, ITransientDependency
{
    public bool HasParameters => false;
    public FormIdentifier? ParametersForm => null;

    public string Generate(string? settingsJson)
    {
        var guid = Guid.NewGuid().ToString("N")[..8].ToUpperInvariant();
        return $"REF-{guid}";
        // Returns: REF-A1B2C3D4
    }
}
```

**Example — parameterized generator with custom settings:**

```csharp
public class {GeneratorName}Settings
{
    public string Prefix { get; set; }
    public int Length { get; set; }
}

[Display(Name = "{Display Name}")]
[ClassUid("{generator-uid}")]
public class {GeneratorName}RefNumberGenerator : IRefNumberGenerator, ITransientDependency
{
    public bool HasParameters => true;
    public FormIdentifier? ParametersForm => new FormIdentifier("{module}", "{form-name}");

    public string Generate(string? settingsJson)
    {
        var settings = JsonConvert.DeserializeObject<{GeneratorName}Settings>(settingsJson)
            ?? throw new UserFriendlyException("Settings are required for this generator.");

        // Use settings.Prefix, settings.Length, etc.
        return $"{settings.Prefix}-{Guid.NewGuid().ToString("N")[..settings.Length].ToUpperInvariant()}";
    }
}
```

**Calling the custom generator:**

```csharp
// Via IRefNumberGeneratorManager
_refNumberManager.Generate("{generator-uid}", settingsJson);
```
