ATLAS Display Plugin Generator

Usage:

Run the GUI generator with Python from the workspace root:

```powershell
python -m tools.PluginGenerator.generator
```

To generate directly without the GUI:

```powershell
python -m tools.PluginGenerator.generator MyPlugin
```

On first use, provide the paths explicitly:

```powershell
python -m tools.PluginGenerator.generator MyPlugin --output C:\path\to\output --library-project C:\path\to\DisplayPluginLibrary.csproj --icon C:\path\to\icon.png
```

The GUI provides Browse controls for the output folder, library project, and PNG icon. After a successful generation, the selected paths are persisted in the operating system's per-user application settings and can be changed later in the GUI or overridden with the CLI options. The selected icon is copied into the generated project's `Resources` folder and referenced by filename in both the `.csproj` resource entry and `IconUri`. For parameter-enabled plugins, the selected `DisplayPluginLibrary` project is copied into the generated project container and added to the solution, so the generated solution does not depend on the original library location. No machine-specific paths are stored in this repository or in generated project files.

To reset the persisted paths for testing first-use behavior:

```powershell
python -m tools.PluginGenerator.generator --clear-settings
```

The GUI also provides a **Clear Saved Paths** button. This removes only the generator settings; it does not delete generated plugins.

The plugin name is used as the C# namespace. In the GUI, enter one custom parameter identifier per line to generate `DisplayParameterService.AddParameterContainer(...)` calls in `OnInitialised()`, and choose the maximum parameter count. Use `--output C:\path\to\folder` to choose the parent folder, `--no-view` to omit the WPF view, `--no-parameters` to generate a basic display without dynamic parameter support, or `--max-parameters 2` to set the generated limit. Generated parameter displays use `DisplayPluginLibrary` to discover configured parameters, request throttled cursor samples, and show live parameter values and ranges in the WPF view.

The GUI will prompt for a plugin name, description, and output folder. The plugin name must contain `Plugin` so ATLAS can discover the assembly. It creates a WPF class library with a `.sln`, `.csproj`, assembly metadata (title, description, and GUID), `PluginModule.cs`, a `ViewModel`, a `Properties/AssemblyInfo.cs` file, and an optional WPF `UserControl` view. The copied `Resources/icon.png` is explicitly included as a WPF resource and registered with the plugin.

Generated projects currently target `net8.0-windows` and use `Atlas.DisplayAPI 11.4.4.371-W48`, which is the compatible package version available in this repository. The older ATLAS tutorial describes a .NET Framework WPF project; targeting `net48` requires ATLAS and `MAT.OCS.Core` package versions that provide .NET Framework assets.

Notes:
- This is a lightweight starter generator. You can extend templates in `gui.py`.
- Ensure you have .NET SDK installed to build the generated project.
