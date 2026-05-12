---
name: add-analyzers
description: Use this skill to add essential code quality analyzers to .NET projects, including AsyncFixer, IDisposableAnalyzers, and Microsoft.VisualStudio.Threading.Analyzers with best-practice configurations.
---

# Add Code Analyzers

This guide will help you add essential code quality analyzers to your .NET project to enforce best practices for async programming, disposable patterns, and threading.

## Overview

You'll be adding three powerful analyzers:

- **AsyncFixer** - Detects and fixes common async/await misuses
- **IDisposableAnalyzers** - Ensures proper disposal of resources
- **Microsoft.VisualStudio.Threading.Analyzers** - Enforces proper threading patterns

## Step 1: Add Analyzer Packages

Add the following NuGet package references to your `.csproj` file(s):

```xml
<ItemGroup>
  <PackageReference Include="AsyncFixer" Version="1.6.0">
    <PrivateAssets>all</PrivateAssets>
    <IncludeAssets>runtime; build; native; contentfiles; analyzers; buildtransitive</IncludeAssets>
  </PackageReference>
  <PackageReference Include="IDisposableAnalyzers" Version="4.0.8">
    <PrivateAssets>all</PrivateAssets>
    <IncludeAssets>runtime; build; native; contentfiles; analyzers; buildtransitive</IncludeAssets>
  </PackageReference>
  <PackageReference Include="Microsoft.VisualStudio.Threading.Analyzers" Version="17.13.2">
    <PrivateAssets>all</PrivateAssets>
    <IncludeAssets>runtime; build; native; contentfiles; analyzers; buildtransitive</IncludeAssets>
  </PackageReference>
</ItemGroup>
```

### Where to Add

- For multiple projects: Add to each `.csproj` file

**Skip these project types — do NOT add analyzers to:**
- Test projects (any `.csproj` containing `<IsTestProject>true</IsTestProject>` or referencing xUnit/NUnit/MSTest)
- `*.Web.Host` projects
- `*.Web.Core` projects

## Step 2: Configure Analyzer Rules

Replace or update your `.editorconfig` file in the backend folder with the following configuration:

```ini
[*.cs]

# ============================================================================
# IDisposableAnalyzers Rules
# ============================================================================
# All rules set to error severity for strict disposal enforcement

dotnet_diagnostic.IDISP001.severity = error  # Dispose created
dotnet_diagnostic.IDISP002.severity = error  # Dispose member
dotnet_diagnostic.IDISP003.severity = error  # Dispose previous before re-assigning
dotnet_diagnostic.IDISP004.severity = error  # Don't ignore created IDisposable
dotnet_diagnostic.IDISP005.severity = error  # Return type should indicate that the value should be disposed
dotnet_diagnostic.IDISP006.severity = error  # Implement IDisposable
dotnet_diagnostic.IDISP007.severity = error  # Don't dispose injected
dotnet_diagnostic.IDISP008.severity = error  # Don't assign member with injected and created disposables
dotnet_diagnostic.IDISP009.severity = error  # Add IDisposable interface
dotnet_diagnostic.IDISP010.severity = error  # Call base.Dispose
dotnet_diagnostic.IDISP011.severity = error  # Don't return disposed instance
dotnet_diagnostic.IDISP012.severity = error  # Property should not return created disposable
dotnet_diagnostic.IDISP013.severity = error  # Await in using
dotnet_diagnostic.IDISP014.severity = error  # Use a single instance of HttpClient
dotnet_diagnostic.IDISP015.severity = error  # Member should not return created and cached instance
dotnet_diagnostic.IDISP016.severity = error  # Don't use disposed instance
dotnet_diagnostic.IDISP017.severity = error  # Prefer using
dotnet_diagnostic.IDISP018.severity = error  # Call SuppressFinalize
dotnet_diagnostic.IDISP019.severity = error  # Call SuppressFinalize(this)
dotnet_diagnostic.IDISP020.severity = error  # Call SuppressFinalize(this) in virtual dispose method
dotnet_diagnostic.IDISP021.severity = error  # Call this.Dispose(true)
dotnet_diagnostic.IDISP022.severity = error  # Call Dispose(true)
dotnet_diagnostic.IDISP023.severity = error  # Don't use reference types in finalizer context
dotnet_diagnostic.IDISP024.severity = error  # Don't call GC.SuppressFinalize(this) when the type is sealed
dotnet_diagnostic.IDISP025.severity = error  # Class with no virtual dispose method should be sealed
dotnet_diagnostic.IDISP026.severity = error  # Class with virtual dispose method should have protected virtual void Dispose(bool disposing)

# ============================================================================
# Microsoft.VisualStudio.Threading.Analyzers Rules
# ============================================================================

# Critical Threading Rules
dotnet_diagnostic.VSTHRD001.severity = error  # Avoid legacy thread switching methods
dotnet_diagnostic.VSTHRD002.severity = error  # Avoid problematic synchronous waits
dotnet_diagnostic.VSTHRD003.severity = error  # Avoid awaiting foreign Tasks
dotnet_diagnostic.VSTHRD004.severity = error  # Await SwitchToMainThreadAsync
dotnet_diagnostic.VSTHRD010.severity = error  # Invoke single-threaded types on Main thread
dotnet_diagnostic.VSTHRD011.severity = error  # Use AsyncLazy<T>
dotnet_diagnostic.VSTHRD012.severity = error  # Provide JoinableTaskFactory where allowed

# Async Best Practices (100 series)
dotnet_diagnostic.VSTHRD100.severity = error  # Avoid async void methods
dotnet_diagnostic.VSTHRD101.severity = error  # Avoid unsupported async delegates
dotnet_diagnostic.VSTHRD102.severity = error  # Implement internal logic asynchronously
dotnet_diagnostic.VSTHRD103.severity = error  # Call async methods when in an async method
dotnet_diagnostic.VSTHRD104.severity = error  # Offer async option
dotnet_diagnostic.VSTHRD105.severity = error  # Avoid method overloads that assume TaskScheduler.Current
dotnet_diagnostic.VSTHRD106.severity = error  # Use InvokeAsync to raise async events
dotnet_diagnostic.VSTHRD107.severity = error  # Await Task within using expression
dotnet_diagnostic.VSTHRD108.severity = error  # Assert thread affinity unconditionally
dotnet_diagnostic.VSTHRD109.severity = error  # Switch instead of assert in async methods
dotnet_diagnostic.VSTHRD110.severity = error  # Observe result of async calls
dotnet_diagnostic.VSTHRD111.severity = none   # Use .ConfigureAwait(bool) - set to none to allow flexibility
dotnet_diagnostic.VSTHRD112.severity = error  # Implement System.IAsyncDisposable
dotnet_diagnostic.VSTHRD113.severity = error  # Check for System.IAsyncDisposable
dotnet_diagnostic.VSTHRD114.severity = error  # Avoid returning null from a Task-returning method
dotnet_diagnostic.VSTHRD115.severity = error  # Avoid creating JoinableTaskContext with explicit null SynchronizationContext

# Naming Conventions (200 series)
dotnet_diagnostic.VSTHRD200.severity = error  # Use Async naming convention

# ============================================================================
# AsyncFixer Rules
# ============================================================================

dotnet_diagnostic.AsyncFixer01.severity = none   # Unnecessary async/await usage
dotnet_diagnostic.AsyncFixer04.severity = error  # Fire-and-forget async call inside a using block
```

## Step 3: Build and Review

After adding the analyzers:

1. **Restore packages:**

   ```bash
   dotnet restore
   ```

2. **Build your project:**

   ```bash
   dotnet build
   ```

3. **Review warnings/errors:**
   - The analyzers will now flag violations in your code
   - Fix critical errors first (disposal issues, async void, etc.)
   - Address warnings based on priority

---
