# Framework Path — Shesha.Testing Available

Use this path when the project has access to `Shesha.Testing` (NuGet package or project reference).

## Table of Contents
- [What Shesha.Testing Provides](#what-sheshatesting-provides)
- [csproj](#csproj)
- [Test Module (simplified)](#test-module-simplified)
- [Collection Definition](#collection-definition-required--must-be-in-test-assembly)
- [SheshaNhTestBase Convenience Class](#sheshanhtestbase-convenience-class)
- [Files to Create](#files-to-create-framework-path)

## What Shesha.Testing Provides

- `ShaIntegratedTestBase<T>` — ABP test base with IoC, UOW, session management
- `SheshaNhTestBase<T>` — NHibernate session helpers, login helpers, UsingDbSession
- `TestWebHostEnvironment` — Concrete `IWebHostEnvironment` for tests
- `UnitTestHelper` — `MockWebHostEnvironment()`, `RegisterFakeService<T>()`, `MockApiExplorer()`
- `SheshaTestModuleHelper` — `ConfigureForTesting()` extension method
- `ServiceCollectionRegistrar` — Identity bridge for Castle Windsor
- `IDatabaseFixture`, `LocalSqlServerFixture`, `SqlServerFixture`, `PostgreSqlFixture`
- Collection definitions (though you still need local ones — see below)

## csproj

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <IsPackable>false</IsPackable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Shesha.Testing" Version="$(SheshaVersion)" />
    <PackageReference Include="Abp.Castle.Log4Net" Version="9.0.0" />
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.8.0" />
    <PackageReference Include="Shouldly" Version="4.2.1" />
    <PackageReference Include="xunit" Version="2.6.3" />
    <PackageReference Include="xunit.extensibility.execution" Version="2.6.3" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.5.5">
      <PrivateAssets>all</PrivateAssets>
      <IncludeAssets>runtime; build; native; contentfiles; analyzers</IncludeAssets>
    </PackageReference>
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\..\src\{Product}.Domain\{Product}.Domain.csproj" />
    <ProjectReference Include="..\..\src\{Product}.Application\{Product}.Application.csproj" />
  </ItemGroup>
  <ItemGroup>
    <None Update="appsettings.Test.json">
      <CopyToOutputDirectory>Always</CopyToOutputDirectory>
    </None>
    <None Update="log4net.config">
      <CopyToOutputDirectory>Always</CopyToOutputDirectory>
    </None>
  </ItemGroup>
</Project>
```

Note: `Shesha.Testing` transitively brings `Abp.TestBase`, `NSubstitute`, `Moq`, `Testcontainers`, etc.

## Test Module (simplified)

```csharp
using Abp;
using Abp.AspNetCore;
using Abp.Castle.Logging.Log4Net;
using Abp.Modules;
using Abp.TestBase;
using Castle.Facilities.Logging;
using Shesha.Modules;
using Shesha.NHibernate;
using Shesha.Testing;
using Shesha.Workflow;
using {Product}.Application;
using {Product}.Domain;
using System.Reflection;

namespace {Product}.Common.Tests
{
    [DependsOn(
        typeof({Product}ApplicationModule),
        typeof({Product}Module),
        typeof(AbpKernelModule),
        typeof(AbpTestBaseModule),
        typeof(AbpAspNetCoreModule),
        typeof(SheshaApplicationModule),
        typeof(SheshaNHibernateModule),
        typeof(SheshaFrameworkModule),
        typeof(SheshaWorkflowModule)
    )]
    public class {Product}CommonDomainTestModule : SheshaModule
    {
        public const string ModuleName = "{Product}.Tests";
        public override SheshaModuleInfo ModuleInfo => new SheshaModuleInfo(ModuleName)
        {
            FriendlyName = "{Product} Tests",
            Publisher = "Boxfusion",
            Alias = "{productAlias}Tests"
        };

        public {Product}CommonDomainTestModule(SheshaNHibernateModule nhModule, SheshaFrameworkModule frwkModule)
        {
            nhModule.SkipDbSeed = true;
            frwkModule.SkipAppWarmUp = true;
        }

        public override void PreInitialize()
        {
            this.ConfigureForTesting(IocManager);
        }

        public override void Initialize()
        {
            var thisAssembly = Assembly.GetExecutingAssembly();
            IocManager.RegisterAssemblyByConvention(thisAssembly);

            IocManager.IocContainer.AddFacility<LoggingFacility>(
                f => f.UseAbpLog4Net().WithConfig("log4net.config"));
        }
    }
}
```

That's it. `ConfigureForTesting(IocManager)` handles all the boilerplate: web host environment mock, API explorer mock, IConfiguration, NHibernate DBMS config, UOW settings, AutoMapper, background jobs, email sender, etc.

## Collection Definition (REQUIRED — must be in test assembly)

xUnit requires `[CollectionDefinition]` classes in the **same assembly** as tests. Even though `Shesha.Testing` has them, you need local ones:

```csharp
// Fixtures/LocalSqlServerCollection.cs
using Shesha.Testing.Fixtures;
using Xunit;

namespace {Product}.Common.Tests.Fixtures
{
    [CollectionDefinition(Name)]
    public class LocalSqlServerCollection : ICollectionFixture<LocalSqlServerFixture>
    {
        public const string Name = "LocalSqlServer";
    }
}
```

## SheshaNhTestBase Convenience Class

```csharp
using Shesha.Testing;
using Shesha.Testing.Fixtures;

namespace {Product}.Common.Tests
{
    public abstract class SheshaNhTestBase : SheshaNhTestBase<{Product}CommonDomainTestModule>
    {
        protected SheshaNhTestBase(IDatabaseFixture fixture) : base(fixture) { }
    }
}
```

## Files to Create (Framework Path)

| File | Purpose |
|------|---------|
| `{Product}.Common.Domain.Tests.csproj` | Project file with Shesha.Testing reference |
| `appsettings.Test.json` | DB connection config |
| `log4net.config` | Logging (copy from any Shesha project) |
| `{Product}CommonDomainTestModule.cs` | Module with `ConfigureForTesting()` |
| `SheshaNhTestBase.cs` | Thin convenience base class |
| `Fixtures/LocalSqlServerCollection.cs` | xUnit collection definition |
| `*_Tests.cs` | Actual test classes |
