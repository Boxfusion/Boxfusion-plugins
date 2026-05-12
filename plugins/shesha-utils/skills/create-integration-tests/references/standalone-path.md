# Standalone Path — No Shesha.Testing Package

Use this path when the project uses an older Shesha framework version without the `Shesha.Testing` NuGet package.

## Table of Contents
- [csproj](#csproj)
- [Fixtures/IDatabaseFixture.cs](#1-fixtureidatabasefixturecs)
- [Fixtures/LocalSqlServerFixture.cs](#2-fixtureslocalSqlServerfixturecs)
- [Fixtures/LocalSqlServerCollection.cs](#3-fixtureslocalSqlServercollectioncs)
- [TestWebHostEnvironment.cs](#4-testwebhostenvironmentcs)
- [UnitTestHelper.cs](#5-unittesthelpercs)
- [SafeSheshaNHibernateInterceptor.cs](#6-safesheshanhibernateinterceptorcs)
- [DependencyInjection/ServiceCollectionRegistrar.cs](#7-dependencyinjectionservicecollectionregistrarcs)
- [ShaIntegratedTestBase.cs](#8-shaintegratedtestbasecs)
- [SheshaNhTestBase.cs](#9-sheshanhtestbasecs)
- [Test Module (Full Standalone)](#10-test-module-full-standalone)
- [Files Summary](#files-to-create-standalone-path)
- [Hangfire Note](#hangfire-note)

## Overview

You must scaffold all test infrastructure locally in the test project. This includes base classes, fixtures, helpers, interceptor workaround, and the full test module configuration.

## csproj

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <IsPackable>false</IsPackable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Abp.Castle.Log4Net" Version="9.0.0" />
    <PackageReference Include="Abp.TestBase" Version="9.0.0" />
    <PackageReference Include="Hangfire.SqlServer" Version="1.8.6" />
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.8.0" />
    <PackageReference Include="Moq" Version="4.20.70" />
    <PackageReference Include="NSubstitute" Version="5.1.0" />
    <PackageReference Include="Shouldly" Version="4.2.1" />
    <PackageReference Include="System.Data.SQLite.Core" Version="1.0.118" />
    <PackageReference Include="xunit" Version="2.6.3" />
    <PackageReference Include="xunit.extensibility.execution" Version="2.6.3" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.5.5">
      <PrivateAssets>all</PrivateAssets>
      <IncludeAssets>runtime; build; native; contentfiles; analyzers</IncludeAssets>
    </PackageReference>
    <PackageReference Include="Shesha.Application" Version="$(SheshaVersion)" />
    <PackageReference Include="Shesha.Core" Version="$(SheshaVersion)" />
    <PackageReference Include="Shesha.Framework" Version="$(SheshaVersion)" />
    <PackageReference Include="Shesha.NHibernate" Version="$(SheshaVersion)" />
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

## Infrastructure Files to Create

### 1. Fixtures/IDatabaseFixture.cs

```csharp
namespace {Product}.Common.Tests.Fixtures
{
    public interface IDatabaseFixture
    {
        string ConnectionString { get; }
        DbmsType DbmsType { get; }
    }
}
```

Note: `DbmsType` is from `Shesha` namespace (available via Shesha.Application).

### 2. Fixtures/LocalSqlServerFixture.cs

```csharp
using Microsoft.Extensions.Configuration;
using System.Threading.Tasks;
using Xunit;

namespace {Product}.Common.Tests.Fixtures
{
    public class LocalSqlServerFixture : IDatabaseFixture, IAsyncLifetime
    {
        public string ConnectionString { get; private set; }
        public DbmsType DbmsType { get; private set; } = DbmsType.SQLServer;

        public Task InitializeAsync()
        {
            var config = new ConfigurationBuilder().AddJsonFile("appsettings.Test.json").Build();
            DbmsType = config.GetDbmsType();
            ConnectionString = config.GetRequiredConnectionString("TestDB");
            return Task.CompletedTask;
        }

        public Task DisposeAsync() => Task.CompletedTask;
    }
}
```

### 3. Fixtures/LocalSqlServerCollection.cs

```csharp
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

### 4. TestWebHostEnvironment.cs

```csharp
using System;
using System.IO;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.FileProviders;

namespace {Product}.Common.Tests
{
    public class TestWebHostEnvironment : IWebHostEnvironment
    {
        public string ApplicationName { get; set; } = "Test Application";
        public string WebRootPath { get; set; } = Path.Combine(Environment.CurrentDirectory, "wwwroot");
        public string EnvironmentName { get; set; } = "Test";
        public string ContentRootPath { get; set; } = Environment.CurrentDirectory;
        public IFileProvider ContentRootFileProvider
        {
            get => throw new NotImplementedException();
            set => throw new NotImplementedException();
        }
        public IFileProvider WebRootFileProvider
        {
            get => throw new NotImplementedException();
            set => throw new NotImplementedException();
        }
    }
}
```

### 5. UnitTestHelper.cs

```csharp
using Abp.Dependency;
using Castle.MicroKernel.Registration;
using Microsoft.AspNetCore.Mvc.Abstractions;
using Microsoft.AspNetCore.Mvc.ApiExplorer;
using Microsoft.AspNetCore.Mvc.Infrastructure;
using Moq;
using NSubstitute;
using Swashbuckle.AspNetCore.Swagger;
using Swashbuckle.AspNetCore.SwaggerGen;
using System.Collections.Generic;

namespace {Product}.Common.Tests
{
    public static class UnitTestHelper
    {
        public static void RegisterFakeService<TService>(this IIocManager iocManager) where TService : class
        {
            iocManager.IocContainer.Register(
                Component.For<TService>()
                    .UsingFactoryMethod(() => Substitute.For<TService>())
                    .LifestyleSingleton()
            );
        }

        public static void MockApiExplorer(this IIocManager iocManager)
        {
            var adcpMock = new Mock<IActionDescriptorCollectionProvider>();
            adcpMock.Setup(m => m.ActionDescriptors)
                .Returns(new ActionDescriptorCollection(new List<ActionDescriptor>(), 0));
            iocManager.IocContainer.Register(
                Component.For<IActionDescriptorCollectionProvider>()
                    .Instance(adcpMock.Object).LifestyleSingleton());

            var apiMock = new Mock<IApiDescriptionGroupCollectionProvider>();
            apiMock.Setup(m => m.ApiDescriptionGroups)
                .Returns(new ApiDescriptionGroupCollection(new List<ApiDescriptionGroup>(), 1));
            iocManager.IocContainer.Register(
                Component.For<IApiDescriptionGroupCollectionProvider>()
                    .Instance(apiMock.Object).LifestyleSingleton());

            iocManager.IocContainer.Register(
                Component.For<ISwaggerProvider>()
                    .Instance(new Mock<ISwaggerProvider>().Object).LifestyleSingleton());
            iocManager.IocContainer.Register(
                Component.For<ISchemaGenerator>()
                    .Instance(new Mock<ISchemaGenerator>().Object).LifestyleSingleton());
        }
    }
}
```

### 6. SafeSheshaNHibernateInterceptor.cs

This workaround is needed because older framework versions have two bugs in `SheshaNHibernateInterceptor`:
1. Null `previousState` in `OnFlushDirty` causes NRE during soft-delete detection
2. Null `EntityChangeEventHelper` before property injection runs

```csharp
using Abp.Dependency;
using Abp.Events.Bus.Entities;
using Shesha.NHibernate.Interceptors;

namespace {Product}.Common.Tests
{
    internal class SafeSheshaNHibernateInterceptor : SheshaNHibernateInterceptor
    {
        public SafeSheshaNHibernateInterceptor(IIocManager iocManager)
            : base(iocManager)
        {
            EntityChangeEventHelper = NullEntityChangeEventHelper.Instance;
        }

        public override bool OnFlushDirty(
            object entity, object id,
            object[] currentState, object[] previousState,
            string[] propertyNames,
            global::NHibernate.Type.IType[] types)
        {
            if (previousState == null)
            {
                previousState = (object[])currentState.Clone();
                for (int i = 0; i < propertyNames.Length; i++)
                {
                    if (propertyNames[i] == "IsDeleted")
                    {
                        previousState[i] = false;
                        break;
                    }
                }
            }
            return base.OnFlushDirty(entity, id, currentState, previousState, propertyNames, types);
        }
    }
}
```

### 7. DependencyInjection/ServiceCollectionRegistrar.cs

```csharp
using Abp.Dependency;
using Castle.Windsor.MsDependencyInjection;
using Microsoft.Extensions.DependencyInjection;
using Shesha.Identity;
using Shesha.Notifications;
using Shesha.Notifications.SMS;

namespace {Product}.Tests.DependencyInjection
{
    public static class ServiceCollectionRegistrar
    {
        public static void Register(IIocManager iocManager)
        {
            var services = new ServiceCollection();
            IdentityRegistrar.Register(services);

            // Register notification channel senders (same as Web.Host Startup)
            // Required if code under test sends notifications (e.g. approval workflows)
            services.AddTransient<INotificationChannelSender, EmailChannelSender>();
            services.AddTransient<INotificationChannelSender, SmsChannelSender>();

            WindsorRegistrationHelper.CreateServiceProvider(iocManager.IocContainer, services);
        }
    }
}
```

### 8. ShaIntegratedTestBase.cs

```csharp
using Abp;
using Abp.Dependency;
using Abp.Domain.Uow;
using Abp.Modules;
using Abp.Runtime.Session;
using Abp.TestBase.Runtime.Session;
using Castle.MicroKernel.Registration;
using {Product}.Common.Tests.Fixtures;
using Shesha.Services;
using System;
using System.Reflection;
using System.Threading.Tasks;

namespace {Product}.Common.Tests
{
    public abstract class ShaIntegratedTestBase<TStartupModule> : IDisposable
        where TStartupModule : AbpModule
    {
        private readonly IIocManager? _ownIocManager;
        private readonly IIocManager? _externalIocManager;

        protected IIocManager LocalIocManager => _externalIocManager ?? _ownIocManager
            ?? throw new Exception($"Failed to get IocManager.");

        protected AbpBootstrapper AbpBootstrapper { get; }
        protected TestAbpSession AbpSession { get; private set; }

        protected ShaIntegratedTestBase(IDatabaseFixture databaseFixture,
            bool initializeAbp = true, IIocManager? localIocManager = null)
        {
            _externalIocManager = localIocManager;
            if (localIocManager == null)
                _ownIocManager = new IocManager();
            StaticContext.SetIocManager(LocalIocManager);

            LocalIocManager.IocContainer.Register(
                Component.For<IDatabaseFixture>().Instance(databaseFixture));

            AbpBootstrapper = AbpBootstrapper.Create<TStartupModule>(options =>
            {
                options.IocManager = LocalIocManager;
            });

            if (initializeAbp) InitializeAbp();
        }

        protected void InitializeAbp()
        {
            LocalIocManager.RegisterIfNot<IAbpSession, TestAbpSession>();
            PreInitialize();
            AbpBootstrapper.Initialize();
            PostInitialize();
            AbpSession = LocalIocManager.Resolve<TestAbpSession>();
        }

        protected virtual void PreInitialize() { }
        protected virtual void PostInitialize() { }

        public virtual void Dispose()
        {
            AbpBootstrapper.Dispose();
            _ownIocManager?.Dispose();
        }

        protected T Resolve<T>()
        {
            EnsureClassRegistered(typeof(T));
            return LocalIocManager.Resolve<T>();
        }

        protected T Resolve<T>(object argumentsAsAnonymousType)
        {
            EnsureClassRegistered(typeof(T));
            return LocalIocManager.Resolve<T>(argumentsAsAnonymousType);
        }

        protected object Resolve(Type type)
        {
            EnsureClassRegistered(type);
            return LocalIocManager.Resolve(type);
        }

        protected object Resolve(Type type, object argumentsAsAnonymousType)
        {
            EnsureClassRegistered(type);
            return LocalIocManager.Resolve(type, argumentsAsAnonymousType);
        }

        protected void EnsureClassRegistered(Type type,
            DependencyLifeStyle lifeStyle = DependencyLifeStyle.Transient)
        {
            if (!LocalIocManager.IsRegistered(type))
            {
                if (!type.GetTypeInfo().IsClass || type.GetTypeInfo().IsAbstract)
                    throw new AbpException("Can not register " + type.Name +
                        ". It should be a non-abstract class.");
                LocalIocManager.Register(type, lifeStyle);
            }
        }

        protected virtual void WithUnitOfWork(Action action, UnitOfWorkOptions? options = null)
        {
            using var uowManager = LocalIocManager.ResolveAsDisposable<IUnitOfWorkManager>();
            using var uow = uowManager.Object.Begin(options ?? new UnitOfWorkOptions());
            action();
            uow.Complete();
        }

        protected virtual async Task WithUnitOfWorkAsync(Func<Task> action, UnitOfWorkOptions? options = null)
        {
            using var uowManager = LocalIocManager.ResolveAsDisposable<IUnitOfWorkManager>();
            using var uow = uowManager.Object.Begin(options ?? new UnitOfWorkOptions());
            await action();
            await uow.CompleteAsync();
        }
    }
}
```

### 9. SheshaNhTestBase.cs

```csharp
using Abp;
using Abp.Authorization.Users;
using Abp.Dependency;
using Abp.Domain.Uow;
using Abp.Modules;
using Abp.MultiTenancy;
using Abp.Runtime.Session;
using NHibernate;
using NHibernate.Linq;
using Shesha.Authorization.Users;
using Shesha.Domain;
using Shesha.MultiTenancy;
using Shesha.NHibernate.UoW;
using {Product}.Common.Tests.Fixtures;
using System;
using System.Linq;
using System.Threading.Tasks;

namespace {Product}.Common.Tests
{
    public abstract class SheshaNhTestBase<TStartupModule> : ShaIntegratedTestBase<TStartupModule>
        where TStartupModule : AbpModule
    {
        protected SheshaNhTestBase(IDatabaseFixture fixture) : base(fixture)
        {
            LoginAsHostAdmin();
            EntityHelper.RefreshStore(LocalIocManager);
        }

        #region UsingDbSession

        protected IDisposable UsingTenantId(int? tenantId)
        {
            var prev = AbpSession.TenantId;
            AbpSession.TenantId = tenantId;
            return new DisposeAction(() => AbpSession.TenantId = prev);
        }

        protected void UsingDbSession(Action<ISession> action) =>
            UsingDbSession(AbpSession.TenantId, action);

        protected T UsingDbSession<T>(Func<ISession, T> func) =>
            UsingDbSession(AbpSession.TenantId, func);

        protected Task UsingDbSessionAsync(Func<ISession, Task> action) =>
            UsingDbSessionAsync(AbpSession.TenantId, action);

        protected Task<T> UsingDbSessionAsync<T>(Func<ISession, Task<T>> func) =>
            UsingDbSessionAsync(AbpSession.TenantId, func);

        protected void UsingDbSession(int? tenantId, Action<ISession> action)
        {
            using (UsingTenantId(tenantId))
            using (var session = OpenSession())
                action(session);
        }

        protected T UsingDbSession<T>(int? tenantId, Func<ISession, T> func)
        {
            using (UsingTenantId(tenantId))
            using (var session = OpenSession())
            {
                var result = func(session);
                session.Flush();
                return result;
            }
        }

        protected async Task UsingDbSessionAsync(int? tenantId, Func<ISession, Task> action)
        {
            using (UsingTenantId(tenantId))
            using (var session = OpenSession())
            {
                await action(session);
                await session.FlushAsync();
            }
        }

        protected async Task<T> UsingDbSessionAsync<T>(int? tenantId, Func<ISession, Task<T>> func)
        {
            using (UsingTenantId(tenantId))
            using (var session = OpenSession())
            {
                var result = await func(session);
                await session.FlushAsync();
                return result;
            }
        }

        private ISession OpenSession() =>
            LocalIocManager.Resolve<ISessionFactory>().OpenSession();

        #endregion

        #region Login

        protected void LoginAsHostAdmin() => LoginAsHost(AbpUserBase.AdminUserName);

        protected void LoginAsHost(string userName)
        {
            AbpSession.TenantId = null;
            var user = UsingDbSession(s =>
                s.Query<User>().FirstOrDefault(u =>
                    u.TenantId == AbpSession.TenantId && u.UserName == userName));
            if (user == null)
                throw new Exception("There is no user: " + userName + " for host.");
            AbpSession.UserId = user.Id;
        }

        protected void LoginAsTenant(string tenancyName, string userName)
        {
            var tenant = UsingDbSession(s =>
                s.Query<Tenant>().FirstOrDefault(t => t.TenancyName == tenancyName));
            if (tenant == null)
                throw new Exception("There is no tenant: " + tenancyName);
            AbpSession.TenantId = tenant.Id;
            var user = UsingDbSession(s =>
                s.Query<User>().FirstOrDefault(u =>
                    u.TenantId == AbpSession.TenantId && u.UserName == userName));
            if (user == null)
                throw new Exception("There is no user: " + userName + " for tenant: " + tenancyName);
            AbpSession.UserId = user.Id;
        }

        #endregion

        protected NhUnitOfWork NewNhUnitOfWork()
        {
            var uowManager = Resolve<IUnitOfWorkManager>();
            return uowManager.Begin() is NhUnitOfWork nhuow
                ? nhuow
                : throw new Exception($"Unexpected UOW type. Expected '{nameof(NhUnitOfWork)}'");
        }

        protected virtual async Task<TResult> WithUnitOfWorkAsync<TResult>(
            Func<Task<TResult>> action, UnitOfWorkOptions? options = null)
        {
            using var uowManager = LocalIocManager.ResolveAsDisposable<IUnitOfWorkManager>();
            using var uow = uowManager.Object.Begin(options ?? new UnitOfWorkOptions());
            var result = await action();
            await uow.CompleteAsync();
            return result;
        }
    }

    // Non-generic convenience class — bind to project's test module
    public abstract class SheshaNhTestBase : SheshaNhTestBase<{Product}CommonDomainTestModule>
    {
        protected SheshaNhTestBase(IDatabaseFixture fixture) : base(fixture) { }
    }
}
```

### 10. Test Module (Full Standalone)

```csharp
using Abp;
using Abp.AspNetCore;
using Abp.AspNetCore.Configuration;
using Abp.AutoMapper;
using Abp.Castle.Logging.Log4Net;
using Abp.Configuration.Startup;
using Abp.Dependency;
using Abp.Domain.Uow;
using Abp.Events.Bus.Entities;
using Abp.Modules;
using Abp.Net.Mail;
using Abp.TestBase;
using Abp.Zero.Configuration;
using Castle.Facilities.Logging;
using Castle.MicroKernel.Registration;
using Hangfire;
using Hangfire.SqlServer;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.ApplicationParts;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Hosting;
using Moq;
using Shesha.Configuration.Startup;
using Shesha.FluentMigrator;
using Shesha.Modules;
using Shesha.NHibernate;
using Shesha.Workflow;
using {Product}.Application;
using {Product}.Common.Tests.Fixtures;
using {Product}.Domain;
using {Product}.Tests.DependencyInjection;
using Shesha.Services;
using System;
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
            // --- Register services FIRST ---

            if (!IocManager.IsRegistered<IWebHostEnvironment>())
                IocManager.IocContainer.Register(
                    Component.For<IWebHostEnvironment>()
                        .ImplementedBy<TestWebHostEnvironment>()
                        .LifestyleSingleton());

            if (!IocManager.IsRegistered<IAbpAspNetCoreConfiguration>())
                IocManager.IocContainer.Register(
                    Component.For<IAbpAspNetCoreConfiguration>()
                        .ImplementedBy<AbpAspNetCoreConfiguration>()
                        .LifestyleSingleton());

            if (!IocManager.IsRegistered<IHostApplicationLifetime>())
            {
                var mock = new Mock<IHostApplicationLifetime>();
                IocManager.IocContainer.Register(
                    Component.For<IHostApplicationLifetime>()
                        .Instance(mock.Object).LifestyleSingleton());
            }

            var testConfig = new ConfigurationBuilder()
                .AddJsonFile("appsettings.Test.json").Build();
            IocManager.IocContainer.Register(
                Component.For<IConfiguration>()
                    .Instance(testConfig)
                    .Named("test-configuration")
                    .IsDefault()
                    .LifestyleSingleton());

            IocManager.MockApiExplorer();

            // Interceptor workaround for older framework versions
            if (!IocManager.IsRegistered<IEntityChangeEventHelper>())
                IocManager.IocContainer.Register(
                    Component.For<IEntityChangeEventHelper>()
                        .Instance(NullEntityChangeEventHelper.Instance)
                        .LifestyleSingleton());

            IocManager.IocContainer.Register(
                Component.For<global::NHibernate.IInterceptor>()
                    .ImplementedBy<SafeSheshaNHibernateInterceptor>()
                    .IsDefault()
                    .LifestyleTransient());

            // --- Configure NHibernate ---
            var nhConfig = Configuration.Modules.ShaNHibernate();

            var dbFixture = IocManager.IsRegistered<IDatabaseFixture>()
                ? IocManager.Resolve<IDatabaseFixture>() : null;
            if (dbFixture != null)
                nhConfig.UseDbms(c => dbFixture.DbmsType, c => dbFixture.ConnectionString);
            else
                nhConfig.UseDbms(
                    c => testConfig.GetDbmsType(),
                    c => testConfig.GetRequiredConnectionString("TestDB"));

            Configuration.UnitOfWork.Timeout = TimeSpan.FromMinutes(30);
            Configuration.UnitOfWork.IsTransactional = false;
            Configuration.Modules.AbpAutoMapper().UseStaticMapper = false;
            Configuration.BackgroundJobs.IsJobExecutionEnabled = false;
            Configuration.EntityHistory.IsEnabled = false;

            // Hangfire (optional — include if project uses background jobs)
            if (!IocManager.IsRegistered<IBackgroundJobClient>())
            {
                var cs = dbFixture?.ConnectionString
                    ?? testConfig.GetConnectionString("TestDB");
                IocManager.IocContainer.Register(
                    Component.For<IBackgroundJobClient>()
                        .UsingFactoryMethod(() =>
                        {
                            var storage = new SqlServerStorage(cs);
                            JobStorage.Current = storage;
                            return new BackgroundJobClient(storage);
                        })
                        .LifestyleSingleton());
            }

            Configuration.Modules.Zero().LanguageManagement.EnableDbLocalization();
            IocManager.RegisterFakeService<SheshaDbMigrator>();
            Configuration.ReplaceService<IDynamicRepository, DynamicRepository>(
                DependencyLifeStyle.Transient);
            Configuration.ReplaceService<IEmailSender, NullEmailSender>(
                DependencyLifeStyle.Transient);
            Configuration.ReplaceService<ICurrentUnitOfWorkProvider,
                AsyncLocalCurrentUnitOfWorkProvider>(DependencyLifeStyle.Singleton);

            if (!IocManager.IsRegistered<ApplicationPartManager>())
                IocManager.IocContainer.Register(
                    Component.For<ApplicationPartManager>()
                        .ImplementedBy<ApplicationPartManager>());

            ServiceCollectionRegistrar.Register(IocManager);
        }

        public override void Initialize()
        {
            IocManager.RegisterAssemblyByConvention(Assembly.GetExecutingAssembly());
            IocManager.IocContainer.AddFacility<LoggingFacility>(
                f => f.UseAbpLog4Net().WithConfig("log4net.config"));
            ServiceCollectionRegistrar.Register(IocManager);
        }
    }
}
```

## Files to Create (Standalone Path)

| File | Purpose |
|------|---------|
| `{Product}.Common.Domain.Tests.csproj` | Project with Shesha NuGet refs |
| `appsettings.Test.json` | DB config |
| `log4net.config` | Logging |
| `{Product}CommonDomainTestModule.cs` | Full module config |
| `ShaIntegratedTestBase.cs` | ABP test base |
| `SheshaNhTestBase.cs` | NH test base + convenience class |
| `TestWebHostEnvironment.cs` | IWebHostEnvironment impl |
| `UnitTestHelper.cs` | Extension methods |
| `SafeSheshaNHibernateInterceptor.cs` | Interceptor bugfix |
| `Fixtures/IDatabaseFixture.cs` | Interface |
| `Fixtures/LocalSqlServerFixture.cs` | Local DB fixture |
| `Fixtures/LocalSqlServerCollection.cs` | xUnit collection |
| `DependencyInjection/ServiceCollectionRegistrar.cs` | Identity bridge |
| `*_Tests.cs` | Test classes |

## Hangfire Note

The Hangfire registration block is only needed if the project's application services inject `IBackgroundJobClient`. Check the Application project for Hangfire usage before including it. If no Hangfire usage exists, omit the `Hangfire.SqlServer` package reference and the registration block.
