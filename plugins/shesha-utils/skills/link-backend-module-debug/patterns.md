# Link Backend Module for Debug — Patterns

## §1. .csproj Choose/When/Otherwise block

Wrap the extracted `<PackageReference>` entries for the module. The `<When>` branch replaces them with `<ProjectReference>` entries; the `<Otherwise>` branch restores them exactly.

**Placement**: immediately after the `<ItemGroup>` that previously contained the package references, or at the end of the project file before `</Project>`.

```xml
<Choose>
  <When Condition="'$(UseLocal{Module})' == 'true'">
    <ItemGroup>
      <ProjectReference Include="{RelativePath}/{ProjectName}/{ProjectName}.csproj" />
      <!-- one entry per project in the module -->
    </ItemGroup>
  </When>
  <Otherwise>
    <ItemGroup>
      <PackageReference Include="{PackageName}" Version="$({ModuleVersion})" />
      <!-- restore all original PackageReference entries exactly -->
    </ItemGroup>
  </Otherwise>
</Choose>
```

**Example** (Chat module in `Rsl.Crm.Domain.csproj`):

```xml
<Choose>
  <When Condition="'$(UseLocalChat)' == 'true'">
    <ItemGroup>
      <ProjectReference Include="..\..\..\..\..\pd-chat\backend\src\Module\boxfusion.chat.Domain\boxfusion.chat.Domain.csproj" />
    </ItemGroup>
  </When>
  <Otherwise>
    <ItemGroup>
      <PackageReference Include="boxfusion.chat.Domain" Version="$(ChatVersion)" />
    </ItemGroup>
  </Otherwise>
</Choose>
```

**Key rules:**
- The path in `<ProjectReference Include="...">` uses backslashes (Windows MSBuild convention, matches existing project style).
- Count the `..` segments by walking up from the `.csproj` file's directory to the backend root, then append the sibling repo path.
- Packages with *different* version variables (e.g., `$(SheshaSignalRVersion)` vs `$(ChatVersion)`) stay in the same `<Otherwise>` block together.
- Do not remove the original `<PackageReference>` entries from `<ItemGroup>` if they are in a different group unrelated to this module.

---

## §2. Solution file — adding external projects

### 2a. Solution folder entry

Add before `Global`:

```
Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "{FolderName}", "{FolderName}", "{FOLDER-GUID}"
EndProject
```

### 2b. External project entry

Add one per `.csproj` in the module:

```
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "{ProjectName}", "{RelativePathFromSlnDir}\{ProjectName}.csproj", "{PROJECT-GUID}"
EndProject
```

Path uses backslashes, relative from the `.sln` file's directory (i.e., `backend/`).

**Example** (Chat module in `Rsl.Crm.Debug.sln`, sln is at `backend/`):

```
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "boxfusion.chat.Domain", "..\..\pd-chat\backend\src\Module\boxfusion.chat.Domain\boxfusion.chat.Domain.csproj", "{13450084-63D1-AD3E-1833-00847430634D}"
EndProject
```

### 2c. ProjectConfigurationPlatforms entries

Add inside `GlobalSection(ProjectConfigurationPlatforms) = postSolution` for each new project GUID:

```
{PROJECT-GUID}.Debug|Any CPU.ActiveCfg = Debug|Any CPU
{PROJECT-GUID}.Debug|Any CPU.Build.0 = Debug|Any CPU
{PROJECT-GUID}.DebugLocalShesha|Any CPU.ActiveCfg = Debug|Any CPU
{PROJECT-GUID}.DebugLocalShesha|Any CPU.Build.0 = Debug|Any CPU
{PROJECT-GUID}.Release|Any CPU.ActiveCfg = Release|Any CPU
{PROJECT-GUID}.Release|Any CPU.Build.0 = Release|Any CPU
```

### 2d. NestedProjects entries

Add inside `GlobalSection(NestedProjects) = preSolution`:

```
{PROJECT-GUID} = {FOLDER-GUID}
```

One line per external project, all nested under the same folder GUID.

---

## §3. Directory.Build.props — adding a new UseLocal flag

If the `UseLocal*` property for the selected module doesn't exist yet, add it to the existing `<PropertyGroup>`:

```xml
<!-- Always change to false before pushing/committing -->
<UseLocal{Module}>false</UseLocal{Module}>
```

Insert it near the relevant `<{Module}Version>` property for readability.
