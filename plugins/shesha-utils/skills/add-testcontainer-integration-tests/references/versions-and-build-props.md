# Versions and Directory.Build.props

## How versions flow

`backend/Directory.Build.props` is imported by every csproj under `backend/`. It holds the version properties; csproj files only reference them.

Reference (`pd-content`):

```xml
<Project>
  <PropertyGroup>
    <SheshaVersion>0.43.36</SheshaVersion>
    <SheshaEnterpriseVersion>5.1.6</SheshaEnterpriseVersion>
    <TestingFrameworkVersion>0.0.0-build112614</TestingFrameworkVersion>
  </PropertyGroup>
</Project>
```

```xml
<PackageReference Include="Boxfusion.Common.Tests.TestingFramework" Version="$(TestingFrameworkVersion)" />
```

## Rules

1. **Never hardcode** the TestingFramework version in a csproj. Always `$(TestingFrameworkVersion)`.
2. **Add, don't replace.** If `Directory.Build.props` exists, insert `<TestingFrameworkVersion>` into its existing `<PropertyGroup>` beside `SheshaVersion`. Leave every other property and its formatting alone. If the file has `Choose`/`When` blocks (e.g. `UseLocal*` debug toggles), put the property in the unconditional `PropertyGroup`.
3. **Reuse an existing value.** If the repo already defines `TestingFrameworkVersion`, keep it — do not bump it as a side effect.
4. **Default value** when the repo has none: `0.0.0-build85915`. pd-content's props say `build112614`, but that build is not on the feed. NuGet compares prerelease labels as text, so `build85915` sorts above `build112614` and is what restore actually picks (warning NU1603). `build85915` is the build the pd-content suite really runs green on; pin it exactly so there is no NU1603 fallback.
5. **Compatibility.** The package depends on `Shesha.Framework` 0.43.x, so it suits projects on Shesha 0.43/0.44. If `SheshaVersion` is outside that range, stop and tell the user a matching TestingFramework build is needed — do not guess a build number.
6. **Feed.** The package is on `nuget.shesha.dev` (`https://pkgs.dev.azure.com/boxfusion/_packaging/nuget.shesha.dev/nuget/v3/index.json`). Confirm `backend/.nuget/NuGet.Config` (or the repo's NuGet.Config) lists it. The feed needs Azure DevOps credentials; a 401 on restore means the user must authenticate (credential provider / `dotnet restore --interactive`), not that the version is wrong.
7. **Verify** with `dotnet restore <test csproj>`. A `NU1102 Unable to find package` means the build number is not on the feed — ask the user for a valid one. A `NU1603 ... was resolved instead` means the same thing, but restore silently picked another build; set the property to the resolved version. Local cache check: `ls ~/.nuget/packages/boxfusion.common.tests.testingframework/`.
8. **Lock files.** If src projects set `RestorePackagesWithLockFile`, the new test project does not need to; do not add the property or commit a lock file for it unless the repo's other test projects have one.

## Package set for the test project

Keep these versions identical across projects so every repo runs the same stack (they match `assets/Tests.Integration.csproj.template`):

| Package | Version | Why |
|---|---|---|
| Boxfusion.Common.Tests.TestingFramework | `$(TestingFrameworkVersion)` | HTTP helpers, DB reset (Respawn) |
| Testcontainers / Testcontainers.MsSql | 3.10.0 | SQL Server container |
| Microsoft.AspNetCore.Mvc.Testing | 8.0.10 | `TestServer` |
| Microsoft.NET.Test.Sdk | 17.8.0 | |
| xunit / xunit.runner.visualstudio | 2.5.3 | |
| coverlet.collector | 6.0.0 | CI code coverage |
| AsyncFixer | 1.6.0 | analyzer (private) |
| IDisposableAnalyzers | 4.0.8 | analyzer (private) |
| Microsoft.VisualStudio.Threading.Analyzers | 17.13.2 | analyzer (private) |
| Intent.RoslynWeaver.Attributes | 2.1.4 | only if the solution uses Intent Architect (`grep -r RoslynWeaver --include=*.csproj src`); otherwise drop it |

If the repo already pins a different version of an analyzer or xunit in its other test projects, use the repo's version instead so the solution stays consistent.

Shesha packages are not referenced directly — they come transitively through the Web.Host/Web.Core project references, so the test project always runs the same `SheshaVersion` as the app.
