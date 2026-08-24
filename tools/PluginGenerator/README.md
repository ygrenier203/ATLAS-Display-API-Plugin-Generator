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

Choose one plugin behavior:

- **Current value at cursor** (default) follows the ATLAS cursor and displays the latest value for each configured parameter.
- **Visible range data** retrieves samples across the visible ATLAS time range and exposes timestamps, values, sample count, minimum, and maximum for each parameter.
- **Current value + visible range** generates both workflows and adds a live cursor value to each visible-range series.
- **Compare sessions at cursor** requests each parameter across the associated compare set and displays one cursor value per session.
- **Basic display** creates a view and ViewModel without automatic ATLAS data retrieval.

Use `--behavior current-value`, `--behavior visible-range`, `--behavior current-and-range`, `--behavior compare-sessions`, or `--behavior basic` from the CLI.

Compare-session plugins use `ParameterContainers` and `CompositeSampleResultSignal`, so their generated rows remain aware of overlay/compare sessions instead of reading only the primary session.

Visible-range plugins inherit `TemplateDisplayViewModelBase`, so session, parameter, visibility, and timebase changes automatically trigger throttled refreshes. Generated result handling filters by display identity, locks and unlocks `ParameterValues` safely, and moves ViewModel updates onto the UI thread. The generated `TimebaseSeriesViewModel` retains the raw `Timestamps` and `Values` collections for a custom graph while the starter view displays summary statistics.

On first use, provide the paths explicitly:

```powershell
python -m tools.PluginGenerator.generator MyPlugin --output C:\path\to\output --library-project C:\path\to\DisplayPluginLibrary.csproj --icon C:\path\to\icon.png
```

The GUI provides Browse controls for the output folder, library project, and PNG icon. After a successful generation, the selected paths are persisted in the operating system's per-user application settings and can be changed later in the GUI or overridden with the CLI options. The selected icon is copied into the generated project's `Resources` folder and referenced by filename in both the `.csproj` resource entry and `IconUri`. For parameter-enabled plugins, the selected `DisplayPluginLibrary` project is copied into the generated project container and added to the solution, so the generated solution does not depend on the original library location. No machine-specific paths are stored in this repository or in generated project files.

The GUI enables **Build and validate after generation** by default. Validation restores packages and builds the generated Debug/x64 solution, reports compiler output when it fails, and explicitly disables plugin deployment during the validation build. Uncheck it when working offline or before the private `mat-docs` NuGet feed has been configured. The CLI equivalent is `--build`.

To reset the persisted paths for testing first-use behavior:

```powershell
python -m tools.PluginGenerator.generator --clear-settings
```

The GUI also provides a **Clear Saved Paths** button. This removes only the generator settings; it does not delete generated plugins.

The plugin name is used as the C# namespace. **ATLAS Parameters** and **Display Properties** are configured separately:

- Add ATLAS parameter identifiers such as `vCar:Chassis` one per line. These generate exact `DisplayParameterService.AddParameterContainer(...)` calls in `OnInitialised()` and require the **Current value at cursor** behavior.
- Use the Display Properties list's **Add...**/**Edit...**/**Remove** buttons for ViewModel settings shown in the ATLAS properties window. Each property has a type and default value, plus optional Display Name, Category, Description, Order, workbook persistence, and properties-window visibility. Display properties are independent of ATLAS parameters and also work in basic plugins.

Display property types currently supported are **String**, **Integer**, **Number** (`double`), and **Boolean**. Defaults are validated before generation and emitted as correctly typed C# values. Persisted properties pass the typed default to `ReadProperty(...)` and save changes with `SaveProperty(...)`.

The **When Changed** option can automatically refresh **Current value**, **Visible range**, or both after a property changes. The generator validates the action against the selected behavior: cursor and compare plugins can refresh current values, visible-range plugins can refresh the range, combined plugins can do either or both, and basic plugins cannot make automatic data requests.

Persistence to the workbook via `ReadProperty`/`SaveProperty` is opt-in and defaults to off. Unchecking "Visible in properties window" adds `[Browsable(false)]`. Use `--atlas-parameter "vCar:Chassis"` repeatedly to configure ATLAS parameters from the CLI, `--output C:\path\to\folder` to choose the parent folder, `--no-view` to omit the WPF view, `--behavior basic` to generate a basic display, or `--max-parameters 2` to set the generated limit. Current-value plugins use `DisplayPluginLibrary` to discover configured parameters, request throttled cursor samples, and show live parameter values and ranges in the WPF view.

The GUI's **Commands** section generates an `ICommand` property, `DelegateCommand` initialization, and an empty handler for each action. It can also add a bound WPF button with a custom label. Enable **Generate an enabled/disabled rule** to add a `Can...()` predicate; replace its starter `return true` with the condition that controls button availability. For scripted generation, repeat `--command`, for example `--command Refresh --command Export`; CLI commands receive a button whose label is derived from the command name.

Enable **Generate loading, status, and error state** to add notifying `IsBusy`, `StatusMessage`, and `ErrorMessage` ViewModel properties. This is also available to scripted generation as `--status-state`.

Enable **Generate lifecycle hooks** to add starter overrides for initialization, active-page changes, render visibility changes, and managed cleanup. Every override calls its base implementation, and initialization is combined with automatic ATLAS parameter registration when both are selected. The CLI equivalent is `--lifecycle-hooks`.

Enable **Generate session notification hooks** to add callbacks for sessions loading, sessions unloading, and the display's associated set changing. The generated overrides call their base implementations first so automatic data refresh behavior is preserved. The CLI equivalent is `--session-notifications`.

The GUI will prompt for a plugin name, description, and output folder. The plugin name must contain `Plugin` so ATLAS can discover the assembly. It creates a WPF class library with a `.sln`, `.csproj`, assembly metadata (title, description, and GUID), `PluginModule.cs`, a `ViewModel`, a `Properties/AssemblyInfo.cs` file, and an optional WPF `UserControl` view. The copied `Resources/icon.png` is explicitly included as a WPF resource and registered with the plugin.

The **Injected Services** section lets you select which factories/services from the Display API are constructor-injected into the ViewModel: `ISignalBus`, `IDataRequestSignalFactory`, `ISessionService`, `ISessionSummaryService`, and `ISessionCursorService`. For **Current value at cursor**, `ISignalBus` and `IDataRequestSignalFactory` are always injected via the `ParameterSampleDisplayViewModelBase` constructor, so those two checkboxes are shown pre-checked and disabled; any additional services you select are appended as extra constructor parameters. In a basic display, any selected services are injected directly into a generated constructor. `IDisplayParameterService` is not injectable; it is accessed via `this.ServiceContext.DisplayParameterService` and is already wired up automatically for current-value plugins.

Generated projects currently target `net8.0-windows` and use `Atlas.DisplayAPI 11.4.4.371-W48`, which is the compatible package version available in this repository. The older ATLAS tutorial describes a .NET Framework WPF project; targeting `net48` requires ATLAS and `MAT.OCS.Core` package versions that provide .NET Framework assets.

Notes:
- This is a lightweight starter generator. You can extend templates in `gui.py`.
- Ensure you have .NET SDK installed to build the generated project.
