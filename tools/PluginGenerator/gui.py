import os
import re
import json
import math
import html
from decimal import Decimal, InvalidOperation
import ctypes
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import shutil
import subprocess
import sys
import tempfile
import uuid

PRESET_VERSION = 1
DEFAULT_ATLAS_INSTALL_DIRECTORY = r'C:\Program Files\McLaren Applied Technologies\ATLAS 10'


def save_preset(path, configuration):
    payload = {'version': PRESET_VERSION, 'configuration': configuration}
    with open(path, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, indent=2)
        stream.write('\n')


def load_preset(path):
    with open(path, 'r', encoding='utf-8') as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict) or payload.get('version') != PRESET_VERSION:
        raise ValueError('Unsupported or invalid PluginGenerator preset.')
    configuration = payload.get('configuration')
    if not isinstance(configuration, dict):
        raise ValueError('Preset configuration must be a JSON object.')
    return configuration


def list_deployed_plugins(atlas_install_directory):
    candidates = []
    root = atlas_install_directory
    if not os.path.isdir(root):
        return []
    for filename in os.listdir(root):
        if not filename.lower().endswith('customplugin.dll'):
            continue
        path = os.path.join(root, filename)
        if os.path.isfile(path):
            candidates.append(path)
    return sorted(set(candidates), key=lambda path: os.path.basename(path).lower())


def plugin_cleanup_files(plugin_path):
    base, _ = os.path.splitext(plugin_path)
    candidates = [
        plugin_path,
        f'{base}.pdb',
        f'{base}.xml',
        f'{base}.deps.json',
        f'{base}.runtimeconfig.json',
        f'{plugin_path}.config',
    ]
    return [path for path in candidates if os.path.isfile(path)]


def remove_deployed_plugin_files(plugin_paths):
    for plugin_path in plugin_paths:
        for path in plugin_cleanup_files(plugin_path):
            os.remove(path)


def remove_dll_specs(dll_specs, selected_paths):
    selected = {os.path.normcase(os.path.abspath(path)) for path in selected_paths}
    return [
        spec for spec in dll_specs
        if os.path.normcase(os.path.abspath(spec['path'])) not in selected
    ]


def request_elevated_plugin_removal(plugin_paths):
    arguments = subprocess.list2cmdline([
        os.path.abspath(__file__),
        '--remove-deployed-plugin-files',
        *plugin_paths,
    ])
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        'runas',
        sys.executable,
        arguments,
        None,
        1,
    )
    if result <= 32:
        raise RuntimeError('Administrator permission was not granted.')


def is_managed_dll(path):
    try:
        with open(path, 'rb') as stream:
            if stream.read(2) != b'MZ':
                return False
            stream.seek(0x3C)
            pe_offset = int.from_bytes(stream.read(4), 'little')
            stream.seek(pe_offset)
            if stream.read(4) != b'PE\0\0':
                return False
            stream.seek(pe_offset + 24)
            magic = int.from_bytes(stream.read(2), 'little')
            data_directory_offset = 96 if magic == 0x10B else 112 if magic == 0x20B else None
            if data_directory_offset is None:
                return False
            stream.seek(pe_offset + 24 + data_directory_offset + (14 * 8))
            cli_header_rva = int.from_bytes(stream.read(4), 'little')
            cli_header_size = int.from_bytes(stream.read(4), 'little')
            return cli_header_rva != 0 and cli_header_size != 0
    except (OSError, ValueError):
        return False


def build_dll_spec(path, source='custom', existing_names=None):
    path = os.path.abspath(path or '')
    if not os.path.isfile(path) or os.path.splitext(path)[1].lower() != '.dll':
        raise ValueError('Select a valid DLL file.')
    name = os.path.basename(path)
    if existing_names and name.lower() in {item.lower() for item in existing_names}:
        raise ValueError(f'A DLL named "{name}" is already selected.')
    if source not in ('atlas', 'custom'):
        raise ValueError(f'Unknown DLL source: {source}')
    return {
        'name': name,
        'path': path,
        'kind': 'managed' if is_managed_dll(path) else 'native',
        'source': source,
    }


def build_dll_project_items(dll_specs):
    items = []
    for spec in dll_specs:
        name = html.escape(spec['name'], quote=True)
        folder = 'Managed' if spec['kind'] == 'managed' else 'Native'
        hint_path = f'Dependencies\\{folder}\\{name}'
        if spec['kind'] == 'managed':
            assembly_name = html.escape(os.path.splitext(spec['name'])[0], quote=True)
            private = 'true' if spec['source'] == 'custom' else 'false'
            items.append(
                f'    <Reference Include="{assembly_name}">\n'
                f'      <HintPath>{hint_path}</HintPath>\n'
                f'      <Private>{private}</Private>\n'
                '    </Reference>'
            )
        elif spec['source'] == 'custom':
            items.append(
                f'    <Content Include="{hint_path}">\n'
                f'      <TargetPath>{name}</TargetPath>\n'
                '      <CopyToOutputDirectory>PreserveNewest</CopyToOutputDirectory>\n'
                '    </Content>'
            )
    if not items:
        return ''
    return '  <ItemGroup>\n' + '\n'.join(items) + '\n  </ItemGroup>\n'


def normalize_dll_specs(dll_specs):
    normalized = []
    names = set()
    for spec in dll_specs or []:
        normalized_spec = build_dll_spec(spec.get('path'), spec.get('source', 'custom'), names)
        normalized.append(normalized_spec)
        names.add(normalized_spec['name'])
    return normalized


def build_generation_summary(name, behavior, include_view, atlas_parameters, display_property_specs,
                             command_specs, service_names, basic_layout='text', include_status_state=False,
                             include_lifecycle_hooks=False, include_session_notifications=False,
                             include_item_collection=False, collection_name='Items',
                             item_class_name='ItemViewModel', item_field_specs=None, graph_type='none', dll_specs=None):
    plugin_name = normalize_plugin_name(name)
    files = [
        f'{plugin_name}.sln',
        f'{plugin_name}/{plugin_name}.csproj',
        f'{plugin_name}/{plugin_name}.csproj.user',
        f'{plugin_name}/PluginModule.cs',
        f'{plugin_name}/{plugin_name}ViewModel.cs',
        f'{plugin_name}/Properties/AssemblyInfo.cs',
        f'{plugin_name}/Resources/<selected icon>',
    ]
    if include_view:
        files.extend([f'{plugin_name}/{plugin_name}View.xaml', f'{plugin_name}/{plugin_name}View.xaml.cs'])
    if behavior == BEHAVIOR_CURRENT_VALUE:
        files.append(f'{plugin_name}/ParameterViewModel.cs')
    elif behavior in (BEHAVIOR_VISIBLE_RANGE, BEHAVIOR_CURRENT_AND_RANGE):
        files.append(f'{plugin_name}/TimebaseSeriesViewModel.cs')
    elif behavior == BEHAVIOR_COMPARE_SESSIONS:
        files.extend([
            f'{plugin_name}/CompareRowViewModel.cs',
            f'{plugin_name}/CompareSessionValueViewModel.cs',
        ])
    uses_collection = include_item_collection or (behavior == BEHAVIOR_BASIC and basic_layout in ('list', 'table'))
    if uses_collection:
        files.append(f'{plugin_name}/{item_class_name}.cs')
    for spec in dll_specs or []:
        if spec['kind'] == 'managed' or spec['source'] == 'custom':
            folder = 'Managed' if spec['kind'] == 'managed' else 'Native'
            files.append(f'{plugin_name}/Dependencies/{folder}/{spec["name"]}')

    features = []
    if include_status_state:
        features.append('loading/status/error state')
    if include_lifecycle_hooks:
        features.append('lifecycle hooks')
    if include_session_notifications:
        features.append('session notification hooks')
    if uses_collection:
        fields = ', '.join(f'{spec["name"]}:{spec["type"]}' for spec in (item_field_specs or [])) or 'Name:string'
        features.append(f'collection {collection_name}<{item_class_name}> ({fields})')
    if graph_type != 'none':
        features.append(f'{graph_type} graph')

    lines = [
        f'Plugin: {plugin_name}',
        f'Behavior: {behavior}',
        f'View: {"yes" if include_view else "no"}' + (f' ({basic_layout})' if behavior == BEHAVIOR_BASIC else ''),
        f'ATLAS parameters: {len(atlas_parameters)}',
        f'Display properties: {len(display_property_specs)}',
        f'Commands: {len(command_specs)}',
        f'Injected services: {", ".join(service_names) if service_names else "none"}',
        f'DLL dependencies: {len(dll_specs or [])} ({sum(spec["source"] == "custom" for spec in dll_specs or [])} added)',
        f'Optional features: {", ".join(features) if features else "none"}',
        '',
        'Files:',
        *[f'  - {path}' for path in files],
    ]
    return '\n'.join(lines)


CS_PROJ_TEMPLATE = r'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0-windows</TargetFramework>
    <OutputType>Library</OutputType>
    <GenerateAssemblyInfo>false</GenerateAssemblyInfo>
    <UseWindowsForms>true</UseWindowsForms>
    <UseWPF>true</UseWPF>
    <Platforms>x64</Platforms>
    <ProjectGuid>{{{project_guid}}}</ProjectGuid>
    <DeployAtlasPlugin Condition="'$(DeployAtlasPlugin)' == ''">true</DeployAtlasPlugin>
  </PropertyGroup>
  <ItemGroup>
        <Resource Include="Resources\{icon_filename}" />
    <PackageReference Include="Atlas.DisplayAPI" Version="11.4.4.371-W48" />
    <PackageReference Include="System.ComponentModel.Composition" Version="7.0.0" />
  </ItemGroup>
  <ItemGroup>
    <PackageReference Include="Autofac" Version="4.9.1" />
    <PackageReference Include="MAT.OCS.Core" Version="*" />
    <PackageReference Include="System.Reactive" Version="4.4.1" />
  </ItemGroup>
{dll_items}  <Target Name="PostBuild" AfterTargets="PostBuildEvent" Condition="'$(DeployAtlasPlugin)' == 'true'">
        <Exec Command="python &quot;$(SolutionDir)scripts\deploy.py&quot; &quot;$(TargetDir)$(ProjectName).dll&quot;{deploy_dependency_args}" />
  </Target>
</Project>
'''

DEPLOY_PY_TEMPLATE = r'''import argparse
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys


DESTINATION = Path(r'{atlas_install_path}')


def is_elevated():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except AttributeError:
        return False


def relaunch_elevated(dll_paths):
    parameters = subprocess.list2cmdline([__file__, *[str(path) for path in dll_paths]])
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        'runas',
        sys.executable,
        parameters,
        None,
        1,
    )
    if result <= 32:
        raise RuntimeError('Administrator permission was not granted.')
    return 0


def deploy(dll_paths):
    dll_paths = [Path(path).resolve() for path in dll_paths]
    missing_paths = [path for path in dll_paths if not path.is_file()]
    if missing_paths:
        raise FileNotFoundError(f'Build output not found: {{missing_paths[0]}}')
    if not is_elevated():
        return relaunch_elevated(dll_paths)
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for dll_path in dll_paths:
        shutil.copy2(dll_path, DESTINATION / dll_path.name)
        print(f'Deployed {{dll_path.name}} to {{DESTINATION}}')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Deploy a built ATLAS display plugin.')
    parser.add_argument('dll_paths', nargs='+')
    arguments = parser.parse_args()
    try:
        sys.exit(deploy(arguments.dll_paths))
    except (FileNotFoundError, RuntimeError, OSError) as error:
        print(f'Deployment failed: {{error}}', file=sys.stderr)
        sys.exit(1)
'''

LIBRARY_POST_BUILD_PATTERN = re.compile(
    r'\s*<Target\s+Name="PostBuild".*?</Target>\s*',
    re.DOTALL,
)

PLUGIN_MODULE_TEMPLATE = '''using System.ComponentModel.Composition;

using Autofac;
using Autofac.Core;

using MAT.Atlas.Client.Presentation.Plugins;

namespace {namespace}
{{
    [Export(typeof(IModule))]
    public sealed class PluginModule : Module
    {{
        protected override void Load(ContainerBuilder builder)
        {{
            Plugin.Register(builder);
        }}

        [DisplayPlugin(
            View = typeof({view_class}),
            ViewModel = typeof({viewmodel_class}),
            IconUri = "Resources/{icon_filename}")]
        private sealed class Plugin : DisplayPlugin<Plugin>
        {{
        }}
    }}
}}
'''

VIEWMODEL_TEMPLATE = '''using DisplayPluginLibrary;

using System.Collections.Generic;
using MAT.Atlas.Api.Core.Diagnostics;
using MAT.Atlas.Api.Core.Signals;
using MAT.Atlas.Client.Platform.Data;
using MAT.Atlas.Client.Presentation.Commands;
using MAT.Atlas.Client.Presentation.Plugins;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Windows.Input;
using System.Windows.Media;
{extra_usings}
namespace {namespace}
{{
    [DisplayPluginSettings(ParametersMaxCount = {parameter_max_count})]
    public sealed class {viewmodel_class} : ParameterSampleDisplayViewModelBase<ParameterViewModel>
    {{
{status_state_fields}{display_property_fields}
        public {viewmodel_class}(
            ISignalBus signalBus,
            IDataRequestSignalFactory dataRequestSignalFactory,
            ILogger logger{extra_ctor_params}) :
            base(signalBus, dataRequestSignalFactory, logger)
        {{
{extra_ctor_assignments}{command_initializers}        }}

{status_state_properties}{display_properties}
{command_properties}
    {atlas_parameter_setup}
        protected override ParameterViewModel OnCreateParameterViewModel() => new ParameterViewModel();

{session_notification_hooks}
{command_handlers}
    }}
}}
'''

BASIC_VIEWMODEL_TEMPLATE = '''using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Windows.Input;

{extra_usings}using MAT.Atlas.Client.Presentation.Displays;
using MAT.Atlas.Client.Presentation.Commands;
using MAT.Atlas.Client.Presentation.Plugins;

namespace {namespace}
{{
    [DisplayPluginSettings(ParametersMaxCount = {parameter_max_count})]
    public sealed class {viewmodel_class} : DisplayPluginViewModel
    {{
{status_state_fields}{display_property_fields}
{service_members}
{status_state_properties}{display_properties}
{command_properties}
{item_collection_property}
    {atlas_parameter_setup}
{session_notification_hooks}
{command_handlers}    }}
}}
'''

TIMEBASE_VIEWMODEL_TEMPLATE = '''using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Threading.Tasks;

using DisplayPluginLibrary;

using MAT.Atlas.Api.Core.Diagnostics;
using MAT.Atlas.Api.Core.Signals;
using MAT.Atlas.Client.Platform.Data;
using MAT.Atlas.Client.Platform.Data.Signals;
using MAT.Atlas.Client.Platform.Sessions;
using MAT.Atlas.Client.Presentation.Commands;
using MAT.Atlas.Client.Presentation.Plugins;
using System.Windows.Input;
{extra_usings}
namespace {namespace}
{{
    [DisplayPluginSettings(ParametersMaxCount = {parameter_max_count})]
    public sealed class {viewmodel_class} : TemplateDisplayViewModelBase
    {{
        private int dataRequestSampleCount;
{graph_units_field}
{status_state_fields}{display_property_fields}
        public {viewmodel_class}(
            ISignalBus signalBus,
            IDataRequestSignalFactory dataRequestSignalFactory,
            ILogger logger{extra_ctor_params}) :
            base(signalBus, dataRequestSignalFactory, logger)
        {{
{data_subscription}
{cursor_subscription}
{extra_ctor_assignments}{command_initializers}        }}

{sample_count_members}

        [Browsable(false)]
        public ObservableCollection<TimebaseSeriesViewModel> Series {{ get; }} =
            new ObservableCollection<TimebaseSeriesViewModel>();

{show_legend_members}
{status_state_properties}{display_properties}
{command_properties}
    {atlas_parameter_setup}
{timebase_request_method}

{cursor_request_method}
{cursor_result_handler}

{session_notification_hooks}
{data_result_handler}

        private void SyncSeries()
        {{
            var existing = this.Series.ToDictionary(item => item.ParameterIdentifier);
            this.Series.Clear();
            for (var index = 0; index < this.DisplayParameterService.PrimaryParameters.Count; index++)
            {{
                var parameter = this.DisplayParameterService.PrimaryParameters[index];
                var unit = index < GraphUnits.Length ? GraphUnits[index] : string.Empty;
                if (existing.TryGetValue(parameter.InstanceIdentifier, out var series))
                {{
                    series.Name = parameter.Name;
                    series.Unit = unit;
                    this.Series.Add(series);
                }}
                else
                {{
                    this.Series.Add(new TimebaseSeriesViewModel(
                        parameter.InstanceIdentifier,
                        parameter.Name,
                        unit));
                }}
            }}
        }}

{graph_cursor_method}

{command_handlers}
    }}
}}
'''

TIMEBASE_SERIES_VIEWMODEL_TEMPLATE = '''using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;

using MAT.Atlas.Api.Core.Presentation;

namespace {namespace}
{{
    public sealed class TimebaseSeriesViewModel : BindableBase
    {{
        private double maximum = double.NaN;
        private double minimum = double.NaN;
        private double average = double.NaN;
        private long? currentTimestamp;
{current_value_field}
        private string name;
        private int sampleCount;
        private IReadOnlyList<long> timestamps = Array.Empty<long>();
        private IReadOnlyList<double> values = Array.Empty<double>();

        [Browsable(false)]
        public string GraphGroup {{ get; set; }} = string.Empty;

        public TimebaseSeriesViewModel(Guid parameterIdentifier, string name, string unit)
        {{
            this.ParameterIdentifier = parameterIdentifier;
            this.name = name;
            this.unit = unit;
        }}

        [Browsable(false)]
        public Guid ParameterIdentifier {{ get; }}

        public string Name
        {{
            get => this.name;
            set => this.SetProperty(ref this.name, value);
        }}

        private string unit;

        public string Unit
        {{
            get => this.unit;
            set => this.SetProperty(ref this.unit, value);
        }}

        public int SampleCount
        {{
            get => this.sampleCount;
            private set => this.SetProperty(ref this.sampleCount, value);
        }}

        public double Minimum
        {{
            get => this.minimum;
            private set => this.SetProperty(ref this.minimum, value);
        }}

        public double Maximum
        {{
            get => this.maximum;
            private set => this.SetProperty(ref this.maximum, value);
        }}

        public double Average
        {{
            get => this.average;
            private set => this.SetProperty(ref this.average, value);
        }}

        [Browsable(false)]
        public long? CurrentTimestamp
        {{
            get => this.currentTimestamp;
            private set => this.SetProperty(ref this.currentTimestamp, value);
        }}

{current_value_property}

        [Browsable(false)]
        public IReadOnlyList<long> Timestamps
        {{
            get => this.timestamps;
            private set => this.SetProperty(ref this.timestamps, value);
        }}

        [Browsable(false)]
        public IReadOnlyList<double> Values
        {{
            get => this.values;
            private set => this.SetProperty(ref this.values, value);
        }}

        public void Update(long[] timestamps, double[] values)
        {{
            this.Timestamps = timestamps;
            this.Values = values;
            var validValues = values.Where(value => !double.IsNaN(value) && !double.IsInfinity(value)).ToArray();
            this.SampleCount = validValues.Length;
            this.Minimum = validValues.Length == 0 ? double.NaN : validValues.Min();
            this.Maximum = validValues.Length == 0 ? double.NaN : validValues.Max();
            this.Average = validValues.Length == 0 ? double.NaN : validValues.Average();
        }}

{current_value_update_method}
    }}
}}
'''

DATA_SUBSCRIPTION = '''            this.Disposables.Add(this.SignalBus.Subscribe<DataResultSignal>(
                this.HandleDataResultSignal,
                signal => signal.SourceId == this.ScopeIdentity.Guid));'''

SAMPLE_COUNT_MEMBERS = '''        [Category("Data")]
        [DisplayName("Sample Count")]
        [Description("Maximum number of samples requested across the visible time range.")]
        [Display(Order = 0)]
        public int DataRequestSampleCount
        {
            get => this.dataRequestSampleCount = this.ReadProperty({default_sample_count});
            set
            {
                if (this.SetProperty(ref this.dataRequestSampleCount, value))
                {
                    this.SaveProperty(value);
                    this.MakeDataRequests(false, true);
                }
            }
        }'''

TIMEBASE_REQUEST_METHOD = '''        protected override async Task OnMakeTimebaseDataRequestsAsync(ICompositeSession compositeSession)
        {
            await this.ExecuteOnUiAsync(this.SyncSeries);

            foreach (var parameter in this.DisplayParameterService.PrimaryParameters)
            {
                var signal = this.DataRequestSignalFactory.CreateDataRequestSignal(
                    this.ScopeIdentity.Guid,
                    parameter,
                    compositeSession.TimebaseRange,
                    this.DataRequestSampleCount,
                    SampleMode.Mean);

                this.SignalBus.Send(signal);
            }
        }'''

DATA_RESULT_HANDLER = '''        private async void HandleDataResultSignal(DataResultSignal signal)
        {
            try
            {
                var parameterValues = signal.Data.ParameterValues;
                long[] timestamps;
                double[] values;
                parameterValues.Lock();
                try
                {
                    if (parameterValues.SampleCount == 0 || parameterValues.Data == null)
                    {
                        return;
                    }

                    timestamps = parameterValues.Timestamp.ToArray();
                    values = parameterValues.Data.ToArray();
                }
                finally
                {
                    parameterValues.Unlock();
                }

                await this.ExecuteOnUiAsync(() =>
                {
                    var series = this.Series.FirstOrDefault(item =>
                        item.ParameterIdentifier == signal.Data.Request.Parameter.InstanceIdentifier);
                    series?.Update(timestamps, values);
                });
            }
            catch (Exception exception)
            {
                this.Logger.Trace("Error handling visible-range data", exception);
            }
        }'''

CURSOR_SUBSCRIPTION = '''            this.Disposables.Add(this.SignalBus.Subscribe<SampleResultSignal>(
                this.HandleSampleResultSignal,
                signal => signal.SourceId == this.ScopeIdentity.Guid));'''

CURSOR_REQUEST_METHOD = '''        protected override async Task OnMakeCursorDataRequestsAsync(ICompositeSession compositeSession)
        {
            await this.ExecuteOnUiAsync(this.SyncSeries);

            foreach (var parameter in this.DisplayParameterService.PrimaryParameters)
            {
                var signal = this.DataRequestSignalFactory.CreateSampleRequestSignal(
                    this.ScopeIdentity.Guid,
                    parameter.InstanceIdentifier,
                    compositeSession.Key,
                    parameter,
                    compositeSession.CursorPoint + 1,
                    1,
                    SampleDirection.Previous);

                this.SignalBus.Send(signal);
            }
        }'''

CURSOR_RESULT_HANDLER = '''        private async void HandleSampleResultSignal(SampleResultSignal signal)
        {
            try
            {
                var parameterValues = signal.Data.ParameterValues;
                double value;
                long timestamp;
                parameterValues.Lock();
                try
                {
                    if (parameterValues.SampleCount != 1 ||
                        parameterValues.Data == null ||
                        !parameterValues.DataStatus[0].HasFlag(DataStatusType.Sample))
                    {
                        return;
                    }

                    value = parameterValues.Data[0];
                    timestamp = parameterValues.Timestamp[0];
                }
                finally
                {
                    parameterValues.Unlock();
                }

                if (double.IsNaN(value))
                {
                    return;
                }

                await this.ExecuteOnUiAsync(() =>
                {
                    var series = this.Series.FirstOrDefault(item =>
                        item.ParameterIdentifier == signal.Data.Request.RequestId);
                    series?.UpdateCurrentValue(value, timestamp);
                });
            }
            catch (Exception exception)
            {
                this.Logger.Trace("Error handling cursor data", exception);
            }
        }'''

CURRENT_VALUE_FIELD = '        private double currentValue = double.NaN;'

CURRENT_VALUE_PROPERTY = '''        public double CurrentValue
        {
            get => this.currentValue;
            private set => this.SetProperty(ref this.currentValue, value);
        }'''

CURRENT_VALUE_UPDATE_METHOD = '''        public void UpdateCurrentValue(double value, long timestamp)
        {
            this.CurrentValue = value;
            this.CurrentTimestamp = timestamp;
        }'''

GRAPH_CURSOR_METHOD = '''        public void MoveCursor(long timestamp)
        {
            if (!this.CanRetrieveData ||
                this.ActiveCompositeSessionContainer?.IsPrimaryCompositeSessionAvailable != true)
            {
                return;
            }

            var primarySession = this.ActiveCompositeSessionContainer.CompositeSessions
                .FirstOrDefault(session => session.IsPrimary);
            if (primarySession != null)
            {
                this.sessionCursorService.MoveCursor(primarySession, timestamp);
            }
        }'''

CURRENT_VALUE_TEXT = '''                            <TextBlock Text="{Binding CurrentValue, StringFormat='Current  {0:F3}'}"
                                       Style="{StaticResource MetricStyle}" />'''

SHOW_LEGEND_MEMBERS = '''        private bool showLegend = __SHOW_LEGEND_DEFAULT__;

        [Browsable(false)]
        public bool ShowLegend
        {
            get => this.showLegend;
            set => this.SetProperty(ref this.showLegend, value);
        }
'''

COMPARE_VIEWMODEL_TEMPLATE = '''using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Threading.Tasks;

using DisplayPluginLibrary;

using MAT.Atlas.Api.Core.Diagnostics;
using MAT.Atlas.Api.Core.Signals;
using MAT.Atlas.Client.Platform.Data;
using MAT.Atlas.Client.Platform.Data.Signals;
using MAT.Atlas.Client.Platform.Sessions;
using MAT.Atlas.Client.Presentation.Commands;
using MAT.Atlas.Client.Presentation.Plugins;
using System.Windows.Input;
{extra_usings}
namespace {namespace}
{{
    [DisplayPluginSettings(ParametersMaxCount = {parameter_max_count})]
    public sealed class {viewmodel_class} : TemplateDisplayViewModelBase
    {{
{status_state_fields}{display_property_fields}
        public {viewmodel_class}(
            ISignalBus signalBus,
            IDataRequestSignalFactory dataRequestSignalFactory,
            ILogger logger{extra_ctor_params}) :
            base(signalBus, dataRequestSignalFactory, logger)
        {{
            this.Disposables.Add(this.SignalBus.Subscribe<CompositeSampleResultSignal>(
                this.HandleCompositeSampleResultSignal,
                signal => signal.SourceId == this.ScopeIdentity.Guid));
{extra_ctor_assignments}{command_initializers}        }}

        [Browsable(false)]
        public ObservableCollection<CompareRowViewModel> Rows {{ get; }} =
            new ObservableCollection<CompareRowViewModel>();
{compare_graph_members}

{status_state_properties}{display_properties}
{command_properties}
    {atlas_parameter_setup}
{session_notification_hooks}
        protected override async Task OnMakeCursorDataRequestsAsync(ICompositeSession compositeSession)
        {{
            await this.ExecuteOnUiAsync(this.SyncRows);

            foreach (var parameterContainer in this.DisplayParameterService.ParameterContainers)
            {{
                var signal = this.DataRequestSignalFactory.CreateCompositeSampleRequestSignal(
                    this.ScopeIdentity.Guid,
                    this.ActiveCompositeSessionContainer.Key,
                    parameterContainer,
                    compositeSession.CursorPoint + 1,
                    1,
                    SampleDirection.Previous);

                this.SignalBus.Send(signal);
            }}
        }}

        private async void HandleCompositeSampleResultSignal(CompositeSampleResultSignal signal)
        {{
            try
            {{
                var updates = new List<(MAT.OCS.Core.CompositeSessionKey SessionKey, double Value)>();
                foreach (var result in signal.Data.Results)
                {{
                    var parameterValues = result.Value.ParameterValues;
                    parameterValues.Lock();
                    try
                    {{
                        if (parameterValues.SampleCount > 0 &&
                            parameterValues.Data != null &&
                            !double.IsNaN(parameterValues.Data[0]) &&
                            !double.IsInfinity(parameterValues.Data[0]))
                        {{
                            updates.Add((result.Key, parameterValues.Data[0]));
                        }}
                    }}
                    finally
                    {{
                        parameterValues.Unlock();
                    }}
                }}

                var parameterIdentifier = signal.Data.Request.ParameterContainer.InstanceIdentifier;
                await this.ExecuteOnUiAsync(() =>
                {{
                    var row = this.Rows.FirstOrDefault(item =>
                        item.ParameterIdentifier == parameterIdentifier);
                    if (row == null)
                    {{
                        return;
                    }}

                    foreach (var update in updates)
                    {{
                        row.Update(update.SessionKey, update.Value);
                    }}
{compare_graph_sync_call}
                }});
            }}
            catch (Exception exception)
            {{
                this.Logger.Trace("Error handling compare-session data", exception);
            }}
        }}

        private void SyncRows()
        {{
            var sessions = this.ActiveCompositeSessionContainer.CompositeSessions.ToList();
            var existing = this.Rows.ToDictionary(row => row.ParameterIdentifier);
            this.Rows.Clear();
            foreach (var parameterContainer in this.DisplayParameterService.ParameterContainers)
            {{
                if (!existing.TryGetValue(parameterContainer.InstanceIdentifier, out var row))
                {{
                    row = new CompareRowViewModel(
                        parameterContainer.InstanceIdentifier,
                        parameterContainer.Name);
                }}

                row.Name = parameterContainer.Name;
                row.SyncSessions(sessions);
                this.Rows.Add(row);
            }}
{compare_graph_sync_call}
        }}

{compare_graph_sync_method}
{command_handlers}
    }}
}}
'''

COMPARE_GRAPH_MEMBERS = '''
        private static readonly string[] GraphUnits = { __GRAPH_UNITS__ };

        [Browsable(false)]
        public ObservableCollection<TimebaseSeriesViewModel> Series { get; } =
            new ObservableCollection<TimebaseSeriesViewModel>();

        private bool showLegend = __SHOW_LEGEND_DEFAULT__;

        [Browsable(false)]
        public bool ShowLegend
        {
            get => this.showLegend;
            set => this.SetProperty(ref this.showLegend, value);
        }
'''

COMPARE_GRAPH_SYNC_METHOD = '''        private void SyncGraphSeries()
        {
            this.Series.Clear();
            var parameterIndex = 0;
            foreach (var row in this.Rows)
            {
                var unit = parameterIndex < GraphUnits.Length ? GraphUnits[parameterIndex] : string.Empty;
                foreach (var sessionValue in row.SessionValues)
                {
                    var series = new TimebaseSeriesViewModel(
                        row.ParameterIdentifier,
                        $"{row.Name} — {sessionValue.SessionName}",
                        unit);
                    series.GraphGroup = sessionValue.SessionName;
                    series.UpdateCurrentValue(sessionValue.Value, 0L);
                    this.Series.Add(series);
                }

                parameterIndex++;
            }
        }
'''

COMPARE_ROW_VIEWMODEL_TEMPLATE = '''using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;

using MAT.Atlas.Api.Core.Presentation;
using MAT.Atlas.Client.Platform.Sessions;

namespace {namespace}
{{
    public sealed class CompareRowViewModel : BindableBase
    {{
        private string name;

        public CompareRowViewModel(Guid parameterIdentifier, string name)
        {{
            this.ParameterIdentifier = parameterIdentifier;
            this.name = name;
        }}

        [Browsable(false)]
        public Guid ParameterIdentifier {{ get; }}

        public string Name
        {{
            get => this.name;
            set => this.SetProperty(ref this.name, value);
        }}

        [Browsable(false)]
        public ObservableCollection<CompareSessionValueViewModel> SessionValues {{ get; }} =
            new ObservableCollection<CompareSessionValueViewModel>();

        public void SyncSessions(IEnumerable<ICompositeSession> sessions)
        {{
            var existing = this.SessionValues.ToDictionary(value => value.SessionKey);
            this.SessionValues.Clear();
            foreach (var session in sessions)
            {{
                if (existing.TryGetValue(session.Key, out var value))
                {{
                    value.SessionName = session.Identifier.ToString();
                    this.SessionValues.Add(value);
                }}
                else
                {{
                    this.SessionValues.Add(new CompareSessionValueViewModel(
                        session.Key,
                        session.Identifier.ToString()));
                }}
            }}
        }}

        public void Update(MAT.OCS.Core.CompositeSessionKey sessionKey, double value)
        {{
            var sessionValue = this.SessionValues.FirstOrDefault(item => item.SessionKey == sessionKey);
            if (sessionValue != null)
            {{
                sessionValue.Value = value;
            }}
        }}
    }}
}}
'''

COMPARE_SESSION_VALUE_VIEWMODEL_TEMPLATE = '''using System.ComponentModel;

using MAT.Atlas.Api.Core.Presentation;
using MAT.Atlas.Client.Platform.Sessions;

namespace {namespace}
{{
    public sealed class CompareSessionValueViewModel : BindableBase
    {{
        private string sessionName;
        private double value = double.NaN;

        public CompareSessionValueViewModel(MAT.OCS.Core.CompositeSessionKey sessionKey, string sessionName)
        {{
            this.SessionKey = sessionKey;
            this.sessionName = sessionName;
        }}

        [Browsable(false)]
        public MAT.OCS.Core.CompositeSessionKey SessionKey {{ get; }}

        public string SessionName
        {{
            get => this.sessionName;
            set => this.SetProperty(ref this.sessionName, value);
        }}

        public double Value
        {{
            get => this.value;
            set => this.SetProperty(ref this.value, value);
        }}
    }}
}}
'''

PARAMETER_VIEWMODEL_TEMPLATE = '''using DisplayPluginLibrary;

namespace {namespace}
{{
    public sealed class ParameterViewModel : ParameterSampleViewModelBase
    {{
        private string description;
        private double displayMaximum;
        private double displayMinimum;

        public string Description
        {{
            get => this.description;
            set => this.SetProperty(ref this.description, value);
        }}

        public double DisplayMaximum
        {{
            get => this.displayMaximum;
            set => this.SetProperty(ref this.displayMaximum, value);
        }}

        public double DisplayMinimum
        {{
            get => this.displayMinimum;
            set => this.SetProperty(ref this.displayMinimum, value);
        }}

        protected override void OnUpdate()
        {{
            this.DisplayMinimum = this.DisplayParameter.SessionParameter.Minimum;
            this.DisplayMaximum = this.DisplayParameter.SessionParameter.Maximum;
        }}

        protected override bool OnValueChanged(double? oldValue, double newValue)
        {{
            this.OnUpdate();
            if (newValue < this.DisplayMinimum || newValue > this.DisplayMaximum)
            {{
                return false;
            }}

            this.Description = $"{{this.Name}}\\r{{this.Value}}";
            return true;
        }}
    }}
}}
'''

ITEM_VIEWMODEL_TEMPLATE = '''using MAT.Atlas.Api.Core.Presentation;

namespace {namespace}
{{
    public sealed class {item_class_name} : BindableBase
    {{
{item_members}
    }}
}}
'''

GRAPH_SERIES_TEMPLATE = '''using System.Collections.Generic;
using System.Windows.Media;

namespace {namespace}
{{
    public sealed class GraphSeries
    {{
        public GraphSeries(string name, IReadOnlyList<long> timestamps, IReadOnlyList<double> values, Color color,
            double currentValue = double.NaN, string groupName = "")
        {{
            this.Name = name;
            this.Timestamps = timestamps;
            this.Values = values;
            this.Color = color;
            this.CurrentValue = currentValue;
            this.GroupName = groupName;
        }}

        public string Name {{ get; }}

        public IReadOnlyList<long> Timestamps {{ get; }}

        public IReadOnlyList<double> Values {{ get; }}

        public Color Color {{ get; }}

        public double CurrentValue {{ get; }}

        public string GroupName {{ get; }}
    }}
}}
'''

GRAPH_RENDERER_TEMPLATE = '''using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Media;
using System.Text.RegularExpressions;

namespace {namespace}
{{
    public sealed class GraphRenderer
    {{
        private static readonly string GraphType = "__GRAPH_TYPE__";
        private static readonly bool OverlayCursorBars = __CURSOR_BAR_OVERLAY__;
        private static readonly bool PairCursorPointsByHalf = __PAIR_CURSOR_POINTS_BY_HALF__;

        public void Draw(DrawingContext drawingContext, Size extents, IReadOnlyList<GraphSeries> series,
            long? viewportStart = null, long? viewportEnd = null)
        {{
            drawingContext.DrawRectangle(Brushes.Transparent, new Pen(Brushes.DimGray, 1), new Rect(extents));
            var gridPen = new Pen(Brushes.DimGray, 0.5);
            for (var division = 1; division < 5; division++)
            {{
                var x = (extents.Width * division) / 5;
                var y = (extents.Height * division) / 5;
                drawingContext.DrawLine(gridPen, new Point(x, 0), new Point(x, extents.Height));
                drawingContext.DrawLine(gridPen, new Point(0, y), new Point(extents.Width, y));
            }}
            if (extents.Width <= 0 || extents.Height <= 0)
            {{
                return;
            }}

            if (GraphType == "cursor-histogram")
            {{
                this.DrawCursorValues(drawingContext, extents, series, false);
                return;
            }}

            if (GraphType == "cursor-points")
            {{
                this.DrawCursorValues(drawingContext, extents, series, true);
                return;
            }}

            var validSeries = series.Where(item => item.Timestamps.Count > 1 && item.Values.Count > 1).ToList();
            if (validSeries.Count == 0)
            {{
                return;
            }}

            if (GraphType == "scatter")
            {{
                this.DrawScatter(drawingContext, extents, validSeries);
                return;
            }}

            if (GraphType == "histogram")
            {{
                this.DrawHistogram(drawingContext, extents, validSeries[0]);
                return;
            }}

            if (GraphType == "bar")
            {{
                this.DrawBars(drawingContext, extents, validSeries);
                return;
            }}

            if (GraphType == "custom")
            {{
                new CustomGraphRenderer().Draw(drawingContext, extents, validSeries);
                return;
            }}

            var start = viewportStart ?? validSeries.Min(item => item.Timestamps.First());
            var end = viewportEnd ?? validSeries.Max(item => item.Timestamps.Last());
            var timeRange = Math.Max(1, end - start);
            var visibleValues = validSeries.SelectMany(item => Enumerable.Range(
                    0, Math.Min(item.Timestamps.Count, item.Values.Count))
                .Where(index => item.Timestamps[index] >= start && item.Timestamps[index] <= end)
                .Select(index => item.Values[index]))
                .Where(value => !double.IsNaN(value) && !double.IsInfinity(value)).ToList();
            if (visibleValues.Count == 0)
            {{
                return;
            }}

            GetCenteredNiceBounds(visibleValues, false, out var minimum, out var maximum);
            var valueRange = maximum - minimum;
            foreach (var item in validSeries)
            {{
                this.DrawSeries(drawingContext, extents, item, start, timeRange, minimum, valueRange);
            }}

            this.DrawTimeAxes(drawingContext, extents, start, end, minimum, maximum);
        }}

        public void DrawCursor(DrawingContext drawingContext, Size extents, IReadOnlyList<GraphSeries> series,
            long? timestamp, long? viewportStart = null, long? viewportEnd = null)
        {{
            if (GraphType != "time-series" || !timestamp.HasValue || extents.Width <= 0 || extents.Height <= 0)
            {{
                return;
            }}

            var validSeries = series.Where(item => item.Timestamps.Count > 1).ToList();
            if (validSeries.Count == 0)
            {{
                return;
            }}

            var start = viewportStart ?? validSeries.Min(item => item.Timestamps.First());
            var end = viewportEnd ?? validSeries.Max(item => item.Timestamps.Last());
            if (timestamp.Value < start || timestamp.Value > end)
            {{
                return;
            }}

            var x = ((timestamp.Value - start) / (double)Math.Max(1, end - start)) * extents.Width;
            drawingContext.DrawLine(new Pen(Brushes.White, 1), new Point(x, 0), new Point(x, extents.Height));
        }}

        private void DrawSeries(DrawingContext drawingContext, Size extents, GraphSeries series,
            long start, long timeRange, double minimum, double valueRange)
        {{
            var count = Math.Min(series.Timestamps.Count, series.Values.Count);
            var pen = new Pen(new SolidColorBrush(series.Color), 1.5);
            Point? previous = null;
            for (var index = 0; index < count; index++)
            {{
                var value = series.Values[index];
                var timestamp = series.Timestamps[index];
                if (timestamp < start || timestamp > start + timeRange ||
                    double.IsNaN(value) || double.IsInfinity(value))
                {{
                    previous = null;
                    continue;
                }}

                var x = ((timestamp - start) / (double)timeRange) * extents.Width;
                var y = extents.Height - (((value - minimum) / valueRange) * extents.Height);
                var point = new Point(x, y);
                if (previous.HasValue)
                {{
                    drawingContext.DrawLine(pen, previous.Value, point);
                }}

                previous = point;
            }}
        }}

        private void DrawScatter(DrawingContext drawingContext, Size extents, IReadOnlyList<GraphSeries> series)
        {{
            if (series.Count < 2)
            {{
                return;
            }}

            var count = Math.Min(series[0].Values.Count, series[1].Values.Count);
            var points = Enumerable.Range(0, count)
                .Select(index => new {{ X = series[0].Values[index], Y = series[1].Values[index] }})
                .Where(point =>
                    !double.IsNaN(point.X) && !double.IsInfinity(point.X) &&
                    !double.IsNaN(point.Y) && !double.IsInfinity(point.Y)).ToList();
            if (points.Count == 0) return;
            var minX = points.Min(point => point.X);
            var maxX = points.Max(point => point.X);
            var rangeX = Math.Max(double.Epsilon, maxX - minX);
            var yValues = points.Select(point => point.Y).ToList();
            GetCenteredNiceBounds(yValues, false, out var minY, out var maxY);
            var rangeY = maxY - minY;
            foreach (var point in points)
            {{
                var x = ((point.X - minX) / rangeX) * extents.Width;
                var y = extents.Height - (((point.Y - minY) / rangeY) * extents.Height);
                drawingContext.DrawEllipse(Brushes.DeepSkyBlue, null, new Point(x, y), 2, 2);
            }}

            this.DrawNumericAxes(drawingContext, extents, minX, maxX, minY, maxY);
        }}

        private void DrawHistogram(DrawingContext drawingContext, Size extents, GraphSeries series)
        {{
            var values = series.Values.Where(value => !double.IsNaN(value) && !double.IsInfinity(value)).ToList();
            if (values.Count == 0) return;
            const int bucketCount = 20;
            var minimum = values.Min();
            var range = Math.Max(double.Epsilon, values.Max() - minimum);
            var buckets = new int[bucketCount];
            foreach (var value in values)
            {{
                var bucket = Math.Min(bucketCount - 1, (int)(((value - minimum) / range) * bucketCount));
                buckets[bucket]++;
            }}

            GetCenteredNiceBounds(buckets.Select(value => (double)value).ToList(), true,
                out var countMinimum, out var countMaximum);
            var width = extents.Width / bucketCount;
            var countRange = countMaximum - countMinimum;
            var zeroY = extents.Height - (((0d - countMinimum) / countRange) * extents.Height);
            for (var index = 0; index < bucketCount; index++)
            {{
                var valueY = extents.Height - (((buckets[index] - countMinimum) / countRange) * extents.Height);
                drawingContext.DrawRectangle(Brushes.DeepSkyBlue, null,
                    new Rect(index * width, Math.Min(zeroY, valueY), Math.Max(1, width - 1),
                        Math.Max(1d, Math.Abs(zeroY - valueY))));
            }}

            this.DrawNumericAxes(drawingContext, extents, minimum, values.Max(), countMinimum, countMaximum);
        }}

        private void DrawBars(DrawingContext drawingContext, Size extents, IReadOnlyList<GraphSeries> series)
        {{
            var averages = series.Select(item => item.Values
                .Where(value => !double.IsNaN(value) && !double.IsInfinity(value))
                .DefaultIfEmpty().Average()).ToList();
            GetCenteredNiceBounds(averages, true, out var minimum, out var maximum);
            var range = maximum - minimum;
            var zeroY = extents.Height - (((0d - minimum) / range) * extents.Height);
            var width = extents.Width / Math.Max(1, averages.Count);
            for (var index = 0; index < averages.Count; index++)
            {{
                var valueY = extents.Height - (((averages[index] - minimum) / range) * extents.Height);
                drawingContext.DrawRectangle(new SolidColorBrush(series[index].Color), null,
                    new Rect(index * width, Math.Min(zeroY, valueY), Math.Max(1, width - 4),
                        Math.Max(1d, Math.Abs(zeroY - valueY))));
            }}

            this.DrawValueAndCategoryAxes(drawingContext, extents, minimum, maximum,
                series.Select(item => item.Name).ToList(), false);
        }}

        private void DrawCursorValues(DrawingContext drawingContext, Size extents,
            IReadOnlyList<GraphSeries> series, bool drawPoints)
        {{
            var current = series.Where(item =>
                !double.IsNaN(item.CurrentValue) && !double.IsInfinity(item.CurrentValue)).ToList();
            if (current.Count == 0)
            {{
                return;
            }}

            GetCenteredNiceBounds(current.Select(item => item.CurrentValue).ToList(), !drawPoints,
                out var minimum, out var maximum);
            var range = maximum - minimum;
            var zeroY = extents.Height - (((0d - minimum) / range) * extents.Height);
            // Cursor points overlay pairs of signals into shared slots instead of one shared slot.
            // Sequential pairing groups (1-2, 3-4, ...); split-half pairing groups (k, k + n/2) e.g. (1,3), (2,4).
            var pairOverlay = drawPoints && OverlayCursorBars;
            if (pairOverlay)
            {{
                this.DrawPairedCursorPoints(drawingContext, extents, current, minimum, maximum);
                return;
            }}
            var halfCount = pairOverlay ? Math.Max(1, (int)Math.Ceiling(current.Count / 2d)) : 0;
            var slotCount = pairOverlay ? halfCount : (OverlayCursorBars ? 1 : current.Count);
            var slotWidth = extents.Width / slotCount;
            for (var index = 0; index < current.Count; index++)
            {{
                var item = current[index];
                var valueY = extents.Height - (((item.CurrentValue - minimum) / range) * extents.Height);
                var barWidth = Math.Max(2d, slotWidth * (OverlayCursorBars ? 0.6d : 0.75d));
                var slotIndex = pairOverlay
                    ? (PairCursorPointsByHalf ? index % halfCount : index / 2)
                    : (OverlayCursorBars ? 0 : index);
                var pairPosition = pairOverlay
                    ? (PairCursorPointsByHalf ? index / halfCount : index % 2)
                    : 0;
                var x = (slotIndex * slotWidth) + ((slotWidth - barWidth) / 2d);
                // Paired cursor points are colored by position in the pair (first red, second blue), not by series color.
                var baseColor = pairOverlay ? (pairPosition == 0 ? Colors.Red : Colors.Blue) : item.Color;
                var color = Color.FromArgb(OverlayCursorBars ? (byte)150 : (byte)230,
                    baseColor.R, baseColor.G, baseColor.B);
                if (drawPoints)
                {{
                    drawingContext.DrawEllipse(new SolidColorBrush(color), new Pen(Brushes.White, 1d),
                        new Point(x + (barWidth / 2d), valueY), 5d, 5d);
                }}
                else
                {{
                    drawingContext.DrawRectangle(new SolidColorBrush(color), null,
                        new Rect(x, Math.Min(zeroY, valueY), barWidth, Math.Max(1d, Math.Abs(zeroY - valueY))));
                }}
            }}

            var categoryLabels = current.Select(item => item.Name).ToList();
            if (pairOverlay)
            {{
                var pairedLabels = new List<string>();
                for (var slot = 0; slot < halfCount; slot++)
                {{
                    var firstIndex = PairCursorPointsByHalf ? slot : slot * 2;
                    var secondIndex = PairCursorPointsByHalf ? slot + halfCount : (slot * 2) + 1;
                    pairedLabels.Add(secondIndex < current.Count
                        ? $"{{current[firstIndex].Name}} / {{current[secondIndex].Name}}"
                        : current[firstIndex].Name);
                }}

                categoryLabels = pairedLabels;
            }}

            this.DrawValueAndCategoryAxes(drawingContext, extents, minimum, maximum,
                categoryLabels, OverlayCursorBars && !pairOverlay);
        }}

        private void DrawPairedCursorPoints(DrawingContext drawingContext, Size extents,
            IReadOnlyList<GraphSeries> current, double minimum, double maximum)
        {{
            var groups = current.GroupBy(item => item.GroupName ?? string.Empty).ToList();
            var largestGroup = groups.Max(group => group.Count());
            var slotCount = Math.Max(1, (int)Math.Ceiling(largestGroup / 2d));
            var slotWidth = extents.Width / slotCount;
            var range = maximum - minimum;
            var traceColors = new[]
            {{
                Colors.Red, Colors.DeepSkyBlue, Colors.Orange, Colors.LimeGreen,
                Colors.Magenta, Colors.Gold, Colors.Cyan, Colors.MediumPurple,
            }};

            for (var groupIndex = 0; groupIndex < groups.Count; groupIndex++)
            {{
                var items = groups[groupIndex].ToList();
                var halfCount = Math.Max(1, (int)Math.Ceiling(items.Count / 2d));
                for (var family = 0; family < 2; family++)
                {{
                    var points = new List<Point>();
                    for (var localIndex = 0; localIndex < items.Count; localIndex++)
                    {{
                        var itemFamily = PairCursorPointsByHalf ? localIndex / halfCount : localIndex % 2;
                        if (itemFamily != family) continue;
                        var slot = PairCursorPointsByHalf ? localIndex % halfCount : localIndex / 2;
                        var x = (slot + 0.5d) * slotWidth;
                        var y = extents.Height - (((items[localIndex].CurrentValue - minimum) / range) * extents.Height);
                        points.Add(new Point(x, y));
                    }}

                    var color = traceColors[((groupIndex * 2) + family) % traceColors.Length];
                    var brush = new SolidColorBrush(color);
                    var pen = new Pen(brush, 1.5d);
                    for (var pointIndex = 1; pointIndex < points.Count; pointIndex++)
                    {{
                        drawingContext.DrawLine(pen, points[pointIndex - 1], points[pointIndex]);
                    }}
                    foreach (var point in points)
                    {{
                        drawingContext.DrawEllipse(brush, new Pen(Brushes.White, 1d), point, 4d, 4d);
                    }}
                }}
            }}

            var labels = groups[0].ToList();
            var categories = new List<string>();
            for (var slot = 0; slot < slotCount; slot++)
            {{
                var firstIndex = PairCursorPointsByHalf ? slot : slot * 2;
                categories.Add(firstIndex < labels.Count ? ExtractSignalIndex(labels[firstIndex].Name) : string.Empty);
            }}
            this.DrawValueAndCategoryAxes(drawingContext, extents, minimum, maximum, categories, false);
        }}

        private static string ExtractSignalIndex(string label)
        {{
            var match = Regex.Match(label ?? string.Empty, @"\\(?(\\d+)\\)?(?:[^0-9]*)$");
            return match.Success && int.TryParse(match.Groups[1].Value, out var index)
                ? index.ToString(CultureInfo.InvariantCulture)
                : label;
        }}

        private void DrawTimeAxes(DrawingContext drawingContext, Size extents,
            long start, long end, double minimum, double maximum)
        {{
            for (var tick = 0; tick <= 5; tick++)
            {{
                var fraction = tick / 5d;
                var timestamp = start + (long)((end - start) * fraction);
                var time = TimeSpan.FromTicks(timestamp / 100);
                this.DrawTickLabel(drawingContext,
                    time.ToString(@"hh\\:mm\\:ss\\.fff", CultureInfo.InvariantCulture),
                    new Point(extents.Width * fraction, extents.Height), true, extents);
                var value = maximum - ((maximum - minimum) * fraction);
                this.DrawTickLabel(drawingContext, FormatNumber(value),
                    new Point(0, extents.Height * fraction), false, extents);
            }}
        }}

        private void DrawNumericAxes(DrawingContext drawingContext, Size extents,
            double minimumX, double maximumX, double minimumY, double maximumY)
        {{
            for (var tick = 0; tick <= 5; tick++)
            {{
                var fraction = tick / 5d;
                this.DrawTickLabel(drawingContext,
                    FormatNumber(minimumX + ((maximumX - minimumX) * fraction)),
                    new Point(extents.Width * fraction, extents.Height), true, extents);
                this.DrawTickLabel(drawingContext,
                    FormatNumber(maximumY - ((maximumY - minimumY) * fraction)),
                    new Point(0, extents.Height * fraction), false, extents);
            }}
        }}

        private void DrawValueAndCategoryAxes(DrawingContext drawingContext, Size extents,
            double minimum, double maximum, IReadOnlyList<string> categories, bool overlaid)
        {{
            for (var tick = 0; tick <= 5; tick++)
            {{
                var fraction = tick / 5d;
                this.DrawTickLabel(drawingContext,
                    FormatNumber(maximum - ((maximum - minimum) * fraction)),
                    new Point(0, extents.Height * fraction), false, extents);
            }}

            if (overlaid)
            {{
                this.DrawTickLabel(drawingContext, "Overlaid parameters",
                    new Point(extents.Width / 2d, extents.Height), true, extents);
                return;
            }}

            var slotWidth = extents.Width / Math.Max(1, categories.Count);
            var step = Math.Max(1, (int)Math.Ceiling(42d / Math.Max(1d, slotWidth)));
            for (var index = 0; index < categories.Count; index += step)
            {{
                var label = categories[index];

                label = ExtractSignalIndex(label);

                this.DrawTickLabel(drawingContext, label,
                    new Point((index + 0.5d) * slotWidth, extents.Height), true, extents);
            }}
        }}

        private static void GetCenteredNiceBounds(IReadOnlyList<double> values, bool includeZero,
            out double minimum, out double maximum)
        {{
            var average = values.Average();
            var maximumDeviation = values.Max(value => Math.Abs(value - average));
            if (includeZero)
            {{
                maximumDeviation = Math.Max(maximumDeviation, Math.Abs(average));
            }}

            var step = NiceNumber(Math.Max(double.Epsilon, maximumDeviation / 2.5d));
            var center = Math.Round(average / (step / 2d)) * (step / 2d);
            while (values.Any(value => Math.Abs(value - center) > 2.5d * step) ||
                (includeZero && Math.Abs(center) > 2.5d * step))
            {{
                step = NiceNumber(step * 1.01d);
                center = Math.Round(average / (step / 2d)) * (step / 2d);
            }}

            minimum = center - (2.5d * step);
            maximum = center + (2.5d * step);
        }}

        private static double NiceNumber(double value)
        {{
            var exponent = Math.Floor(Math.Log10(value));
            var fraction = value / Math.Pow(10d, exponent);
            var niceFraction = fraction <= 1d ? 1d : fraction <= 2d ? 2d : fraction <= 5d ? 5d : 10d;
            return niceFraction * Math.Pow(10d, exponent);
        }}

        private void DrawTickLabel(DrawingContext drawingContext, string text, Point anchor,
            bool horizontal, Size extents)
        {{
            var formatted = new FormattedText(
                text,
                CultureInfo.InvariantCulture,
                FlowDirection.LeftToRight,
                new Typeface("Segoe UI"),
                10d,
                Brushes.White,
                1d);
            var x = horizontal
                ? Math.Max(2d, Math.Min(extents.Width - formatted.Width - 2d,
                    anchor.X - (formatted.Width / 2d)))
                : 3d;
            var y = horizontal
                ? Math.Max(0d, anchor.Y - formatted.Height - 2d)
                : Math.Max(0d, Math.Min(extents.Height - formatted.Height,
                    anchor.Y - (formatted.Height / 2d)));
            drawingContext.DrawText(formatted, new Point(x, y));
        }}

        private static string FormatNumber(double value) =>
            value.ToString("G5", CultureInfo.InvariantCulture);

    }}
}}
'''

CUSTOM_GRAPH_RENDERER_TEMPLATE = '''using System.Collections.Generic;
using System.Windows;
using System.Windows.Media;

namespace {namespace}
{{
    public sealed class CustomGraphRenderer
    {{
        public void Draw(DrawingContext drawingContext, Size extents, IReadOnlyList<GraphSeries> series)
        {{
            // TODO: Draw any custom visualization using the supplied series and WPF DrawingContext.
            // Example: drawingContext.DrawLine(new Pen(Brushes.DeepSkyBlue, 2), start, end);
        }}
    }}
}}
'''

COMPUTED_GRAPH_SERIES_TEMPLATE = '''using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows.Media;

namespace {namespace}
{{
    public static class ComputedGraphSeriesFactory
    {{
        public static IEnumerable<GraphSeries> Create(IReadOnlyList<GraphSeries> source)
        {{
            if (source.Count < 2)
            {{
                yield break;
            }}

            var first = source[0];
            var second = source[1];
            var count = Math.Min(first.Values.Count, second.Values.Count);
{computed_blocks}
        }}

        private static double SafeRatio(double left, double right) =>
            Math.Abs(right) < double.Epsilon ? double.NaN : left / right;
    }}
}}
'''

VIEW_XAML_HEADER = '''<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
             xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
             xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
             xmlns:d="http://schemas.microsoft.com/expression/blend/2008"
             mc:Ignorable="d"
             d:DesignHeight="450" d:DesignWidth="800"'''

ATLAS_THEME_RESOURCES = '''
    <UserControl.Resources>
        <BooleanToVisibilityConverter x:Key="BoolToVisibilityConverter" />
        <SolidColorBrush x:Key="PageBrush" Color="#10151C" />
        <SolidColorBrush x:Key="SurfaceBrush" Color="#18212B" />
        <SolidColorBrush x:Key="RaisedSurfaceBrush" Color="#202C38" />
        <SolidColorBrush x:Key="BorderBrush" Color="#344454" />
        <SolidColorBrush x:Key="AccentBrush" Color="#39C5F3" />
        <SolidColorBrush x:Key="PrimaryTextBrush" Color="#F2F7FA" />
        <SolidColorBrush x:Key="SecondaryTextBrush" Color="#9FB0BD" />
        <Style TargetType="Button">
            <Setter Property="Background" Value="{{StaticResource AccentBrush}}" />
            <Setter Property="Foreground" Value="#081116" />
            <Setter Property="BorderThickness" Value="0" />
            <Setter Property="FontWeight" Value="SemiBold" />
            <Setter Property="Padding" Value="14,7" />
            <Setter Property="Margin" Value="0,0,8,0" />
            <Setter Property="Cursor" Value="Hand" />
        </Style>
        <Style TargetType="TextBox">
            <Setter Property="Background" Value="{{StaticResource RaisedSurfaceBrush}}" />
            <Setter Property="Foreground" Value="{{StaticResource PrimaryTextBrush}}" />
            <Setter Property="BorderBrush" Value="{{StaticResource BorderBrush}}" />
            <Setter Property="CaretBrush" Value="{{StaticResource AccentBrush}}" />
            <Setter Property="Padding" Value="8,5" />
        </Style>
        <Style TargetType="CheckBox">
            <Setter Property="Foreground" Value="{{StaticResource PrimaryTextBrush}}" />
        </Style>
        <Style x:Key="CardStyle" TargetType="Border">
            <Setter Property="Background" Value="{{StaticResource SurfaceBrush}}" />
            <Setter Property="BorderBrush" Value="{{StaticResource BorderBrush}}" />
            <Setter Property="BorderThickness" Value="1" />
            <Setter Property="CornerRadius" Value="8" />
            <Setter Property="Padding" Value="14" />
            <Setter Property="Margin" Value="6" />
        </Style>
        <Style x:Key="TitleStyle" TargetType="TextBlock">
            <Setter Property="Foreground" Value="{{StaticResource PrimaryTextBrush}}" />
            <Setter Property="FontSize" Value="14" />
            <Setter Property="FontWeight" Value="SemiBold" />
        </Style>
        <Style x:Key="MetricStyle" TargetType="TextBlock">
            <Setter Property="Foreground" Value="{{StaticResource AccentBrush}}" />
            <Setter Property="FontSize" Value="26" />
            <Setter Property="FontWeight" Value="Light" />
        </Style>
        <Style x:Key="CaptionStyle" TargetType="TextBlock">
            <Setter Property="Foreground" Value="{{StaticResource SecondaryTextBrush}}" />
            <Setter Property="FontSize" Value="11" />
        </Style>
    </UserControl.Resources>
'''

VIEW_XAML_TEMPLATE = VIEW_XAML_HEADER + '''
             x:Class="{namespace}.{view_class}">''' + ATLAS_THEME_RESOURCES + '''    <Grid Background="{{StaticResource PageBrush}}">
    <ScrollViewer HorizontalScrollBarVisibility="Disabled" VerticalScrollBarVisibility="Auto">
        <DockPanel>
            <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="12,12,12,6">
{command_buttons}            </StackPanel>
            <ItemsControl ItemsSource="{{Binding Parameters}}" Margin="6">
            <ItemsControl.ItemsPanel>
                <ItemsPanelTemplate>
                    <UniformGrid Columns="2" />
                </ItemsPanelTemplate>
            </ItemsControl.ItemsPanel>
            <ItemsControl.ItemTemplate>
                <DataTemplate>
                    <Border Style="{{StaticResource CardStyle}}">
                        <StackPanel>
                            <TextBlock Text="{{Binding Name}}" Style="{{StaticResource TitleStyle}}" />
                            <TextBlock Text="{{Binding Value, StringFormat=F3}}" Style="{{StaticResource MetricStyle}}" Margin="0,8,0,4" />
                            <TextBlock Text="{{Binding Description}}" Style="{{StaticResource CaptionStyle}}" TextWrapping="Wrap" />
                        </StackPanel>
                    </Border>
                </DataTemplate>
            </ItemsControl.ItemTemplate>
        </ItemsControl>
        </DockPanel>
    </ScrollViewer>
    </Grid>
</UserControl>
'''

ASSEMBLY_INFO_TEMPLATE = '''using System.Reflection;
using System.Runtime.InteropServices;

[assembly: AssemblyTitle("{title}")]
[assembly: AssemblyDescription("{description}")]
[assembly: AssemblyProduct("ATLAS Display Plugin")]
[assembly: ComVisible(false)]
[assembly: Guid("{assembly_guid}")]
'''

DEBUG_USER_SETTINGS_TEMPLATE = r'''<Project ToolsVersion="Current" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
    <PropertyGroup Condition="'$(Configuration)|$(Platform)' == 'Debug|x64'">
        <StartAction>Program</StartAction>
        <StartProgram>{atlas_host_path}</StartProgram>
    </PropertyGroup>
</Project>
'''

BASIC_VIEW_XAML_TEMPLATE = VIEW_XAML_HEADER + '''
             x:Class="{namespace}.{view_class}">''' + ATLAS_THEME_RESOURCES + '''    <Grid Background="{{StaticResource PageBrush}}" Margin="0">
{basic_content}
    </Grid>
</UserControl>
'''

TIMEBASE_VIEW_XAML_TEMPLATE = VIEW_XAML_HEADER + '''
             x:Class="{namespace}.{view_class}">''' + ATLAS_THEME_RESOURCES + '''    <Grid Background="{{StaticResource PageBrush}}">
    <ScrollViewer HorizontalScrollBarVisibility="Disabled" VerticalScrollBarVisibility="Auto">
        <DockPanel>
            <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="12,12,12,6">
{command_buttons}            </StackPanel>
            <ItemsControl ItemsSource="{{Binding Series}}">
            <ItemsControl.ItemTemplate>
                <DataTemplate>
                    <Border Style="{{StaticResource CardStyle}}">
                        <StackPanel>
                            <TextBlock Text="{{Binding Name}}" Style="{{StaticResource TitleStyle}}" />
{current_value_text}
                            <TextBlock Text="{{Binding SampleCount, StringFormat='{{0}} samples'}}" Style="{{StaticResource CaptionStyle}}" Margin="0,6,0,0" />
                            <TextBlock Text="{{Binding Minimum, StringFormat='Minimum  {{0:F3}}'}}" Style="{{StaticResource CaptionStyle}}" />
                            <TextBlock Text="{{Binding Maximum, StringFormat='Maximum  {{0:F3}}'}}" Style="{{StaticResource CaptionStyle}}" />
                        </StackPanel>
                    </Border>
                </DataTemplate>
            </ItemsControl.ItemTemplate>
            </ItemsControl>
        </DockPanel>
    </ScrollViewer>
    </Grid>
</UserControl>
'''

TIME_GRAPH_VIEW_XAML_TEMPLATE = VIEW_XAML_HEADER + '''
             xmlns:displayPluginLibrary="clr-namespace:DisplayPluginLibrary;assembly=DisplayPluginLibrary"
             x:Class="{namespace}.{view_class}">''' + ATLAS_THEME_RESOURCES + '''    <DockPanel Background="{{StaticResource PageBrush}}">
        <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="12,12,12,6">
{command_buttons}            <CheckBox Content="Show Legend" IsChecked="{{Binding ShowLegend}}" VerticalAlignment="Center" Margin="8,0,0,0" />
        </StackPanel>
{graph_title_block}
        <Grid>
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="3*" />
                <ColumnDefinition Width="Auto" />
            </Grid.ColumnDefinitions>
            <Border Style="{{StaticResource CardStyle}}" Padding="4">
                <Grid>
                    <displayPluginLibrary:VisualLayer x:Name="GraphVisualLayer" />
                    <displayPluginLibrary:VisualLayer x:Name="CursorVisualLayer" />
                </Grid>
            </Border>
            <ScrollViewer Grid.Column="1" Margin="0,6,6,6" VerticalScrollBarVisibility="Auto" Width="240"
                          Visibility="{{Binding ShowLegend, Converter={{StaticResource BoolToVisibilityConverter}}}}">
                <ItemsControl ItemsSource="{{Binding Series}}">
                    <ItemsControl.ItemTemplate>
                        <DataTemplate>
                            <Border Background="{{StaticResource SurfaceBrush}}" BorderBrush="{{StaticResource BorderBrush}}" BorderThickness="0,0,0,1" Padding="12">
                                <StackPanel>
                                    <TextBlock Text="{{Binding Name}}" Style="{{StaticResource TitleStyle}}" />
                                    <TextBlock Text="{{Binding Unit, StringFormat='Units: {{0}}'}}" Style="{{StaticResource CaptionStyle}}" Margin="0,2,0,6" />
{current_value_text}
{graph_statistics}
                                </StackPanel>
                            </Border>
                        </DataTemplate>
                    </ItemsControl.ItemTemplate>
                </ItemsControl>
            </ScrollViewer>
        </Grid>
    </DockPanel>
</UserControl>
'''

BASIC_PLACEHOLDER_CONTENT = '''            <Border Style="{{StaticResource CardStyle}}"
                    VerticalAlignment="Center" HorizontalAlignment="Center" Padding="32,24">
                <StackPanel>
                    <TextBlock Text="{view_class}" Style="{{StaticResource TitleStyle}}"
                               FontSize="22" HorizontalAlignment="Center" />
                    <Border Height="3" Width="48" Background="{{StaticResource AccentBrush}}"
                            CornerRadius="2" Margin="0,12,0,0" />
                </StackPanel>
            </Border>'''

BASIC_ITEM_COLLECTION_CONTENT = '''            <ItemsControl ItemsSource="{Binding Items}" Margin="6">
                <ItemsControl.ItemTemplate>
                    <DataTemplate>
                        <Border Style="{StaticResource CardStyle}">
                            <TextBlock Text="{Binding Name}" Style="{StaticResource TitleStyle}" />
                        </Border>
                    </DataTemplate>
                </ItemsControl.ItemTemplate>
            </ItemsControl>'''

BASIC_LAYOUTS = ('text', 'form', 'list', 'table', 'blank')


def build_property_control(spec):
    label = html.escape(spec.get('display_name') or command_display_label(spec['name']), quote=True)
    name = spec['name']
    if spec.get('read_only', False):
        editor = f'<TextBlock Text="{{Binding {name}}}" Foreground="{{StaticResource PrimaryTextBrush}}" />'
    elif spec['type'] == 'bool':
        editor = f'<CheckBox IsChecked="{{Binding {name}}}" VerticalAlignment="Center" />'
    else:
        editor = (
            f'<TextBox Text="{{Binding {name}, UpdateSourceTrigger=PropertyChanged}}" '
            'MinWidth="180" />'
        )
    return (
        '            <Grid Margin="0,6">\n'
        '                <Grid.ColumnDefinitions>\n'
        '                    <ColumnDefinition Width="Auto" />\n'
        '                    <ColumnDefinition Width="*" />\n'
        '                </Grid.ColumnDefinitions>\n'
        f'                <TextBlock Text="{label}" Style="{{StaticResource CaptionStyle}}" Margin="0,0,16,0" VerticalAlignment="Center" />\n'
        f'                <ContentControl Grid.Column="1">{editor}</ContentControl>\n'
        '            </Grid>\n'
    )


def build_basic_layout_content(layout, view_class, command_buttons, display_property_specs=None,
                               collection_name='Items', item_display_field='Name'):
    if layout not in BASIC_LAYOUTS:
        raise ValueError(f'Unknown basic view layout: {layout}')
    commands = (
        '        <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="12,12,12,6">\n'
        f'{command_buttons}'
        '        </StackPanel>\n'
    ) if command_buttons else ''
    if layout == 'blank':
        return commands.rstrip()
    if layout == 'list':
        body = BASIC_ITEM_COLLECTION_CONTENT.replace(
            '{Binding Items}', f'{{Binding {collection_name}}}'
        ).replace('{Binding Name}', f'{{Binding {item_display_field}}}')
    elif layout == 'table':
        body = f'        <DataGrid ItemsSource="{{Binding {collection_name}}}" AutoGenerateColumns="True" Margin="12" Background="{{StaticResource SurfaceBrush}}" Foreground="{{StaticResource PrimaryTextBrush}}" BorderBrush="{{StaticResource BorderBrush}}" />'
    elif layout == 'form':
        controls = ''.join(build_property_control(spec) for spec in (display_property_specs or []))
        if not controls:
            controls = '            <!-- Add display properties to generate controls. -->\n'
        body = f'        <Border Style="{{StaticResource CardStyle}}" Margin="12">\n            <StackPanel>\n{controls}            </StackPanel>\n        </Border>'
    else:
        body = BASIC_PLACEHOLDER_CONTENT.format(view_class=view_class)
    return f'        <DockPanel>\n{commands}{body}\n        </DockPanel>'

COMPARE_VIEW_XAML_TEMPLATE = VIEW_XAML_HEADER + '''
             x:Class="{namespace}.{view_class}">''' + ATLAS_THEME_RESOURCES + '''    <Grid Background="{{StaticResource PageBrush}}">
    <ScrollViewer HorizontalScrollBarVisibility="Disabled" VerticalScrollBarVisibility="Auto">
        <DockPanel>
            <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="12,12,12,6">
{command_buttons}            </StackPanel>
            <ItemsControl ItemsSource="{{Binding Rows}}">
            <ItemsControl.ItemTemplate>
                <DataTemplate>
                    <Border Style="{{StaticResource CardStyle}}">
                        <StackPanel>
                            <TextBlock Text="{{Binding Name}}" Style="{{StaticResource TitleStyle}}" />
                            <ItemsControl ItemsSource="{{Binding SessionValues}}">
                                <ItemsControl.ItemsPanel>
                                    <ItemsPanelTemplate>
                                        <StackPanel Orientation="Horizontal" />
                                    </ItemsPanelTemplate>
                                </ItemsControl.ItemsPanel>
                                <ItemsControl.ItemTemplate>
                                    <DataTemplate>
                                        <Border Background="{{StaticResource RaisedSurfaceBrush}}" CornerRadius="6" Padding="10,7" Margin="0,8,8,0">
                                        <StackPanel>
                                            <TextBlock Text="{{Binding SessionName}}" Style="{{StaticResource CaptionStyle}}" />
                                            <TextBlock Text="{{Binding Value, StringFormat=F3}}"
                                                       Style="{{StaticResource MetricStyle}}" FontSize="20" />
                                        </StackPanel>
                                        </Border>
                                    </DataTemplate>
                                </ItemsControl.ItemTemplate>
                            </ItemsControl>
                        </StackPanel>
                    </Border>
                </DataTemplate>
            </ItemsControl.ItemTemplate>
            </ItemsControl>
        </DockPanel>
    </ScrollViewer>
    </Grid>
</UserControl>
'''

VIEW_CODEBEHIND_TEMPLATE = '''using System.Windows.Controls;

namespace {namespace}
{{
    public partial class {view_class} : UserControl
    {{
        public {view_class}()
        {{
            InitializeComponent();
        }}
    }}
}}
'''

SLN_TEMPLATE = r'''Microsoft Visual Studio Solution File, Format Version 12.00
# Visual Studio Version 17
VisualStudioVersion = 17.0.31903.59
MinimumVisualStudioVersion = 10.0.40219.1
Project("{{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}}") = "{project_name}", "{project_name}\{project_name}.csproj", "{{{project_guid}}}"
EndProject
{library_project_entry}
Global
	GlobalSection(SolutionConfigurationPlatforms) = preSolution
		Debug|x64 = Debug|x64
		Release|x64 = Release|x64
	EndGlobalSection
	GlobalSection(ProjectConfigurationPlatforms) = postSolution
		{{{project_guid}}}.Debug|x64.ActiveCfg = Debug|x64
		{{{project_guid}}}.Debug|x64.Build.0 = Debug|x64
		{{{project_guid}}}.Release|x64.ActiveCfg = Release|x64
		{{{project_guid}}}.Release|x64.Build.0 = Release|x64
{library_configurations}
	EndGlobalSection
EndGlobal
'''


def settings_path():
    settings_root = os.environ.get('APPDATA')
    if not settings_root:
        settings_root = os.environ.get('XDG_CONFIG_HOME')
    if not settings_root:
        settings_root = os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(settings_root, 'atlas-display-plugin-generator', 'settings.json')


def load_settings():
    try:
        with open(settings_path(), 'r', encoding='utf-8') as stream:
            settings = json.load(stream)
            return settings if isinstance(settings, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_settings(settings):
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = f'{path}.tmp'
    with open(temporary_path, 'w', encoding='utf-8', newline='') as stream:
        json.dump(settings, stream, indent=2)
        stream.write('\n')
    os.replace(temporary_path, path)


def clear_settings():
    try:
        os.remove(settings_path())
    except FileNotFoundError:
        pass


def default_output_folder():
    return load_settings().get('output_folder', '')


def default_workspace_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def normalize_plugin_name(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError('Plugin name must be a valid C# identifier (letters, numbers, and underscores only).')
    # ATLAS only loads assemblies whose name contains "Plugin".
    if 'plugin' not in name.lower():
        name += 'CustomPlugin'
    return name


def to_camel_case(identifier):
    return identifier[:1].lower() + identifier[1:] if identifier else identifier


def build_atlas_parameter(identifier, existing_identifiers=None):
    identifier = (identifier or '').strip()
    if not identifier:
        raise ValueError('ATLAS parameter identifier is required.')
    if existing_identifiers and identifier in existing_identifiers:
        raise ValueError(f'ATLAS parameter "{identifier}" already exists.')
    return identifier


DISPLAY_PROPERTY_TYPES = {
    'String': 'string',
    'Integer': 'int',
    'Long integer': 'long',
    'Number': 'double',
    'Single-precision number': 'float',
    'Decimal': 'decimal',
    'Boolean': 'bool',
    'String list': 'List<string>',
    'Integer list': 'List<int>',
    'Number list': 'List<double>',
    'Boolean list': 'List<bool>',
}

DISPLAY_PROPERTY_ACTIONS = {
    'No automatic action': 'none',
    'Refresh current value': 'refresh-current',
    'Refresh visible range': 'refresh-visible',
    'Refresh current value and visible range': 'refresh-all',
}


def parse_display_property_default(property_type, default_value):
    text = str(default_value or '').strip()
    if property_type == 'string':
        return text
    if property_type in ('int', 'long'):
        if not text:
            return 0
        try:
            return int(text)
        except ValueError as error:
            raise ValueError('Integer property default must be a whole number.') from error
    if property_type in ('double', 'float'):
        if not text:
            return 0.0
        try:
            value = float(text)
        except ValueError as error:
            raise ValueError('Number property default must be numeric.') from error
        if not math.isfinite(value):
            raise ValueError('Number property default must be finite.')
        return value
    if property_type == 'decimal':
        if not text:
            return '0'
        try:
            value = Decimal(text)
        except InvalidOperation as error:
            raise ValueError('Decimal property default must be numeric.') from error
        if not value.is_finite():
            raise ValueError('Decimal property default must be finite.')
        return str(value)
    if property_type == 'bool':
        if not text:
            return False
        normalized = text.lower()
        if normalized in ('true', 'yes', '1'):
            return True
        if normalized in ('false', 'no', '0'):
            return False
        raise ValueError('Boolean property default must be true or false.')
    if property_type.startswith('List<'):
        if not text:
            return []
        try:
            values = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError('List defaults must be a JSON array, for example [1, 2, 3].') from error
        if not isinstance(values, list):
            raise ValueError('List defaults must be a JSON array, for example [1, 2, 3].')
        item_type = property_type[5:-1]
        if item_type == 'string' and not all(isinstance(value, str) for value in values):
            raise ValueError('String list defaults may only contain strings.')
        if item_type == 'int' and not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            raise ValueError('Integer list defaults may only contain whole numbers.')
        if item_type == 'double' and not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            for value in values
        ):
            raise ValueError('Number list defaults may only contain finite numbers.')
        if item_type == 'bool' and not all(isinstance(value, bool) for value in values):
            raise ValueError('Boolean list defaults may only contain true or false.')
        return values
    raise ValueError(f'Unsupported display property type: {property_type}')


def build_display_property_spec(name, display_name='', category='', description='', order='', persisted=False,
                                browsable=True, property_type='string', default_value='', change_action='none',
                                read_only=False, existing_names=None):
    name = (name or '').strip()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError(f'Display property name "{name}" must be a valid C# identifier.')
    if existing_names and name in existing_names:
        raise ValueError(f'A display property named "{name}" already exists.')
    display_name = (display_name or '').strip()
    category = (category or '').strip()
    description = (description or '').strip()
    if property_type not in DISPLAY_PROPERTY_TYPES.values():
        raise ValueError(f'Unsupported display property type: {property_type}')
    if change_action not in DISPLAY_PROPERTY_ACTIONS.values():
        raise ValueError(f'Unsupported display property change action: {change_action}')
    if read_only and change_action != 'none':
        raise ValueError('A read-only display property cannot run a change action.')
    parsed_default = parse_display_property_default(property_type, default_value)
    order_text = str(order).strip()
    if not order_text:
        order_value = None
    elif re.fullmatch(r'-?\d+', order_text):
        order_value = int(order_text)
    else:
        raise ValueError(f'Display property "{name}" order must be an integer.')
    return {
        'name': name,
        'display_name': display_name,
        'category': category,
        'description': description,
        'order': order_value,
        'persisted': bool(persisted),
        'browsable': bool(browsable),
        'type': property_type,
        'default': parsed_default,
        'change_action': change_action,
        'read_only': bool(read_only),
    }


def escape_csharp_string(value):
    return value.replace('\\', '\\\\').replace('"', '\\"')


def build_display_property_field(spec):
    field = '_' + to_camel_case(spec['name'])
    return f'        private {spec["type"]} {field} = {display_property_default_literal(spec)};'


def display_property_default_literal(spec):
    value = spec['default']
    if spec['type'] == 'string':
        return f'"{escape_csharp_string(value)}"'
    if spec['type'] == 'int':
        return str(value)
    if spec['type'] == 'long':
        return f'{value}L'
    if spec['type'] == 'double':
        return f'{format(value, ".15g")}d'
    if spec['type'] == 'float':
        return f'{format(value, ".8g")}f'
    if spec['type'] == 'decimal':
        return f'{value}m'
    if spec['type'] == 'bool':
        return 'true' if value else 'false'
    if spec['type'].startswith('List<'):
        item_type = spec['type'][5:-1]
        literals = [display_property_default_literal({'type': item_type, 'default': item}) for item in value]
        return f'new {spec["type"]} {{ {", ".join(literals)} }}'
    raise ValueError(f'Unsupported display property type: {spec["type"]}')


def build_display_property(spec):
    field = '_' + to_camel_case(spec['name'])
    default_value = display_property_default_literal(spec)
    action_statements = {
        'none': '',
        'refresh-current': '                    this.MakeDataRequests(true, false);\n',
        'refresh-visible': '                    this.MakeDataRequests(false, true);\n',
        'refresh-all': '                    this.MakeDataRequests(true, true);\n',
    }
    action_statement = action_statements[spec.get('change_action', 'none')]
    if spec.get('read_only', False):
        accessor = (
            f'            get => this.{field} = this.ReadProperty({default_value});\n'
            if spec['persisted'] else
            f'            get => this.{field};\n'
        )
    elif spec['persisted'] or action_statement:
        save_statement = '                    this.SaveProperty(value);\n' if spec['persisted'] else ''
        accessor = (
            f'            get => this.{field} = this.ReadProperty({default_value});\n'
            if spec['persisted'] else
            f'            get => this.{field};\n'
        ) + (
            '            set\n'
            '            {\n'
            f'                if (this.SetProperty(ref this.{field}, value))\n'
            '                {\n'
            f'{save_statement}'
            f'{action_statement}'
            '                }\n'
            '            }\n'
        )
    else:
        accessor = (
            f'            get => this.{field};\n'
            f'            set => this.SetProperty(ref this.{field}, value);\n'
        )
    attributes = []
    if spec['category']:
        attributes.append(f'        [Category("{escape_csharp_string(spec["category"])}")]')
    if spec['display_name']:
        attributes.append(f'        [DisplayName("{escape_csharp_string(spec["display_name"])}")]')
    if spec['description']:
        attributes.append(f'        [Description("{escape_csharp_string(spec["description"])}")]')
    if spec['order'] is not None:
        attributes.append(f'        [Display(Order = {spec["order"]})]')
    if not spec['browsable']:
        attributes.append('        [Browsable(false)]')
    attribute_block = ''.join(f'{attribute}\n' for attribute in attributes)
    return (
        f'{attribute_block}'
        f'        public {spec["type"]} {spec["name"]}\n'
        '        {\n'
        f'{accessor}'
        '        }\n'
    )


# Factories/services registered with Autofac, injectable via the ViewModel constructor.
# Namespaces/param names verified against Atlas.DisplayAPI.Examples usage.
SERVICE_DEFINITIONS = {
    'ILogger': {'namespace': 'MAT.Atlas.Api.Core.Diagnostics', 'param': 'logger'},
    'ISignalBus': {'namespace': 'MAT.Atlas.Api.Core.Signals', 'param': 'signalBus'},
    'IDataRequestSignalFactory': {'namespace': 'MAT.Atlas.Client.Platform.Data', 'param': 'dataRequestSignalFactory'},
    'ISessionService': {'namespace': 'MAT.Atlas.Client.Platform.Sessions', 'param': 'sessionService'},
    'ISessionSummaryService': {'namespace': 'MAT.Atlas.Client.Platform.Sessions', 'param': 'sessionSummaryService'},
    'ISessionCursorService': {'namespace': 'MAT.Atlas.Client.Presentation.Services', 'param': 'sessionCursorService'},
}

BEHAVIOR_CURRENT_VALUE = 'Current value at cursor'
BEHAVIOR_VISIBLE_RANGE = 'Visible range data'
BEHAVIOR_CURRENT_AND_RANGE = 'Current value + visible range'
BEHAVIOR_COMPARE_SESSIONS = 'Compare sessions at cursor'
BEHAVIOR_BASIC = 'Basic display'


def behavior_uses_parameters(behavior):
    if behavior in (
        BEHAVIOR_CURRENT_VALUE,
        BEHAVIOR_VISIBLE_RANGE,
        BEHAVIOR_CURRENT_AND_RANGE,
        BEHAVIOR_COMPARE_SESSIONS,
    ):
        return True
    if behavior == BEHAVIOR_BASIC:
        return False
    raise ValueError(f'Unknown plugin behavior: {behavior}')


def validate_display_property_actions(display_property_specs, behavior):
    allowed_actions = {
        BEHAVIOR_BASIC: {'none'},
        BEHAVIOR_CURRENT_VALUE: {'none', 'refresh-current'},
        BEHAVIOR_VISIBLE_RANGE: {'none', 'refresh-visible'},
        BEHAVIOR_CURRENT_AND_RANGE: set(DISPLAY_PROPERTY_ACTIONS.values()),
        BEHAVIOR_COMPARE_SESSIONS: {'none', 'refresh-current'},
    }[behavior]
    for spec in display_property_specs:
        action = spec.get('change_action', 'none')
        if action not in allowed_actions:
            action_label = next(label for label, value in DISPLAY_PROPERTY_ACTIONS.items() if value == action)
            raise ValueError(
                f'Display property "{spec["name"]}" cannot use "{action_label}" '
                f'with the "{behavior}" behavior.'
            )


def build_service_entries(service_names):
    return [
        {'interface': name, 'namespace': SERVICE_DEFINITIONS[name]['namespace'], 'param': SERVICE_DEFINITIONS[name]['param']}
        for name in service_names
        if name in SERVICE_DEFINITIONS
    ]


def build_service_usings(entries):
    namespaces = sorted({entry['namespace'] for entry in entries})
    return ''.join(f'using {namespace};\n' for namespace in namespaces)


def build_service_fields(entries):
    return ''.join(f'        private readonly {entry["interface"]} {entry["param"]};\n' for entry in entries)


def build_basic_service_members(viewmodel_class, entries, command_initializers=''):
    if not entries and not command_initializers:
        return ''
    fields = build_service_fields(entries)
    params = ',\n'.join(f'            {entry["interface"]} {entry["param"]}' for entry in entries)
    assignments = ''.join(f'            this.{entry["param"]} = {entry["param"]};\n' for entry in entries)
    return (
        f'{fields}\n'
        f'        public {viewmodel_class}(\n'
        f'{params})\n'
        '        {\n'
        f'{assignments}'
        f'{command_initializers}'
        '        }\n'
    )


def validate_icon_path(icon_path):
    icon_path = os.path.abspath(icon_path or '')
    if not os.path.isfile(icon_path):
        raise FileNotFoundError('Select a valid PNG icon before generating the plugin.')
    if os.path.splitext(icon_path)[1].lower() != '.png':
        raise ValueError('The plugin icon must be a PNG file.')
    return icon_path


def find_build_tool():
    dotnet_candidates = [
        shutil.which('dotnet'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'dotnet', 'dotnet.exe'),
    ]
    for candidate in dotnet_candidates:
        if candidate and os.path.isfile(candidate):
            result = subprocess.run(
                [candidate, '--list-sdks'],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return 'dotnet', candidate

    msbuild_candidates = [
        shutil.which('msbuild'),
        os.path.join(
            os.environ.get('ProgramFiles(x86)', ''),
            'Microsoft Visual Studio', '2022', 'BuildTools', 'MSBuild', 'Current', 'Bin', 'MSBuild.exe',
        ),
    ]
    for candidate in msbuild_candidates:
        if candidate and os.path.isfile(candidate):
            return 'msbuild', candidate
    return None


def build_generated_plugin(target, build_tool=None):
    target = os.path.abspath(target)
    plugin_name = os.path.basename(target)
    solution_path = os.path.join(target, f'{plugin_name}.sln')
    if not os.path.isfile(solution_path):
        raise FileNotFoundError(f'Generated solution not found: {solution_path}')

    tool = build_tool or find_build_tool()
    if not tool:
        raise RuntimeError('No .NET SDK or MSBuild installation was found. Install the .NET 8 SDK to build plugins.')

    tool_kind, executable = tool
    if tool_kind == 'dotnet':
        command = [
            executable,
            'build',
            solution_path,
            '--configuration',
            'Debug',
            '-p:Platform=x64',
        ]
    elif tool_kind == 'msbuild':
        command = [
            executable,
            solution_path,
            '-restore',
            '-p:Configuration=Debug',
            '-p:Platform=x64',
        ]
    else:
        raise ValueError(f'Unknown build tool: {tool_kind}')

    environment = os.environ.copy()
    environment['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
    environment['DOTNET_SKIP_FIRST_TIME_EXPERIENCE'] = '1'
    result = subprocess.run(
        command,
        cwd=target,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = '\n'.join(filter(None, [result.stdout.strip(), result.stderr.strip()]))
        output_lines = output.splitlines()
        summary = '\n'.join(output_lines[-40:])
        raise RuntimeError(f'Generated plugin build failed:\n\n{summary}')
    return result.stdout


def command_display_label(name):
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', name)


COMMAND_ACTIONS = {
    'Custom code placeholder': 'custom',
    'Toggle Boolean property': 'toggle',
    'Set property value': 'set',
    'Reset property to default': 'reset',
    'Increment numeric property': 'increment',
    'Decrement numeric property': 'decrement',
}


def build_command_spec(name, button_label='', include_button=True, existing_names=None, generate_can_execute=False,
                       generate_log=False, break_when_attached=False, action='custom', target_property='',
                       action_value=''):
    name = (name or '').strip()
    if name.endswith('Command'):
        name = name[:-len('Command')]
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError('Command name must be a valid C# identifier.')
    if existing_names and name in existing_names:
        raise ValueError(f'A command named "{name}" already exists.')
    if action not in COMMAND_ACTIONS.values():
        raise ValueError(f'Unsupported command action: {action}')
    return {
        'name': name,
        'button_label': (button_label or '').strip() or command_display_label(name),
        'include_button': bool(include_button),
        'generate_can_execute': bool(generate_can_execute),
        'generate_log': bool(generate_log),
        'break_when_attached': bool(break_when_attached),
        'action': action,
        'target_property': (target_property or '').strip(),
        'action_value': str(action_value or '').strip(),
    }


def build_command_property(spec):
    return (
        '        [Browsable(false)]\n'
        f'        public ICommand {spec["name"]}Command {{ get; }}\n'
    )


def build_command_initializer(spec):
    can_execute = f', this.Can{spec["name"]}' if spec.get('generate_can_execute', False) else ''
    return (
        f'            this.{spec["name"]}Command = '
        f'new DelegateCommand(this.On{spec["name"]}{can_execute});\n'
    )


def validate_command_actions(command_specs, display_property_specs):
    properties = {spec['name']: spec for spec in display_property_specs}
    numeric_types = {'int', 'long', 'double', 'float', 'decimal'}
    for command in command_specs:
        action = command.get('action', 'custom')
        if action == 'custom':
            continue
        target_name = command.get('target_property', '')
        target = properties.get(target_name)
        if not target:
            raise ValueError(f'Command "{command["name"]}" must target an existing display property.')
        if target.get('read_only', False):
            raise ValueError(f'Command "{command["name"]}" cannot change read-only property "{target_name}".')
        if action == 'toggle' and target['type'] != 'bool':
            raise ValueError(f'Command "{command["name"]}" can only toggle a Boolean property.')
        if action in ('increment', 'decrement') and target['type'] not in numeric_types:
            raise ValueError(f'Command "{command["name"]}" requires a numeric property.')
        if action == 'set':
            command['_action_literal'] = display_property_default_literal({
                'type': target['type'],
                'default': parse_display_property_default(target['type'], command.get('action_value', '')),
            })


def build_command_action_statement(spec, display_properties=None):
    action = spec.get('action', 'custom')
    if action == 'custom':
        return f'            // TODO: Implement {spec["name"]}.\n'
    target = spec['target_property']
    if action == 'toggle':
        expression = f'!this.{target}'
    elif action == 'set':
        expression = spec['_action_literal']
    elif action == 'reset':
        target_spec = {item['name']: item for item in (display_properties or [])}[target]
        expression = display_property_default_literal(target_spec)
    elif action == 'increment':
        expression = f'this.{target} + 1'
    else:
        expression = f'this.{target} - 1'
    return f'            this.{target} = {expression};\n'


def build_command_handler(spec, logger_expression='this.Logger', display_properties=None):
    instrumentation = ''
    if spec.get('generate_log', False):
        instrumentation += f'            {logger_expression}.Trace("Command {spec["name"]} executed.");\n'
    if spec.get('break_when_attached', False):
        instrumentation += (
            '            if (Debugger.IsAttached)\n'
            '            {\n'
            '                Debugger.Break();\n'
            '            }\n'
        )
    handler = (
        f'        private void On{spec["name"]}()\n'
        '        {\n'
        f'{instrumentation}'
        f'{build_command_action_statement(spec, display_properties)}'
        '        }\n'
    )
    if not spec.get('generate_can_execute', False):
        return handler
    return (
        f'{handler}\n'
        f'        private bool Can{spec["name"]}()\n'
        '        {\n'
        f'            // TODO: Return whether {spec["name"]} is currently available.\n'
        '            return true;\n'
        '        }\n'
    )


def build_command_button(spec):
    if not spec['include_button']:
        return ''
    label = html.escape(spec['button_label'], quote=True)
    return (
        f'            <Button Content="{label}" Command="{{Binding {spec["name"]}Command}}" '
        '/>\n'
    )


def build_status_state():
    fields = (
        '        private bool isBusy;\n'
        '        private string statusMessage = string.Empty;\n'
        '        private string errorMessage = string.Empty;\n'
    )
    properties = '''        [Browsable(false)]
        public bool IsBusy
        {
            get => this.isBusy;
            private set => this.SetProperty(ref this.isBusy, value);
        }

        [Browsable(false)]
        public string StatusMessage
        {
            get => this.statusMessage;
            private set => this.SetProperty(ref this.statusMessage, value);
        }

        [Browsable(false)]
        public string ErrorMessage
        {
            get => this.errorMessage;
            private set => this.SetProperty(ref this.errorMessage, value);
        }
'''
    return fields, properties

GRAPH_VIEW_CODEBEHIND_TEMPLATE = '''using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.ComponentModel;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace {namespace}
{{
    public partial class {view_class} : UserControl
    {{
        private static readonly bool UsesTimeAxis = {uses_time_axis};
        private static readonly Color[] Palette =
        {{
            Colors.DeepSkyBlue, Colors.Orange, Colors.LimeGreen, Colors.Magenta,
            Colors.Gold, Colors.Cyan, Colors.Red, Colors.MediumPurple,
        }};
        private readonly GraphRenderer graphRenderer = new GraphRenderer();
        private {viewmodel_class} viewModel;
        private long? loadedStart;
        private long? loadedEnd;
        private long? viewportStart;
        private long? viewportEnd;
        private bool movingCursor;
        private bool panningRange;
        private double panOriginX;
        private long panOriginStart;
        private long panOriginEnd;

        public {view_class}()
        {{
            this.InitializeComponent();
            this.DataContextChanged += this.OnDataContextChanged;
            this.SizeChanged += (sender, args) => this.Redraw();
            this.GraphVisualLayer.MouseLeftButtonDown += this.OnGraphMouseLeftButtonDown;
            this.GraphVisualLayer.MouseMove += this.OnGraphMouseMove;
            this.GraphVisualLayer.MouseLeftButtonUp += this.OnGraphMouseLeftButtonUp;
            this.GraphVisualLayer.MouseRightButtonDown += this.OnGraphMouseRightButtonDown;
            this.GraphVisualLayer.MouseRightButtonUp += this.OnGraphMouseRightButtonUp;
            this.GraphVisualLayer.MouseWheel += this.OnGraphMouseWheel;
        }}

        private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs args)
        {{
            this.Detach();
            this.viewModel = args.NewValue as {viewmodel_class};
            if (this.viewModel != null)
            {{
                this.viewModel.Series.CollectionChanged += this.OnSeriesCollectionChanged;
                this.AttachSeries();
            }}

            this.Redraw();
        }}

        private void OnSeriesCollectionChanged(object sender, NotifyCollectionChangedEventArgs args)
        {{
            this.AttachSeries();
            this.Redraw();
        }}

        private void AttachSeries()
        {{
            if (this.viewModel == null)
            {{
                return;
            }}

            foreach (var item in this.viewModel.Series)
            {{
                item.PropertyChanged -= this.OnSeriesPropertyChanged;
                item.PropertyChanged += this.OnSeriesPropertyChanged;
            }}
        }}

        private void OnSeriesPropertyChanged(object sender, PropertyChangedEventArgs args)
        {{
            if (args.PropertyName == nameof(TimebaseSeriesViewModel.Values) ||
                args.PropertyName == nameof(TimebaseSeriesViewModel.Timestamps) ||
                args.PropertyName == nameof(TimebaseSeriesViewModel.CurrentTimestamp))
            {{
                this.Redraw();
            }}
        }}

        private void Detach()
        {{
            if (this.viewModel == null)
            {{
                return;
            }}

            this.viewModel.Series.CollectionChanged -= this.OnSeriesCollectionChanged;
            foreach (var item in this.viewModel.Series)
            {{
                item.PropertyChanged -= this.OnSeriesPropertyChanged;
            }}
        }}

        private void Redraw()
        {{
            var visual = this.GraphVisualLayer.Visual;
            var series = this.viewModel?.Series.Select((item, index) => new GraphSeries(
                item.Name,
                item.Timestamps,
                item.Values,
                Palette[index % Palette.Length]{current_value_argument}, item.GraphGroup)).ToList() ?? new List<GraphSeries>();
            this.UpdateLoadedRange(series);
{computed_series_update}
            visual.Draw(context => this.graphRenderer.Draw(
                context, visual.Extents, series, this.viewportStart, this.viewportEnd));
            var cursorVisual = this.CursorVisualLayer.Visual;
            var cursorTimestamp = this.viewModel?.Series.Select(item => item.CurrentTimestamp).FirstOrDefault(value => value.HasValue);
            cursorVisual.Draw(context => this.graphRenderer.DrawCursor(
                context,
                cursorVisual.Extents,
                series,
                cursorTimestamp,
                this.viewportStart,
                this.viewportEnd));
        }}

        private void UpdateLoadedRange(IReadOnlyList<GraphSeries> series)
        {{
            if (!UsesTimeAxis)
            {{
                return;
            }}

            var ranged = series.Where(item => item.Timestamps.Count > 1).ToList();
            if (ranged.Count == 0)
            {{
                this.loadedStart = this.loadedEnd = this.viewportStart = this.viewportEnd = null;
                return;
            }}

            var start = ranged.Min(item => item.Timestamps.First());
            var end = ranged.Max(item => item.Timestamps.Last());
            if (this.loadedStart != start || this.loadedEnd != end)
            {{
                this.loadedStart = this.viewportStart = start;
                this.loadedEnd = this.viewportEnd = end;
            }}
        }}

        private void OnGraphMouseLeftButtonDown(object sender, MouseButtonEventArgs args)
        {{
            if (!UsesTimeAxis)
            {{
                return;
            }}

            this.movingCursor = true;
            this.GraphVisualLayer.CaptureMouse();
            this.MoveCursor(args.GetPosition(this.GraphVisualLayer).X);
            args.Handled = true;
        }}

        private void OnGraphMouseMove(object sender, MouseEventArgs args)
        {{
            if (this.movingCursor && args.LeftButton == MouseButtonState.Pressed)
            {{
                this.MoveCursor(args.GetPosition(this.GraphVisualLayer).X);
                args.Handled = true;
            }}
            else if (this.panningRange && args.RightButton == MouseButtonState.Pressed &&
                this.GraphVisualLayer.ActualWidth > 0)
            {{
                var delta = args.GetPosition(this.GraphVisualLayer).X - this.panOriginX;
                var span = this.panOriginEnd - this.panOriginStart;
                var offset = (long)(-(delta / this.GraphVisualLayer.ActualWidth) * span);
                this.SetViewport(this.panOriginStart + offset, this.panOriginEnd + offset);
                this.Redraw();
                args.Handled = true;
            }}
        }}

        private void OnGraphMouseRightButtonDown(object sender, MouseButtonEventArgs args)
        {{
            if (!UsesTimeAxis || !this.viewportStart.HasValue || !this.viewportEnd.HasValue)
            {{
                return;
            }}

            this.panningRange = true;
            this.panOriginX = args.GetPosition(this.GraphVisualLayer).X;
            this.panOriginStart = this.viewportStart.Value;
            this.panOriginEnd = this.viewportEnd.Value;
            this.GraphVisualLayer.CaptureMouse();
            args.Handled = true;
        }}

        private void OnGraphMouseRightButtonUp(object sender, MouseButtonEventArgs args)
        {{
            if (!this.panningRange)
            {{
                return;
            }}

            this.panningRange = false;
            this.GraphVisualLayer.ReleaseMouseCapture();
            args.Handled = true;
        }}

        private void OnGraphMouseLeftButtonUp(object sender, MouseButtonEventArgs args)
        {{
            if (!this.movingCursor)
            {{
                return;
            }}

            this.MoveCursor(args.GetPosition(this.GraphVisualLayer).X);
            this.movingCursor = false;
            this.GraphVisualLayer.ReleaseMouseCapture();
            args.Handled = true;
        }}

        private void MoveCursor(double x)
        {{
            if (!this.viewportStart.HasValue || !this.viewportEnd.HasValue ||
                this.GraphVisualLayer.ActualWidth <= 0 || this.viewModel == null)
            {{
                return;
            }}

            var fraction = Math.Max(0d, Math.Min(1d, x / this.GraphVisualLayer.ActualWidth));
            var timestamp = this.viewportStart.Value +
                (long)((this.viewportEnd.Value - this.viewportStart.Value) * fraction);
            this.viewModel.MoveCursor(timestamp);
        }}

        private void OnGraphMouseWheel(object sender, MouseWheelEventArgs args)
        {{
            if (!UsesTimeAxis || !this.viewportStart.HasValue || !this.viewportEnd.HasValue ||
                !this.loadedStart.HasValue || !this.loadedEnd.HasValue)
            {{
                return;
            }}

            var start = this.viewportStart.Value;
            var end = this.viewportEnd.Value;
            var span = Math.Max(1L, end - start);
            if ((Keyboard.Modifiers & ModifierKeys.Shift) != 0)
            {{
                var direction = args.Delta > 0 ? -1d : 1d;
                var offset = (long)(span * 0.1d * direction);
                this.SetViewport(start + offset, end + offset);
            }}
            else
            {{
                var factor = args.Delta > 0 ? 0.8d : 1.25d;
                var newSpan = Math.Max(1L, (long)(span * factor));
                var cursorTimestamp = this.viewModel?.Series
                    .Select(item => item.CurrentTimestamp)
                    .FirstOrDefault(value => value.HasValue);
                var anchorTimestamp = cursorTimestamp.HasValue &&
                    cursorTimestamp.Value >= start && cursorTimestamp.Value <= end
                    ? cursorTimestamp.Value
                    : start + (span / 2L);
                var newStart = anchorTimestamp - (newSpan / 2L);
                this.SetViewport(newStart, newStart + newSpan);
            }}

            this.Redraw();
            args.Handled = true;
        }}

        private void SetViewport(long start, long end)
        {{
            var loadedStart = this.loadedStart.Value;
            var loadedEnd = this.loadedEnd.Value;
            var loadedSpan = Math.Max(1L, loadedEnd - loadedStart);
            var span = Math.Min(loadedSpan, Math.Max(1L, end - start));
            start = Math.Max(loadedStart, Math.Min(start, loadedEnd - span));
            this.viewportStart = start;
            this.viewportEnd = start + span;
        }}
    }}
}}
'''


def build_item_field_spec(value):
    parts = [part.strip() for part in str(value or '').split(':', 1)]
    name = parts[0]
    property_type = parts[1].lower() if len(parts) == 2 else 'string'
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError('Item field name must be a valid C# identifier.')
    if property_type not in DISPLAY_PROPERTY_TYPES.values():
        raise ValueError(f'Unsupported item field type: {property_type}')
    return {'name': name, 'type': property_type}


def build_computed_series_spec(value):
    parts = [part.strip() for part in str(value or '').split(':', 1)]
    if len(parts) != 2 or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_ ]*', parts[0]):
        raise ValueError('Computed series must use Name:operation.')
    operation = parts[1].lower()
    if operation not in ('difference', 'sum', 'average', 'ratio'):
        raise ValueError(f'Unsupported computed series operation: {operation}')
    return {'name': parts[0], 'operation': operation}


def build_computed_series_blocks(specs):
    expressions = {
        'difference': 'first.Values[index] - second.Values[index]',
        'sum': 'first.Values[index] + second.Values[index]',
        'average': '(first.Values[index] + second.Values[index]) / 2d',
        'ratio': 'SafeRatio(first.Values[index], second.Values[index])',
    }
    blocks = []
    for spec in specs:
        name = escape_csharp_string(spec['name'])
        expression = expressions[spec['operation']]
        blocks.append(
            f'            yield return new GraphSeries("{name}", first.Timestamps.Take(count).ToArray(),\n'
            f'                Enumerable.Range(0, count).Select(index => {expression}).ToArray(), Colors.White);'
        )
    return '\n'.join(blocks)


def build_item_members(field_specs):
    defaults = {'string': ' = string.Empty', 'int': '', 'double': '', 'bool': ''}
    blocks = []
    for spec in field_specs:
        name = spec['name']
        field = to_camel_case(name)
        property_type = spec['type']
        blocks.append(
            f'        private {property_type} {field}{defaults[property_type]};\n\n'
            f'        public {property_type} {name}\n'
            '        {\n'
            f'            get => this.{field};\n'
            f'            set => this.SetProperty(ref this.{field}, value);\n'
            '        }'
        )
    return '\n\n'.join(blocks)


def build_lifecycle_hooks(atlas_parameters, include_hooks):
    if not atlas_parameters and not include_hooks:
        return ''
    registration_blocks = []
    range_number = 0
    for identifier in atlas_parameters:
        match = re.fullmatch(r'(.*)\[(\d+):(\d+)\](.*)', identifier)
        if not match:
            registration_blocks.append(
                f'            this.DisplayParameterService.AddParameterContainer("{escape_csharp_string(identifier)}");'
            )
            continue
        prefix, start_text, end_text, suffix = match.groups()
        range_number += 1
        variable = 'parameterIndex' if range_number == 1 else f'parameterIndex{range_number}'
        interpolation = (
            escape_csharp_string(prefix)
            + f'{{{variable}:{"0" * len(start_text)}}}'
            + escape_csharp_string(suffix)
        )
        registration_blocks.append(
            f'            for (var {variable} = {int(start_text)}; {variable} <= {int(end_text)}; {variable}++)\n'
            '            {\n'
            f'                this.DisplayParameterService.AddParameterContainer($"{interpolation}");\n'
            '            }'
        )
    registrations = '\n'.join(registration_blocks)
    initialised_body = '\n'.join(filter(None, [
        '            base.OnInitialised();',
        registrations,
        '            // TODO: Add one-time display setup.' if include_hooks else '',
    ]))
    result = (
        '        protected override void OnInitialised()\n'
        '        {\n'
        f'{initialised_body}\n'
        '        }\n'
    )
    if not include_hooks:
        return result
    return result + '''
        public override void OnActiveDisplayPageChanged(bool isActive)
        {
            base.OnActiveDisplayPageChanged(isActive);
            // TODO: Respond when the containing display page becomes active or inactive.
        }

        public override void OnCanRenderDisplayChanged(bool canRender)
        {
            base.OnCanRenderDisplayChanged(canRender);
            // TODO: Respond when this display becomes visible or hidden.
        }

        protected override void OnDisposeManagedResources()
        {
            // TODO: Dispose resources created by this ViewModel.
            base.OnDisposeManagedResources();
        }
'''


def build_session_notification_hooks():
    return '''        public override void OnCompositeSessionLoaded(CompositeSessionEventArgs args)
        {
            base.OnCompositeSessionLoaded(args);
            // TODO: Respond after a session is loaded.
        }

        public override void OnCompositeSessionUnLoaded(CompositeSessionUnloadedEventArgs args)
        {
            base.OnCompositeSessionUnLoaded(args);
            // TODO: Respond after a session is unloaded.
        }

        public override void OnCompositeSessionContainerChanged()
        {
            base.OnCompositeSessionContainerChanged();
            // TODO: Respond when the set associated with this display changes.
        }
'''

def get_parameter_range(atlas_parameter):
    # If parameter is named "someText{python formatted range}", extract and return the list of parameters.
    # For example, if atlas_parameter is "someText[001:003]someMoreText", the function should return ["someText001someMoreText", "someText002someMoreText", "someText003someMoreText"].
    # Pad based on the number of zeros specified in the range
    import re
    match = re.match(r'^(.*)\[(\d+):(\d+)\](.*)$', atlas_parameter)
    if match:
        base, start, end, suffix = match.groups()
        start, end = int(start), int(end)
        return [f"{base}{i:0{len(match.group(2))}d}{suffix}" for i in range(start, end + 1)]
    return [atlas_parameter]


def count_parameter_entries(text):
    return sum(
        len(get_parameter_range(line.strip()))
        for line in (text or '').splitlines()
        if line.strip()
    )

def generate_plugin(name, base_out, include_view=True, include_parameters=True, behavior=None, atlas_parameters=None,
                    display_property_specs=None, command_specs=None, parameter_max_count=100, workspace_root=None,
                    description=None, library_project=None, icon_path=None, service_names=None,
                    include_status_state=False, include_lifecycle_hooks=False,
                    include_session_notifications=False, include_item_collection=False,
                    basic_layout='text', collection_name='Items', item_class_name='ItemViewModel',
                    item_field_specs=None, graph_type='none', computed_series_specs=None, graph_title='',
                    graph_units=None, show_graph_legend=True, overlay_cursor_bars=False,
                    pair_cursor_points_by_half=False,
                    dll_specs=None, atlas_install_directory=None, sample_count = 100):
    if not include_view:
        raise ValueError('Generated display plugins require a WPF view.')
    name = normalize_plugin_name(name)
    behavior = behavior or (BEHAVIOR_CURRENT_VALUE if include_parameters else BEHAVIOR_BASIC)
    include_parameters = behavior_uses_parameters(behavior)
    if not isinstance(parameter_max_count, int) or parameter_max_count < 1:
        raise ValueError('Maximum parameter count must be a positive integer.')
    atlas_parameter_specs = [str(identifier).strip() for identifier in (atlas_parameters or []) if str(identifier).strip()]
    existing_atlas_parameters = set()
    expanded_atlas_parameters = []
    for identifier in atlas_parameter_specs:
        for expanded_identifier in get_parameter_range(identifier):
            validated_identifier = build_atlas_parameter(expanded_identifier, existing_atlas_parameters)
            expanded_atlas_parameters.append(validated_identifier)
            existing_atlas_parameters.add(validated_identifier)
    atlas_parameters = expanded_atlas_parameters
    display_property_specs = list(display_property_specs or [])
    command_specs = list(command_specs or [])
    computed_series_specs = list(computed_series_specs or [])
    graph_title = str(graph_title or '').strip()
    graph_units = [str(unit).strip() for unit in (graph_units or [])]
    dll_specs = normalize_dll_specs(dll_specs)
    validate_display_property_actions(display_property_specs, behavior)
    validate_command_actions(command_specs, display_property_specs)
    if atlas_parameters and not include_parameters:
        raise ValueError('ATLAS parameters require a data behavior.')
    if include_item_collection and behavior != BEHAVIOR_BASIC:
        raise ValueError('The starter item collection is only available for basic displays.')
    if basic_layout not in BASIC_LAYOUTS:
        raise ValueError(f'Unknown basic view layout: {basic_layout}')
    if behavior != BEHAVIOR_BASIC and basic_layout != 'text':
        raise ValueError('View layout selection is only available for basic displays.')
    if graph_type not in ('none', 'time-series', 'scatter', 'histogram', 'cursor-histogram', 'cursor-points', 'bar', 'custom'):
        raise ValueError(f'Unknown graph type: {graph_type}')
    cursor_graph = graph_type in ('cursor-histogram', 'cursor-points')
    range_behavior = behavior in (BEHAVIOR_VISIBLE_RANGE, BEHAVIOR_CURRENT_AND_RANGE)
    if graph_type != 'none' and not range_behavior and not (
        cursor_graph and behavior in (BEHAVIOR_CURRENT_VALUE, BEHAVIOR_COMPARE_SESSIONS)
    ):
        raise ValueError('Time-series graphs require a visible-range behavior.')
    if cursor_graph and behavior not in (BEHAVIOR_CURRENT_VALUE, BEHAVIOR_COMPARE_SESSIONS):
        raise ValueError('Cursor graphs require Current value at cursor or Compare sessions behavior.')
    if overlay_cursor_bars and graph_type not in ('cursor-histogram', 'cursor-points'):
        raise ValueError('Cursor bar overlay requires a cursor histogram or cursor points graph.')
    if pair_cursor_points_by_half and not (graph_type == 'cursor-points' and overlay_cursor_bars):
        raise ValueError('Split-half pairing requires overlaid cursor points.')
    if computed_series_specs and graph_type == 'none':
        raise ValueError('Computed series require a graph.')
    if include_item_collection and basic_layout == 'text':
        basic_layout = 'list'
    include_item_collection = include_item_collection or basic_layout in ('list', 'table')
    item_field_specs = list(item_field_specs or [build_item_field_spec('Name:string')])
    for label, identifier in (('Collection name', collection_name), ('Item class name', item_class_name)):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', identifier or ''):
            raise ValueError(f'{label} must be a valid C# identifier.')
    if not item_field_specs:
        raise ValueError('At least one item field is required.')
    field_names = [spec['name'] for spec in item_field_specs]
    if len(field_names) != len(set(field_names)):
        raise ValueError('Item field names must be unique.')
    if len(atlas_parameters) > parameter_max_count:
        raise ValueError('Maximum parameter count cannot be lower than the number of ATLAS parameters.')
    namespace = name
    workspace_root = os.path.abspath(workspace_root or default_workspace_root())
    atlas_install_directory = os.path.abspath(atlas_install_directory or DEFAULT_ATLAS_INSTALL_DIRECTORY)
    icon_path = validate_icon_path(icon_path)
    icon_filename = os.path.basename(icon_path)
    target = os.path.join(base_out, name)
    project_directory = os.path.join(target, name)
    os.makedirs(project_directory, exist_ok=True)
    resources_dir = os.path.join(project_directory, 'Resources')
    os.makedirs(resources_dir, exist_ok=True)
    shutil.copyfile(icon_path, os.path.join(resources_dir, icon_filename))
    for spec in dll_specs:
        if spec['kind'] == 'native' and spec['source'] == 'atlas':
            continue
        folder = 'Managed' if spec['kind'] == 'managed' else 'Native'
        dependency_directory = os.path.join(project_directory, 'Dependencies', folder)
        os.makedirs(dependency_directory, exist_ok=True)
        shutil.copy2(spec['path'], os.path.join(dependency_directory, spec['name']))

    project_guid = str(uuid.uuid4()).upper()
    assembly_guid = str(uuid.uuid4()).upper()
    description = description or f'{name} ATLAS display plugin'

    deploy_dependency_args = ''.join(
        f' &quot;$(TargetDir){html.escape(spec["name"], quote=True)}&quot;'
        for spec in dll_specs
        if spec['source'] == 'custom'
    )
    csproj = CS_PROJ_TEMPLATE.format(
        project_guid=project_guid,
        icon_filename=icon_filename,
        dll_items=build_dll_project_items(dll_specs),
        deploy_dependency_args=deploy_dependency_args,
    )
    library_project_guid = str(uuid.uuid4()).upper()
    library_project_entry = ''
    library_configurations = ''
    if include_parameters:
        library_project = os.path.abspath(library_project or '')
        if not os.path.isfile(library_project):
            raise FileNotFoundError('Select a valid DisplayPluginLibrary.csproj before generating a parameter plugin.')
        library_source_directory = os.path.dirname(library_project)
        library_target_directory = os.path.join(target, 'DisplayPluginLibrary')
        shutil.copytree(
            library_source_directory,
            library_target_directory,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns('bin', 'obj', '*.user', '*.suo'),
        )
        copied_library_project = os.path.join(library_target_directory, os.path.basename(library_project))
        with open(copied_library_project, 'r', encoding='utf-8') as stream:
            copied_library_contents = stream.read()
        copied_library_contents = LIBRARY_POST_BUILD_PATTERN.sub('\n', copied_library_contents)
        with open(copied_library_project, 'w', encoding='utf-8', newline='') as stream:
            stream.write(copied_library_contents)
        library_reference = os.path.relpath(copied_library_project, project_directory).replace(os.sep, '/')
        csproj = csproj.replace(
            '    <PackageReference Include="Atlas.DisplayAPI"',
            '    <ProjectReference Include="' + library_reference + '">\n'
            '      <Private>true</Private>\n'
            '    </ProjectReference>\n'
            '    <PackageReference Include="Atlas.DisplayAPI"',
        )
        library_project_entry = (
            'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = '
            '"DisplayPluginLibrary", "DisplayPluginLibrary\\DisplayPluginLibrary.csproj", '
            f'"{{{library_project_guid}}}"\nEndProject'
        )
        library_configurations = (
            f'\t\t{{{library_project_guid}}}.Debug|x64.ActiveCfg = Debug|x64\n'
            f'\t\t{{{library_project_guid}}}.Debug|x64.Build.0 = Debug|x64\n'
            f'\t\t{{{library_project_guid}}}.Release|x64.ActiveCfg = Release|x64\n'
            f'\t\t{{{library_project_guid}}}.Release|x64.Build.0 = Release|x64'
        )

    if behavior == BEHAVIOR_CURRENT_VALUE:
        viewmodel_template = TIMEBASE_VIEWMODEL_TEMPLATE if cursor_graph else VIEWMODEL_TEMPLATE
        view_template = TIME_GRAPH_VIEW_XAML_TEMPLATE if cursor_graph else VIEW_XAML_TEMPLATE
    elif behavior in (BEHAVIOR_VISIBLE_RANGE, BEHAVIOR_CURRENT_AND_RANGE):
        viewmodel_template = TIMEBASE_VIEWMODEL_TEMPLATE
        view_template = TIME_GRAPH_VIEW_XAML_TEMPLATE if graph_type != 'none' else TIMEBASE_VIEW_XAML_TEMPLATE
    elif behavior == BEHAVIOR_COMPARE_SESSIONS:
        viewmodel_template = COMPARE_VIEWMODEL_TEMPLATE
        view_template = TIME_GRAPH_VIEW_XAML_TEMPLATE if cursor_graph else COMPARE_VIEW_XAML_TEMPLATE
    else:
        viewmodel_template = BASIC_VIEWMODEL_TEMPLATE
        view_template = BASIC_VIEW_XAML_TEMPLATE
    atlas_parameter_setup = ''
    display_property_fields = ''
    display_properties = ''
    atlas_parameter_setup = build_lifecycle_hooks(
        atlas_parameter_specs if include_parameters else [],
        include_lifecycle_hooks,
    )
    if display_property_specs:
        display_property_fields = '\n'.join(
            build_display_property_field(spec) for spec in display_property_specs
        )
        display_properties = '\n'.join(
            build_display_property(spec) for spec in display_property_specs
        )

    # ISignalBus/IDataRequestSignalFactory are always injected by ParameterSampleDisplayViewModelBase.
    requested_services = list(service_names or [])
    if graph_type != 'none' and 'ISessionCursorService' not in requested_services:
        requested_services.append('ISessionCursorService')
    if behavior == BEHAVIOR_BASIC and any(spec.get('generate_log', False) for spec in command_specs):
        if 'ILogger' not in requested_services:
            requested_services.append('ILogger')
    if include_parameters:
        extra_service_names = [
            n for n in requested_services
            if n not in ('ILogger', 'ISignalBus', 'IDataRequestSignalFactory')
        ]
    else:
        extra_service_names = requested_services
    service_entries = build_service_entries(extra_service_names)
    extra_usings = build_service_usings(service_entries)
    if include_session_notifications and behavior in (BEHAVIOR_CURRENT_VALUE, BEHAVIOR_BASIC):
        extra_usings += 'using MAT.Atlas.Client.Platform.Sessions;\n'
    if include_item_collection:
        extra_usings += 'using System.Collections.ObjectModel;\n'
    if any(spec.get('break_when_attached', False) for spec in command_specs):
        extra_usings += 'using System.Diagnostics;\n'
    if graph_type and graph_type != 'none':
        extra_usings += 'using MAT.OCS.Core;\n'
    extra_ctor_params = ''
    extra_ctor_assignments = ''
    service_members = ''
    command_properties = '\n'.join(build_command_property(spec) for spec in command_specs)
    command_initializers = ''.join(build_command_initializer(spec) for spec in command_specs)
    logger_expression = 'this.Logger' if include_parameters else 'this.logger'
    command_handlers = '\n'.join(
        build_command_handler(spec, logger_expression, display_property_specs)
        for spec in command_specs
    )
    command_buttons = ''.join(build_command_button(spec) for spec in command_specs)
    status_state_fields, status_state_properties = build_status_state() if include_status_state else ('', '')
    session_notification_hooks = build_session_notification_hooks() if include_session_notifications else ''
    show_legend_members = (
        SHOW_LEGEND_MEMBERS.replace('__SHOW_LEGEND_DEFAULT__', 'true' if show_graph_legend else 'false')
        if graph_type != 'none' else ''
    )
    item_collection_property = (
        '        [Browsable(false)]\n'
        f'        public ObservableCollection<{item_class_name}> {collection_name} {{ get; }} =\n'
        f'            new ObservableCollection<{item_class_name}>();\n'
        if include_item_collection else ''
    )
    if include_parameters:
        extra_service_fields = build_service_fields(service_entries)
        display_property_fields = '\n'.join(filter(None, [display_property_fields, extra_service_fields]))
        extra_ctor_params = ''.join(f',\n            {entry["interface"]} {entry["param"]}' for entry in service_entries)
        extra_ctor_assignments = ''.join(f'            this.{entry["param"]} = {entry["param"]};\n' for entry in service_entries)
    else:
        service_members = build_basic_service_members(
            f'{name}ViewModel',
            service_entries,
            command_initializers,
        )

    files = {
        f'{name}.csproj': csproj,
        f'{name}.csproj.user': DEBUG_USER_SETTINGS_TEMPLATE.format(
            atlas_host_path=os.path.join(atlas_install_directory, 'MAT.Atlas.Host.exe'),
        ),
        os.path.join('Properties', 'AssemblyInfo.cs'): ASSEMBLY_INFO_TEMPLATE.format(
            title=name,
            description=escape_csharp_string(description),
            assembly_guid=assembly_guid,
        ),
        'PluginModule.cs': PLUGIN_MODULE_TEMPLATE.format(
            namespace=namespace,
            view_class=f'{name}View',
            viewmodel_class=f'{name}ViewModel',
            icon_filename=icon_filename,
        ),
        f'{name}ViewModel.cs': viewmodel_template.format(
            namespace=namespace,
            viewmodel_class=f'{name}ViewModel',
            view_class=f'{name}View',
            atlas_parameter_setup=atlas_parameter_setup,
            display_property_fields=display_property_fields,
            display_properties=display_properties,
            extra_usings=extra_usings,
            extra_ctor_params=extra_ctor_params,
            extra_ctor_assignments=extra_ctor_assignments,
            service_members=service_members,
            parameter_max_count=parameter_max_count,
            data_subscription=DATA_SUBSCRIPTION if range_behavior else '',
            sample_count_members=(
                SAMPLE_COUNT_MEMBERS.replace('{default_sample_count}', str(sample_count)) if range_behavior else ''
            ),
            timebase_request_method=TIMEBASE_REQUEST_METHOD if range_behavior else '',
            data_result_handler=DATA_RESULT_HANDLER if range_behavior else '',
            cursor_subscription=CURSOR_SUBSCRIPTION if behavior == BEHAVIOR_CURRENT_AND_RANGE or cursor_graph else '',
            cursor_request_method=CURSOR_REQUEST_METHOD if behavior == BEHAVIOR_CURRENT_AND_RANGE or cursor_graph else '',
            cursor_result_handler=CURSOR_RESULT_HANDLER if behavior == BEHAVIOR_CURRENT_AND_RANGE or cursor_graph else '',
            command_properties=command_properties,
            command_initializers=command_initializers,
            command_handlers=command_handlers,
            status_state_fields=status_state_fields,
            status_state_properties=status_state_properties,
            session_notification_hooks=session_notification_hooks,
            item_collection_property=item_collection_property,
            graph_units_field=(
                '        private static readonly string[] GraphUnits = { '
                + ', '.join(f'"{escape_csharp_string(unit)}"' for unit in graph_units)
                + ' };'
                if range_behavior or cursor_graph else ''
            ),
            graph_cursor_method=GRAPH_CURSOR_METHOD if graph_type != 'none' else '',
            compare_graph_members=(
                COMPARE_GRAPH_MEMBERS.replace(
                    '__GRAPH_UNITS__',
                    ', '.join(f'"{escape_csharp_string(unit)}"' for unit in graph_units),
                ).replace('__SHOW_LEGEND_DEFAULT__', 'true' if show_graph_legend else 'false')
                if behavior == BEHAVIOR_COMPARE_SESSIONS and cursor_graph else ''
            ),
            compare_graph_sync_call=(
                '                    this.SyncGraphSeries();'
                if behavior == BEHAVIOR_COMPARE_SESSIONS and cursor_graph else ''
            ),
            compare_graph_sync_method=(
                COMPARE_GRAPH_SYNC_METHOD if behavior == BEHAVIOR_COMPARE_SESSIONS and cursor_graph else ''
            ),
            default_sample_count=sample_count,
            show_legend_members=show_legend_members,
        ),
    }
    if behavior == BEHAVIOR_CURRENT_VALUE and not cursor_graph:
        files['ParameterViewModel.cs'] = PARAMETER_VIEWMODEL_TEMPLATE.format(namespace=namespace)
    elif range_behavior or cursor_graph:
        include_current_value = behavior == BEHAVIOR_CURRENT_AND_RANGE or cursor_graph
        files['TimebaseSeriesViewModel.cs'] = TIMEBASE_SERIES_VIEWMODEL_TEMPLATE.format(
            namespace=namespace,
            current_value_field=CURRENT_VALUE_FIELD if include_current_value else '',
            current_value_property=CURRENT_VALUE_PROPERTY if include_current_value else '',
            current_value_update_method=CURRENT_VALUE_UPDATE_METHOD if include_current_value else '',
        )
        if graph_type != 'none':
            files['GraphSeries.cs'] = GRAPH_SERIES_TEMPLATE.format(namespace=namespace)
            regex_val = "^[a-zA-Z]+\\\\d{3}$"
            files['GraphRenderer.cs'] = GRAPH_RENDERER_TEMPLATE.format(namespace=namespace).replace(
                '__REGEX_VALUE__', regex_val
            ).replace('__GRAPH_TYPE__', graph_type).replace(
                '__CURSOR_BAR_OVERLAY__', 'true' if overlay_cursor_bars else 'false'
            ).replace(
                '__PAIR_CURSOR_POINTS_BY_HALF__', 'true' if pair_cursor_points_by_half else 'false'
            )
            files['CustomGraphRenderer.cs'] = CUSTOM_GRAPH_RENDERER_TEMPLATE.format(namespace=namespace)
            if computed_series_specs:
                files['ComputedGraphSeriesFactory.cs'] = COMPUTED_GRAPH_SERIES_TEMPLATE.format(
                    namespace=namespace,
                    computed_blocks=build_computed_series_blocks(computed_series_specs),
                )
    if behavior == BEHAVIOR_COMPARE_SESSIONS:
        files['CompareRowViewModel.cs'] = COMPARE_ROW_VIEWMODEL_TEMPLATE.format(namespace=namespace)
        files['CompareSessionValueViewModel.cs'] = COMPARE_SESSION_VALUE_VIEWMODEL_TEMPLATE.format(
            namespace=namespace,
        )
    elif include_item_collection:
        files[f'{item_class_name}.cs'] = ITEM_VIEWMODEL_TEMPLATE.format(
            namespace=namespace,
            item_class_name=item_class_name,
            item_members=build_item_members(item_field_specs),
        )
    if include_view:
        files[f'{name}View.xaml'] = view_template.format(
            namespace=namespace,
            view_class=f'{name}View',
            command_buttons=command_buttons,
            graph_title_block=(
                f'        <TextBlock DockPanel.Dock="Top" Text="{html.escape(graph_title, quote=True)}" '
                'FontSize="20" FontWeight="SemiBold" Foreground="{StaticResource PrimaryTextBrush}" Margin="14,6,14,8" />'
                if graph_title and graph_type != 'none' else ''
            ),
                current_value_text=(
                    CURRENT_VALUE_TEXT if behavior == BEHAVIOR_CURRENT_AND_RANGE or cursor_graph else ''
                ),
                graph_statistics=(
                    '''                                    <TextBlock Text="{Binding Minimum, StringFormat='Minimum: {0:F3}'}" Style="{StaticResource CaptionStyle}" />
                                    <TextBlock Text="{Binding Maximum, StringFormat='Maximum: {0:F3}'}" Style="{StaticResource CaptionStyle}" />
                                    <TextBlock Text="{Binding Average, StringFormat='Average: {0:F3}'}" Style="{StaticResource CaptionStyle}" />
                                    <TextBlock Text="{Binding SampleCount, StringFormat='Samples: {0}'}" Style="{StaticResource CaptionStyle}" />'''
                    if range_behavior else ''
                ),
            basic_content=build_basic_layout_content(
                basic_layout,
                f'{name}View',
                command_buttons,
                display_property_specs,
                collection_name,
                item_field_specs[0]['name'],
            ),
        )
        codebehind_template = GRAPH_VIEW_CODEBEHIND_TEMPLATE if graph_type != 'none' else VIEW_CODEBEHIND_TEMPLATE
        files[f'{name}View.xaml.cs'] = codebehind_template.format(
            namespace=namespace,
            view_class=f'{name}View',
            viewmodel_class=f'{name}ViewModel',
            uses_time_axis='true' if graph_type == 'time-series' else 'false',
            current_value_argument=(
                ', item.CurrentValue' if behavior == BEHAVIOR_CURRENT_AND_RANGE or cursor_graph else ', double.NaN'
            ),
            computed_series_update=(
                '            series.AddRange(ComputedGraphSeriesFactory.Create(series).ToList());'
                if computed_series_specs else ''
            ),
        )

    for filename, content in files.items():
        file_path = os.path.join(project_directory, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8', newline='') as stream:
            stream.write(content)
    
    # Generate the solution beside the nested project folder.
    sln_content = SLN_TEMPLATE.format(
        project_name=name,
        project_guid=project_guid,
        library_project_entry=library_project_entry,
        library_configurations=library_configurations,
    )
    sln_path = os.path.join(target, f'{name}.sln')
    with open(sln_path, 'w', encoding='utf-8', newline='') as stream:
        stream.write(sln_content)

    scripts_dir = os.path.join(target, 'scripts')
    os.makedirs(scripts_dir, exist_ok=True)
    deploy_py = DEPLOY_PY_TEMPLATE.format(
        atlas_install_path=atlas_install_directory,
    )
    with open(os.path.join(scripts_dir, 'deploy.py'), 'w', encoding='utf-8', newline='') as stream:
        stream.write(deploy_py)
    
    return target


class PluginGeneratorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.generated_icon_temp_directory = None
        self.title('ATLAS Display Plugin Generator')
        self.minsize(480, 400)
        self.resizable(True, True)
        settings = load_settings()
        
        # Create main frame with scrollbar
        main_frame = tk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        canvas = tk.Canvas(main_frame)
        scrollbar = tk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def on_canvas_configure(event):
            # Stretch the scrollable content to fill the canvas as the window is resized.
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", on_canvas_configure)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda event: canvas.bind_all("<MouseWheel>", on_mousewheel))
        canvas.bind("<Leave>", lambda event: canvas.unbind_all("<MouseWheel>"))
        
        # === Basic Plugin Information ===
        info_frame = tk.LabelFrame(scrollable_frame, text='Basic Information', padx=8, pady=8)
        info_frame.pack(fill=tk.X, pady=8)
        
        tk.Label(info_frame, text='Plugin Name:').grid(row=0, column=0, sticky='w', pady=6)
        self.name_var = tk.StringVar()
        tk.Entry(info_frame, textvariable=self.name_var, width=45).grid(row=0, column=1, sticky='ew', padx=8)
        tk.Label(info_frame, text='(C# identifier, required)', font=('Arial', 8, 'italic')).grid(row=0, column=2, sticky='w')
        info_frame.columnconfigure(1, weight=1)

        tk.Label(info_frame, text='Description:').grid(row=1, column=0, sticky='nw', pady=6)
        self.description_var = tk.StringVar()
        tk.Entry(info_frame, textvariable=self.description_var, width=45).grid(row=1, column=1, sticky='ew', padx=8)
        tk.Label(info_frame, text='(optional)', font=('Arial', 8, 'italic')).grid(row=1, column=2, sticky='w')
        
        # === Output Location ===
        output_frame = tk.LabelFrame(scrollable_frame, text='Output Location', padx=8, pady=8)
        output_frame.pack(fill=tk.X, pady=8)
        
        tk.Label(output_frame, text='Output Folder:').grid(row=0, column=0, sticky='w', pady=6)
        self.out_var = tk.StringVar(value=settings.get('output_folder', ''))
        tk.Entry(output_frame, textvariable=self.out_var, width=45).grid(row=0, column=1, sticky='ew', padx=8)
        tk.Button(output_frame, text='Browse', command=self.browse).grid(row=0, column=2, padx=6)
        output_frame.columnconfigure(1, weight=1)

        tk.Label(output_frame, text='DisplayPluginLibrary.csproj:').grid(row=1, column=0, sticky='w', pady=6)
        self.library_var = tk.StringVar(value=settings.get('library_project', ''))
        tk.Entry(output_frame, textvariable=self.library_var, width=45).grid(row=1, column=1, sticky='ew', padx=8)
        tk.Button(output_frame, text='Browse', command=self.browse_library).grid(row=1, column=2, padx=6)

        tk.Label(output_frame, text='Plugin icon (.png):').grid(row=2, column=0, sticky='w', pady=6)
        self.icon_var = tk.StringVar(value=settings.get('icon_path', ''))
        self.icon_entry = tk.Entry(output_frame, textvariable=self.icon_var, width=45)
        self.icon_entry.grid(row=2, column=1, sticky='ew', padx=8)
        tk.Button(output_frame, text='Browse', command=self.browse_icon).grid(row=2, column=2, padx=6)
        tk.Button(output_frame, text='Create...', command=self.create_icon).grid(row=2, column=3, padx=6)

        tk.Label(output_frame, text='ATLAS install folder:').grid(row=3, column=0, sticky='w', pady=6)
        self.atlas_install_var = tk.StringVar(value=settings.get(
            'atlas_install_directory',
            DEFAULT_ATLAS_INSTALL_DIRECTORY,
        ))
        tk.Entry(output_frame, textvariable=self.atlas_install_var, width=45).grid(
            row=3, column=1, sticky='ew', padx=8
        )
        tk.Button(output_frame, text='Browse', command=self.browse_atlas_install).grid(row=3, column=2, padx=6)

        # === Deployed Plugins ===
        dll_frame = tk.LabelFrame(scrollable_frame, text='Deployed Plugins', padx=8, pady=8)
        dll_frame.pack(fill=tk.BOTH, expand=True, pady=8)
        tk.Label(
            dll_frame,
            text='Lists custom plugin DLLs in the configured ATLAS folder. Built-in MAT.Atlas.Plugins assemblies are excluded.',
            font=('Arial', 8, 'italic'), justify='left', wraplength=600,
        ).pack(anchor='w', pady=(0, 4))

        self.deployed_plugin_tree = ttk.Treeview(
            dll_frame,
            columns=('name', 'location'),
            show='headings',
            height=5,
            selectmode='extended',
        )
        self.deployed_plugin_tree.heading('name', text='Plugin DLL')
        self.deployed_plugin_tree.heading('location', text='Location')
        self.deployed_plugin_tree.column('name', width=220, anchor='w')
        self.deployed_plugin_tree.column('location', width=460, anchor='w')
        self.deployed_plugin_tree.pack(fill=tk.BOTH, expand=True, pady=4)
        self.dll_specs = []

        dll_button_frame = tk.Frame(dll_frame)
        dll_button_frame.pack(fill=tk.X, pady=4)
        tk.Button(dll_button_frame, text='Refresh', command=self.refresh_deployed_plugins).pack(
            side=tk.LEFT, padx=4
        )
        tk.Button(dll_button_frame, text='Remove Selected...', command=self.remove_selected_deployed_plugins).pack(
            side=tk.LEFT, padx=4
        )
        self.refresh_deployed_plugins()
        
        # === Plugin Behavior ===
        config_frame = tk.LabelFrame(scrollable_frame, text='Plugin Behavior', padx=8, pady=8)
        config_frame.pack(fill=tk.X, pady=8)

        tk.Label(config_frame, text='What should the plugin do?').pack(anchor='w', pady=(0, 4))
        self.behavior_var = tk.StringVar(value=BEHAVIOR_CURRENT_VALUE)
        behavior_combo = ttk.Combobox(
            config_frame,
            textvariable=self.behavior_var,
            values=(
                BEHAVIOR_CURRENT_VALUE,
                BEHAVIOR_VISIBLE_RANGE,
                BEHAVIOR_CURRENT_AND_RANGE,
                BEHAVIOR_COMPARE_SESSIONS,
                BEHAVIOR_BASIC,
            ),
            state='readonly',
        )
        
        behavior_combo.pack(fill=tk.X, pady=(0, 4))
        behavior_combo.bind('<<ComboboxSelected>>', lambda event: self.update_behavior_states())
        behavior_combo.bind('<MouseWheel>', lambda event: "break")
        tk.Label(
            config_frame,
            text='Choose cursor values, visible-range samples, both, compare sessions, or a basic display.',
            font=('Arial', 8, 'italic'), justify='left', wraplength=600,
        ).pack(anchor='w', pady=(0, 4))

        # Ask for the default sample count if visible range behavior is selected
        tk.Label(config_frame, text='Default sample count:').pack(anchor='w', pady=(8, 4))
        self.sample_count_var = tk.IntVar(value=100)
        self.sample_count_entry = tk.Entry(config_frame, textvariable=self.sample_count_var)
        self.sample_count_entry.pack(fill=tk.X, pady=(0, 4))

        tk.Label(config_frame, text='Basic display layout:').pack(anchor='w', pady=(8, 4))
        self.basic_layout_var = tk.StringVar(value='text')
        self.basic_layout_combo = ttk.Combobox(
            config_frame,
            textvariable=self.basic_layout_var,
            values=BASIC_LAYOUTS,
            state='disabled',
        )
        self.basic_layout_combo.bind('<MouseWheel>', lambda event: "break")
        self.basic_layout_combo.pack(fill=tk.X, pady=(0, 4))
        
        # === Injected Services ===
        services_frame = tk.LabelFrame(scrollable_frame, text='Injected Services', padx=8, pady=8)
        services_frame.pack(fill=tk.X, pady=8)

        tk.Label(
            services_frame,
            text='ISignalBus and IDataRequestSignalFactory are always injected for data behaviors.',
            font=('Arial', 8, 'italic'), justify='left', wraplength=600,
        ).pack(anchor='w', pady=(0, 4))

        self.service_vars = {service_name: tk.BooleanVar(value=False) for service_name in SERVICE_DEFINITIONS}
        self.service_checkbuttons = {}
        for service_name in SERVICE_DEFINITIONS:
            checkbutton = tk.Checkbutton(services_frame, text=service_name, variable=self.service_vars[service_name])
            checkbutton.pack(anchor='w')
            self.service_checkbuttons[service_name] = checkbutton
        self.update_behavior_states()
        
        # === ATLAS Parameters ===
        atlas_frame = tk.LabelFrame(scrollable_frame, text='ATLAS Parameters', padx=8, pady=8)
        atlas_frame.pack(fill=tk.X, pady=8)
        tk.Label(
            atlas_frame,
            text='One ATLAS identifier per line, for example vCar:Chassis. These are added in OnInitialised().',
            font=('Arial', 8, 'italic'), justify='left', wraplength=600,
        ).pack(anchor='w', pady=(0, 4))
        self.atlas_parameter_text = tk.Text(atlas_frame, height=4, wrap=tk.WORD)
        self.atlas_parameter_text.pack(fill=tk.X)
        self.atlas_parameter_text.bind('<KeyRelease>', self.infer_parameter_max_count)
        self.update_behavior_states()

        # === Display Properties ===
        property_frame = tk.LabelFrame(scrollable_frame, text='Display Properties', padx=8, pady=8)
        property_frame.pack(fill=tk.BOTH, expand=True, pady=8)
        tk.Label(
            property_frame,
            text='Settings shown in the ATLAS properties window and optionally saved in the workbook.',
            font=('Arial', 8, 'italic'), justify='left', wraplength=600,
        ).pack(anchor='w', pady=(0, 4))

        self.display_property_specs = []

        tree_columns = ('identifier', 'type', 'default', 'action', 'display_name', 'persisted', 'read_only', 'browsable')
        column_headings = {
            'identifier': 'Identifier',
            'type': 'Type',
            'default': 'Default',
            'action': 'When Changed',
            'display_name': 'Display Name',
            'persisted': 'Persisted',
            'read_only': 'Read Only',
            'browsable': 'Browsable',
        }
        column_widths = {
            'identifier': 110,
            'type': 70,
            'default': 90,
            'action': 130,
            'display_name': 120,
            'persisted': 65,
            'read_only': 65,
            'browsable': 65,
        }
        self.property_tree = ttk.Treeview(property_frame, columns=tree_columns, show='headings', height=6)
        for column in tree_columns:
            self.property_tree.heading(column, text=column_headings[column])
            self.property_tree.column(column, width=column_widths[column], anchor='w')
        self.property_tree.pack(fill=tk.BOTH, expand=True, pady=4)
        self.property_tree.bind('<Double-1>', lambda event: self.edit_selected_property())

        property_button_frame = tk.Frame(property_frame)
        property_button_frame.pack(fill=tk.X, pady=4)
        tk.Button(property_button_frame, text='Add...', command=self.add_property_dialog).pack(side=tk.LEFT, padx=4)
        tk.Button(property_button_frame, text='Edit...', command=self.edit_selected_property).pack(side=tk.LEFT, padx=4)
        tk.Button(property_button_frame, text='Remove', command=self.remove_selected_property).pack(side=tk.LEFT, padx=4)

        # === Commands ===
        command_frame = tk.LabelFrame(scrollable_frame, text='Commands', padx=8, pady=8)
        command_frame.pack(fill=tk.BOTH, expand=True, pady=8)
        tk.Label(
            command_frame,
            text='Generate an ICommand, handler stub, and optional WPF button for each action.',
            font=('Arial', 8, 'italic'), justify='left', wraplength=600,
        ).pack(anchor='w', pady=(0, 4))

        self.command_specs = []
        self.command_tree = ttk.Treeview(
            command_frame,
            columns=('name', 'action', 'target', 'button_label', 'include_button', 'can_execute', 'log', 'breakpoint'),
            show='headings',
            height=4,
        )
        self.command_tree.heading('name', text='Command')
        self.command_tree.heading('action', text='Action')
        self.command_tree.heading('target', text='Target')
        self.command_tree.heading('button_label', text='Button Label')
        self.command_tree.heading('include_button', text='Add Button')
        self.command_tree.heading('can_execute', text='Enabled Rule')
        self.command_tree.heading('log', text='Log')
        self.command_tree.heading('breakpoint', text='Debug Break')
        self.command_tree.column('name', width=150, anchor='w')
        self.command_tree.column('action', width=145, anchor='w')
        self.command_tree.column('target', width=100, anchor='w')
        self.command_tree.column('button_label', width=180, anchor='w')
        self.command_tree.column('include_button', width=80, anchor='w')
        self.command_tree.column('can_execute', width=100, anchor='w')
        self.command_tree.column('log', width=55, anchor='w')
        self.command_tree.column('breakpoint', width=85, anchor='w')
        self.command_tree.pack(fill=tk.BOTH, expand=True, pady=4)
        self.command_tree.bind('<Double-1>', lambda event: self.edit_selected_command())

        command_button_frame = tk.Frame(command_frame)
        command_button_frame.pack(fill=tk.X, pady=4)
        tk.Button(command_button_frame, text='Add...', command=self.add_command_dialog).pack(side=tk.LEFT, padx=4)
        tk.Button(command_button_frame, text='Edit...', command=self.edit_selected_command).pack(side=tk.LEFT, padx=4)
        tk.Button(command_button_frame, text='Remove', command=self.remove_selected_command).pack(side=tk.LEFT, padx=4)
        
        # === Advanced Settings ===
        advanced_section = tk.Frame(scrollable_frame)
        advanced_section.pack(fill=tk.X, pady=8)
        advanced_frame = tk.LabelFrame(advanced_section, text='Advanced Settings', padx=8, pady=8)
        self.advanced_expanded = False

        def toggle_advanced():
            self.advanced_expanded = not self.advanced_expanded
            if self.advanced_expanded:
                advanced_frame.pack(fill=tk.X, pady=(4, 0))
                advanced_toggle.config(text='▼ Advanced Settings')
            else:
                advanced_frame.pack_forget()
                advanced_toggle.config(text='▶ Advanced Settings')

        advanced_toggle = tk.Button(advanced_section, text='▶ Advanced Settings', command=toggle_advanced, anchor='w')
        advanced_toggle.pack(fill=tk.X)
        
        tk.Label(advanced_frame, text='Maximum parameters:').grid(row=0, column=0, sticky='w', pady=6)
        self.parameter_max_var = tk.StringVar(value='100')
        tk.Spinbox(advanced_frame, from_=1, to=1000, textvariable=self.parameter_max_var, width=10).grid(row=0, column=1, sticky='w', padx=8)
        
        self.open_folder_var = tk.BooleanVar(value=True)
        tk.Checkbutton(advanced_frame, text='Open folder after generation', variable=self.open_folder_var).grid(row=1, column=0, columnspan=2, sticky='w', pady=4)

        self.build_after_generation_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            advanced_frame,
            text='Build, validate, and deploy after generation',
            variable=self.build_after_generation_var,
        ).grid(row=2, column=0, columnspan=2, sticky='w', pady=4)

        self.status_state_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            advanced_frame,
            text='Generate loading, status, and error state',
            variable=self.status_state_var,
        ).grid(row=3, column=0, columnspan=2, sticky='w', pady=4)

        self.lifecycle_hooks_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            advanced_frame,
            text='Generate lifecycle hooks',
            variable=self.lifecycle_hooks_var,
        ).grid(row=4, column=0, columnspan=2, sticky='w', pady=4)

        self.session_notifications_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            advanced_frame,
            text='Generate session notification hooks',
            variable=self.session_notifications_var,
        ).grid(row=5, column=0, columnspan=2, sticky='w', pady=4)

        self.item_collection_var = tk.BooleanVar(value=False)
        self.item_collection_checkbutton = tk.Checkbutton(
            advanced_frame,
            text='Generate starter item collection (basic display)',
            variable=self.item_collection_var,
        )
        self.item_collection_checkbutton.grid(row=6, column=0, columnspan=2, sticky='w', pady=4)

        tk.Label(advanced_frame, text='Collection name:').grid(row=7, column=0, sticky='w', pady=4)
        self.collection_name_var = tk.StringVar(value='Items')
        self.collection_name_entry = tk.Entry(advanced_frame, textvariable=self.collection_name_var, width=24)
        self.collection_name_entry.grid(row=7, column=1, sticky='w', padx=8)
        tk.Label(advanced_frame, text='Item class name:').grid(row=8, column=0, sticky='w', pady=4)
        self.item_class_name_var = tk.StringVar(value='ItemViewModel')
        self.item_class_name_entry = tk.Entry(advanced_frame, textvariable=self.item_class_name_var, width=24)
        self.item_class_name_entry.grid(row=8, column=1, sticky='w', padx=8)
        tk.Label(advanced_frame, text='Item fields (Name:type, comma separated):').grid(row=9, column=0, sticky='w', pady=4)
        self.item_fields_var = tk.StringVar(value='Name:string')
        self.item_fields_entry = tk.Entry(advanced_frame, textvariable=self.item_fields_var, width=36)
        self.item_fields_entry.grid(row=9, column=1, sticky='ew', padx=8)

        tk.Label(advanced_frame, text='Graph:').grid(row=10, column=0, sticky='w', pady=4)
        self.graph_type_var = tk.StringVar(value='none')
        self.graph_type_combo = ttk.Combobox(
            advanced_frame,
            textvariable=self.graph_type_var,
            values=('none', 'time-series', 'scatter', 'histogram', 'cursor-histogram', 'cursor-points', 'bar', 'custom'),
            state='disabled',
            width=22,
        )
        self.graph_type_combo.grid(row=10, column=1, sticky='w', padx=8)
        self.graph_type_combo.bind('<MouseWheel>', lambda event: "break")
        self.graph_type_combo.bind('<<ComboboxSelected>>', lambda event: self.update_graph_states())
        tk.Label(advanced_frame, text='Computed series (Name:operation):').grid(row=11, column=0, sticky='w', pady=4)
        self.computed_series_var = tk.StringVar(value='')
        self.computed_series_entry = tk.Entry(advanced_frame, textvariable=self.computed_series_var, width=36)
        self.computed_series_entry.grid(row=11, column=1, sticky='ew', padx=8)
        tk.Label(advanced_frame, text='Graph title:').grid(row=12, column=0, sticky='w', pady=4)
        self.graph_title_var = tk.StringVar(value='')
        self.graph_title_entry = tk.Entry(advanced_frame, textvariable=self.graph_title_var, width=36)
        self.graph_title_entry.grid(row=12, column=1, sticky='ew', padx=8)
        tk.Label(advanced_frame, text='Series units (comma separated):').grid(row=13, column=0, sticky='w', pady=4)
        self.graph_units_var = tk.StringVar(value='')
        self.graph_units_entry = tk.Entry(advanced_frame, textvariable=self.graph_units_var, width=36)
        self.graph_units_entry.grid(row=13, column=1, sticky='ew', padx=8)
        self.graph_legend_var = tk.BooleanVar(value=True)
        self.graph_legend_checkbutton = tk.Checkbutton(
            advanced_frame,
            text='Show graph legend and statistics',
            variable=self.graph_legend_var,
        )
        self.graph_legend_checkbutton.grid(row=14, column=0, columnspan=2, sticky='w', pady=4)
        self.overlay_cursor_bars_var = tk.BooleanVar(value=False)
        self.overlay_cursor_bars_checkbutton = tk.Checkbutton(
            advanced_frame,
            text='Overlay parameter bars/points (cursor histogram or points)',
            variable=self.overlay_cursor_bars_var,
            command=self.update_graph_states,
        )
        self.overlay_cursor_bars_checkbutton.grid(row=15, column=0, columnspan=2, sticky='w', pady=4)
        self.pair_cursor_points_by_half_var = tk.BooleanVar(value=False)
        self.pair_cursor_points_by_half_checkbutton = tk.Checkbutton(
            advanced_frame,
            text='Pair overlaid points as (k, k + n/2) instead of (1-2, 3-4, ...)',
            variable=self.pair_cursor_points_by_half_var,
        )
        self.pair_cursor_points_by_half_checkbutton.grid(row=16, column=0, columnspan=2, sticky='w', pady=4)
        self.update_graph_states()
        
        # === Action Buttons ===
        button_frame = tk.Frame(scrollable_frame)
        button_frame.pack(fill=tk.X, pady=12)
        
        tk.Button(button_frame, text='Generate Plugin', command=self.generate, 
                 bg='#4CAF50', fg='white', font=('Arial', 10, 'bold'), padx=20, pady=10).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Reset', command=self.reset_form, 
                 bg='#2196F3', fg='white', font=('Arial', 10), padx=20, pady=10).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Clear Saved Paths', command=self.clear_saved_paths,
             bg='#FF9800', fg='white', font=('Arial', 10), padx=20, pady=10).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Save Preset', command=self.save_preset_dialog).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Load Preset', command=self.load_preset_dialog).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Exit', command=self.quit, 
                 bg='#f44336', fg='white', font=('Arial', 10), padx=20, pady=10).pack(side=tk.LEFT, padx=4)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._fit_window_to_content(scrollable_frame)

    def _fit_window_to_content(self, scrollable_frame):
        # Measuring reqwidth/reqheight of canvas-embedded widgets is unreliable before the
        # window is realized, so size to a generous fixed target capped to the screen instead.
        target_width = 700
        target_height = 900
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(target_width, screen_width - 100)
        height = min(target_height, screen_height - 100)
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.geometry(f'{width}x{height}+{x}+{y}')

    def browse(self):
        initial = self.out_var.get()
        if not os.path.isdir(initial):
            initial = os.getcwd()
        d = filedialog.askdirectory(initialdir=initial)
        if d:
            self.out_var.set(d)

    def browse_library(self):
        initial = self.library_var.get()
        initial_dir = os.path.dirname(initial) if os.path.isfile(initial) else os.getcwd()
        path = filedialog.askopenfilename(
            initialdir=initial_dir,
            filetypes=[('C# project', '*.csproj'), ('All files', '*.*')],
        )
        if path:
            self.library_var.set(path)

    def browse_icon(self):
        initial = self.icon_var.get()
        initial_dir = os.path.dirname(initial) if os.path.isfile(initial) else os.getcwd()
        path = filedialog.askopenfilename(
            initialdir=initial_dir,
            filetypes=[('PNG image', '*.png')],
        )
        if path:
            self.clear_generated_icon_temp_directory()
            self.set_icon_path(path)

    def browse_atlas_install(self):
        initial = self.atlas_install_var.get().strip()
        if not os.path.isdir(initial):
            initial = os.path.dirname(initial) if initial else os.getcwd()
        path = filedialog.askdirectory(title='Select ATLAS installation folder', initialdir=initial)
        if path:
            self.atlas_install_var.set(path)

    def refresh_deployed_plugins(self):
        self.deployed_plugin_tree.delete(*self.deployed_plugin_tree.get_children())
        atlas_directory = self.atlas_install_var.get().strip()
        for plugin_path in list_deployed_plugins(atlas_directory):
            self.deployed_plugin_tree.insert('', tk.END, values=(
                os.path.basename(plugin_path),
                plugin_path,
            ))

    def remove_selected_deployed_plugins(self):
        selected = self.deployed_plugin_tree.selection()
        if not selected:
            messagebox.showinfo('Deployed Plugins', 'Select one or more custom plugin DLLs to remove.')
            return
        plugin_paths = [self.deployed_plugin_tree.item(item, 'values')[1] for item in selected]
        cleanup_paths = [path for plugin_path in plugin_paths for path in plugin_cleanup_files(plugin_path)]
        message = 'The following files will be removed from the ATLAS installation:\n\n'
        message += '\n'.join(f'  - {path}' for path in cleanup_paths)
        message += '\n\nWindows will request administrator permission. Continue?'
        if not messagebox.askyesno('Remove Deployed Plugins', message):
            return
        try:
            request_elevated_plugin_removal(plugin_paths)
        except RuntimeError as error:
            messagebox.showerror('Remove Deployed Plugins', str(error))
            return
        self._refresh_after_deployed_removal(plugin_paths)

    def _refresh_after_deployed_removal(self, plugin_paths, attempts_remaining=30):
        self.refresh_deployed_plugins()
        if attempts_remaining > 0 and any(os.path.exists(path) for path in plugin_paths):
            self.after(
                500,
                lambda: self._refresh_after_deployed_removal(plugin_paths, attempts_remaining - 1),
            )

    def refresh_dll_tree(self):
        self.dll_tree.delete(*self.dll_tree.get_children())
        for spec in self.dll_specs:
            self.dll_tree.insert('', tk.END, values=(
                spec['name'],
                spec['kind'].title(),
                'ATLAS-installed' if spec['source'] == 'atlas' else 'Added',
                spec['path'],
            ))

    def _append_dll_paths(self, paths, source):
        existing_names = {spec['name'] for spec in self.dll_specs}
        errors = []
        for path in paths:
            try:
                spec = build_dll_spec(path, source, existing_names)
            except ValueError as error:
                errors.append(str(error))
                continue
            self.dll_specs.append(spec)
            existing_names.add(spec['name'])
        self.refresh_dll_tree()
        if errors:
            messagebox.showwarning('DLL Manager', '\n'.join(errors))

    def add_custom_dlls(self):
        paths = filedialog.askopenfilenames(
            title='Add custom DLLs',
            filetypes=[('DLL files', '*.dll')],
        )
        if paths:
            self._append_dll_paths(paths, 'custom')

    def remove_selected_dlls(self):
        selections = self.dll_tree.selection()
        if not selections:
            messagebox.showinfo('DLL Manager', 'Select one or more DLLs to remove.')
            return
        selected_paths = [self.dll_tree.item(item, 'values')[3] for item in selections]
        self.dll_specs = remove_dll_specs(self.dll_specs, selected_paths)
        self.refresh_dll_tree()

    def add_atlas_dlls(self):
        atlas_directory = self.atlas_install_var.get().strip()
        if not os.path.isdir(atlas_directory):
            messagebox.showerror('DLL Manager', 'Select a valid ATLAS installation folder first.')
            return

        dialog = tk.Toplevel(self)
        dialog.title('Add DLLs from ATLAS')
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry('900x600')
        dialog.minsize(650, 400)

        filter_frame = tk.Frame(dialog)
        filter_frame.pack(fill=tk.X, padx=8, pady=8)
        tk.Label(filter_frame, text='Filter:').pack(side=tk.LEFT)
        filter_var = tk.StringVar()
        tk.Entry(filter_frame, textvariable=filter_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        kind_var = tk.StringVar(value='All')
        ttk.Combobox(
            filter_frame,
            textvariable=kind_var,
            values=('All', 'Managed', 'Native'),
            state='readonly',
            width=12,
        ).pack(side=tk.LEFT)

        tree = ttk.Treeview(
            dialog,
            columns=('name', 'kind', 'relative_path'),
            show='headings',
            selectmode='extended',
        )
        tree.heading('name', text='DLL')
        tree.heading('kind', text='Type')
        tree.heading('relative_path', text='ATLAS-relative path')
        tree.column('name', width=220, anchor='w')
        tree.column('kind', width=90, anchor='w')
        tree.column('relative_path', width=500, anchor='w')
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        available = []
        dialog.config(cursor='watch')
        dialog.update_idletasks()
        for directory, child_directories, filenames in os.walk(atlas_directory):
            child_directories[:] = [name for name in child_directories if name.lower() not in ('obj',)]
            for filename in filenames:
                if filename.lower().endswith('.dll'):
                    path = os.path.join(directory, filename)
                    available.append({
                        'name': filename,
                        'path': path,
                        'kind': 'managed' if is_managed_dll(path) else 'native',
                        'relative_path': os.path.relpath(path, atlas_directory),
                    })
        available.sort(key=lambda item: (item['name'].lower(), item['relative_path'].lower()))
        dialog.config(cursor='')

        def refresh_available(*_):
            tree.delete(*tree.get_children())
            search = filter_var.get().strip().lower()
            selected_kind = kind_var.get().lower()
            for index, spec in enumerate(available):
                if selected_kind != 'all' and spec['kind'] != selected_kind:
                    continue
                searchable = f'{spec["name"]} {spec["relative_path"]}'.lower()
                if search and search not in searchable:
                    continue
                tree.insert('', tk.END, iid=str(index), values=(
                    spec['name'],
                    spec['kind'].title(),
                    spec['relative_path'],
                ))

        def add_selected():
            selected = [available[int(item)] for item in tree.selection()]
            if not selected:
                messagebox.showinfo('DLL Manager', 'Select one or more DLLs to add.', parent=dialog)
                return
            self._append_dll_paths([spec['path'] for spec in selected], 'atlas')
            dialog.destroy()

        filter_var.trace_add('write', refresh_available)
        kind_var.trace_add('write', refresh_available)
        tree.bind('<Double-1>', lambda event: add_selected())
        refresh_available()

        button_frame = tk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Button(button_frame, text='Add Selected', command=add_selected).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Cancel', command=dialog.destroy).pack(side=tk.LEFT, padx=4)

    def create_icon(self):
        from .icon_maker import open_icon_maker

        self.clear_generated_icon_temp_directory()
        temporary_directory = tempfile.mkdtemp(prefix='PluginGeneratorIcon-')
        self.generated_icon_temp_directory = temporary_directory
        path = open_icon_maker(
            self,
            temporary_directory,
            os.path.join(temporary_directory, 'icon.png'),
            self.set_icon_path,
        )
        if not path:
            self.clear_generated_icon_temp_directory()

    def set_icon_path(self, path):
        self.icon_var.set(os.path.abspath(path))
        self.icon_entry.icursor(tk.END)
        self.icon_entry.xview_moveto(1.0)
        self.update_idletasks()

    def clear_generated_icon_temp_directory(self):
        if self.generated_icon_temp_directory:
            current_icon = self.icon_var.get().strip() if hasattr(self, 'icon_var') else ''
            temporary_directory = os.path.abspath(self.generated_icon_temp_directory)
            if current_icon:
                try:
                    if os.path.commonpath((temporary_directory, os.path.abspath(current_icon))) == temporary_directory:
                        self.icon_var.set('')
                except ValueError:
                    pass
            shutil.rmtree(self.generated_icon_temp_directory, ignore_errors=True)
            self.generated_icon_temp_directory = None

    def refresh_property_tree(self):
        self.property_tree.delete(*self.property_tree.get_children())
        for spec in self.display_property_specs:
            self.property_tree.insert('', tk.END, values=(
                spec['name'],
                next(label for label, property_type in DISPLAY_PROPERTY_TYPES.items() if property_type == spec['type']),
                str(spec['default']),
                next(
                    label for label, action in DISPLAY_PROPERTY_ACTIONS.items()
                    if action == spec.get('change_action', 'none')
                ),
                spec['display_name'],
                'Yes' if spec['persisted'] else 'No',
                'Yes' if spec.get('read_only', False) else 'No',
                'Yes' if spec['browsable'] else 'No',
            ))

    def add_property_dialog(self):
        spec = self._property_dialog('Add Display Property')
        if spec:
            self.display_property_specs.append(spec)
            self.refresh_property_tree()

    def edit_selected_property(self):
        selection = self.property_tree.selection()
        if not selection:
            messagebox.showinfo('Edit Display Property', 'Select a display property to edit.')
            return
        index = self.property_tree.index(selection[0])
        current = self.display_property_specs[index]
        spec = self._property_dialog('Edit Display Property', initial=current, editing_name=current['name'])
        if spec:
            self.display_property_specs[index] = spec
            self.refresh_property_tree()

    def remove_selected_property(self):
        selection = self.property_tree.selection()
        if not selection:
            messagebox.showinfo('Remove Display Property', 'Select a display property to remove.')
            return
        index = self.property_tree.index(selection[0])
        del self.display_property_specs[index]
        self.refresh_property_tree()

    def _property_dialog(self, title, initial=None, editing_name=None):
        initial = initial or {}
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(True, True)
        dialog.minsize(320, 260)

        identifier_var = tk.StringVar(value=initial.get('name', ''))
        initial_type = initial.get('type', 'string')
        type_var = tk.StringVar(value=next(
            label for label, property_type in DISPLAY_PROPERTY_TYPES.items() if property_type == initial_type
        ))
        default_var = tk.StringVar(value=str(initial.get('default', '')))
        initial_action = initial.get('change_action', 'none')
        action_var = tk.StringVar(value=next(
            label for label, action in DISPLAY_PROPERTY_ACTIONS.items() if action == initial_action
        ))
        display_name_var = tk.StringVar(value=initial.get('display_name', ''))
        category_var = tk.StringVar(value=initial.get('category', ''))
        description_var = tk.StringVar(value=initial.get('description', ''))
        order_var = tk.StringVar(value='' if initial.get('order') is None else str(initial['order']))
        persisted_var = tk.BooleanVar(value=initial.get('persisted', False))
        read_only_var = tk.BooleanVar(value=initial.get('read_only', False))
        browsable_var = tk.BooleanVar(value=initial.get('browsable', True))

        fields = [
            ('Property Name (required):', identifier_var, 'entry'),
            ('Type:', type_var, 'type'),
            ('Default Value:', default_var, 'entry'),
            ('When Changed:', action_var, 'action'),
            ('Display Name:', display_name_var, 'entry'),
            ('Category:', category_var, 'entry'),
            ('Description:', description_var, 'entry'),
            ('Order:', order_var, 'entry'),
        ]
        for row, (label_text, var, field_kind) in enumerate(fields):
            tk.Label(dialog, text=label_text).grid(row=row, column=0, sticky='w', padx=8, pady=6)
            if field_kind in ('type', 'action'):
                choices = DISPLAY_PROPERTY_TYPES if field_kind == 'type' else DISPLAY_PROPERTY_ACTIONS
                ttk.Combobox(
                    dialog,
                    textvariable=var,
                    values=tuple(choices),
                    state='readonly',
                    width=33,
                ).grid(row=row, column=1, sticky='ew', padx=8, pady=6)
            else:
                tk.Entry(dialog, textvariable=var, width=35).grid(
                    row=row, column=1, sticky='ew', padx=8, pady=6
                )
        tk.Checkbutton(dialog, text='Persist to workbook', variable=persisted_var).grid(
            row=len(fields), column=0, columnspan=2, sticky='w', padx=8, pady=6)
        tk.Checkbutton(dialog, text='Read-only (generated without a setter)', variable=read_only_var).grid(
            row=len(fields) + 1, column=0, columnspan=2, sticky='w', padx=8, pady=6)
        tk.Checkbutton(dialog, text='Visible in properties window (Browsable)', variable=browsable_var).grid(
            row=len(fields) + 2, column=0, columnspan=2, sticky='w', padx=8, pady=6)
        dialog.columnconfigure(1, weight=1)

        result = {}

        def on_ok():
            existing_names = {
                spec['name'] for spec in self.display_property_specs if spec['name'] != editing_name
            }
            try:
                result['spec'] = build_display_property_spec(
                    identifier_var.get(),
                    display_name_var.get(),
                    category_var.get(),
                    description_var.get(),
                    order_var.get(),
                    persisted_var.get(),
                    browsable_var.get(),
                    DISPLAY_PROPERTY_TYPES[type_var.get()],
                    default_var.get(),
                    DISPLAY_PROPERTY_ACTIONS[action_var.get()],
                    read_only_var.get(),
                    existing_names=existing_names,
                )
            except ValueError as error:
                messagebox.showerror('Invalid Display Property', str(error), parent=dialog)
                return
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        button_frame = tk.Frame(dialog)
        button_frame.grid(row=len(fields) + 3, column=0, columnspan=2, pady=10)
        tk.Button(button_frame, text='OK', command=on_ok, width=10).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Cancel', command=on_cancel, width=10).pack(side=tk.LEFT, padx=4)

        dialog.protocol('WM_DELETE_WINDOW', on_cancel)
        dialog.wait_window()
        return result.get('spec')

    def refresh_command_tree(self):
        self.command_tree.delete(*self.command_tree.get_children())
        for spec in self.command_specs:
            self.command_tree.insert('', tk.END, values=(
                f'{spec["name"]}Command',
                next(label for label, action in COMMAND_ACTIONS.items() if action == spec.get('action', 'custom')),
                spec.get('target_property', ''),
                spec['button_label'],
                'Yes' if spec['include_button'] else 'No',
                'Generated' if spec.get('generate_can_execute', False) else 'Always',
                'Yes' if spec.get('generate_log', False) else 'No',
                'Yes' if spec.get('break_when_attached', False) else 'No',
            ))

    def add_command_dialog(self):
        spec = self._command_dialog('Add Command')
        if spec:
            self.command_specs.append(spec)
            self.refresh_command_tree()

    def edit_selected_command(self):
        selection = self.command_tree.selection()
        if not selection:
            messagebox.showinfo('Edit Command', 'Select a command to edit.')
            return
        index = self.command_tree.index(selection[0])
        current = self.command_specs[index]
        spec = self._command_dialog('Edit Command', initial=current, editing_name=current['name'])
        if spec:
            self.command_specs[index] = spec
            self.refresh_command_tree()

    def remove_selected_command(self):
        selection = self.command_tree.selection()
        if not selection:
            messagebox.showinfo('Remove Command', 'Select a command to remove.')
            return
        index = self.command_tree.index(selection[0])
        del self.command_specs[index]
        self.refresh_command_tree()

    def _command_dialog(self, title, initial=None, editing_name=None):
        initial = initial or {}
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(True, False)

        name_var = tk.StringVar(value=initial.get('name', ''))
        button_label_var = tk.StringVar(value=initial.get('button_label', ''))
        include_button_var = tk.BooleanVar(value=initial.get('include_button', True))
        can_execute_var = tk.BooleanVar(value=initial.get('generate_can_execute', False))
        generate_log_var = tk.BooleanVar(value=initial.get('generate_log', False))
        breakpoint_var = tk.BooleanVar(value=initial.get('break_when_attached', False))
        initial_action = initial.get('action', 'custom')
        action_var = tk.StringVar(value=next(
            label for label, action in COMMAND_ACTIONS.items() if action == initial_action
        ))
        target_property_var = tk.StringVar(value=initial.get('target_property', ''))
        action_value_var = tk.StringVar(value=initial.get('action_value', ''))

        tk.Label(dialog, text='Action Name (required):').grid(row=0, column=0, sticky='w', padx=8, pady=6)
        tk.Entry(dialog, textvariable=name_var, width=35).grid(row=0, column=1, sticky='ew', padx=8, pady=6)
        tk.Label(dialog, text='Button Label:').grid(row=1, column=0, sticky='w', padx=8, pady=6)
        tk.Entry(dialog, textvariable=button_label_var, width=35).grid(row=1, column=1, sticky='ew', padx=8, pady=6)
        tk.Label(dialog, text='Command Action:').grid(row=2, column=0, sticky='w', padx=8, pady=6)
        action_combo = ttk.Combobox(
            dialog, textvariable=action_var, values=tuple(COMMAND_ACTIONS), state='readonly', width=32
        )
        action_combo.grid(row=2, column=1, sticky='ew', padx=8, pady=6)
        tk.Label(dialog, text='Target Property:').grid(row=3, column=0, sticky='w', padx=8, pady=6)
        target_combo = ttk.Combobox(
            dialog,
            textvariable=target_property_var,
            values=tuple(spec['name'] for spec in self.display_property_specs),
            state='readonly',
            width=32,
        )
        target_combo.grid(row=3, column=1, sticky='ew', padx=8, pady=6)
        tk.Label(dialog, text='Value (for Set):').grid(row=4, column=0, sticky='w', padx=8, pady=6)
        value_entry = tk.Entry(dialog, textvariable=action_value_var, width=35)
        value_entry.grid(row=4, column=1, sticky='ew', padx=8, pady=6)
        tk.Checkbutton(dialog, text='Add button to generated view', variable=include_button_var).grid(
            row=5, column=0, columnspan=2, sticky='w', padx=8, pady=6
        )
        tk.Checkbutton(
            dialog,
            text='Generate an enabled/disabled rule (CanExecute)',
            variable=can_execute_var,
        ).grid(row=6, column=0, columnspan=2, sticky='w', padx=8, pady=6)
        tk.Checkbutton(
            dialog,
            text='Log when the command runs (injects ILogger when needed)',
            variable=generate_log_var,
        ).grid(row=7, column=0, columnspan=2, sticky='w', padx=8, pady=6)
        tk.Checkbutton(
            dialog,
            text='Break into the debugger when one is attached',
            variable=breakpoint_var,
        ).grid(row=8, column=0, columnspan=2, sticky='w', padx=8, pady=6)

        def update_action_fields(*_args):
            action = COMMAND_ACTIONS[action_var.get()]
            target_combo.config(state='disabled' if action == 'custom' else 'readonly')
            value_entry.config(state=tk.NORMAL if action == 'set' else tk.DISABLED)

        action_combo.bind('<<ComboboxSelected>>', update_action_fields)
        update_action_fields()
        dialog.columnconfigure(1, weight=1)

        result = {}

        def on_ok():
            existing_names = {spec['name'] for spec in self.command_specs if spec['name'] != editing_name}
            try:
                command_spec = build_command_spec(
                    name_var.get(),
                    button_label_var.get(),
                    include_button_var.get(),
                    existing_names,
                    can_execute_var.get(),
                    generate_log_var.get(),
                    breakpoint_var.get(),
                    COMMAND_ACTIONS[action_var.get()],
                    target_property_var.get(),
                    action_value_var.get(),
                )
                validate_command_actions([command_spec], self.display_property_specs)
                result['spec'] = command_spec
            except ValueError as error:
                messagebox.showerror('Invalid Command', str(error), parent=dialog)
                return
            dialog.destroy()

        button_frame = tk.Frame(dialog)
        button_frame.grid(row=9, column=0, columnspan=2, pady=10)
        tk.Button(button_frame, text='OK', command=on_ok, width=10).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Cancel', command=dialog.destroy, width=10).pack(side=tk.LEFT, padx=4)
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
        dialog.wait_window()
        return result.get('spec')

    def reset_form(self):
        self.clear_generated_icon_temp_directory()
        self.name_var.set('')
        self.description_var.set('')
        self.atlas_parameter_text.delete('1.0', tk.END)
        self.display_property_specs = []
        self.refresh_property_tree()
        self.command_specs = []
        self.refresh_command_tree()
        self.refresh_deployed_plugins()
        self.icon_var.set('')
        self.atlas_install_var.set(DEFAULT_ATLAS_INSTALL_DIRECTORY)
        self.parameter_max_var.set('100')
        self.behavior_var.set(BEHAVIOR_CURRENT_VALUE)
        self.basic_layout_var.set('text')
        for service_var in self.service_vars.values():
            service_var.set(False)
        self.update_behavior_states()
        self.open_folder_var.set(True)
        self.build_after_generation_var.set(True)
        self.status_state_var.set(False)
        self.lifecycle_hooks_var.set(False)
        self.session_notifications_var.set(False)
        self.item_collection_var.set(False)
        self.collection_name_var.set('Items')
        self.item_class_name_var.set('ItemViewModel')
        self.item_fields_var.set('Name:string')
        self.graph_type_var.set('none')
        self.computed_series_var.set('')
        self.graph_title_var.set('')
        self.graph_units_var.set('')
        self.graph_legend_var.set(True)
        self.overlay_cursor_bars_var.set(False)
        self.pair_cursor_points_by_half_var.set(False)
        self.update_graph_states()
        messagebox.showinfo('Reset', 'Form has been reset to default values')

    def update_behavior_states(self):
        # Data behaviors inject these services through DisplayPluginLibrary base classes.
        parameters_enabled = behavior_uses_parameters(self.behavior_var.get())
        if hasattr(self, 'sample_count_entry'):
            uses_samples = self.behavior_var.get() in (BEHAVIOR_VISIBLE_RANGE, BEHAVIOR_CURRENT_AND_RANGE)
            self.sample_count_entry.config(state=tk.NORMAL if uses_samples else tk.DISABLED)
        for service_name in ('ILogger', 'ISignalBus', 'IDataRequestSignalFactory'):
            checkbutton = self.service_checkbuttons[service_name]
            if parameters_enabled:
                self.service_vars[service_name].set(True)
                checkbutton.config(state=tk.DISABLED)
            else:
                checkbutton.config(state=tk.NORMAL)
        if hasattr(self, 'atlas_parameter_text'):
            self.atlas_parameter_text.config(state=tk.NORMAL if parameters_enabled else tk.DISABLED)
        if hasattr(self, 'item_collection_checkbutton'):
            if parameters_enabled:
                self.item_collection_var.set(False)
                self.item_collection_checkbutton.config(state=tk.DISABLED)
            else:
                self.item_collection_checkbutton.config(state=tk.NORMAL)
        if hasattr(self, 'basic_layout_combo'):
            self.basic_layout_combo.config(state='readonly' if not parameters_enabled else 'disabled')
            if parameters_enabled:
                self.basic_layout_var.set('text')
        for widget_name in ('collection_name_entry', 'item_class_name_entry', 'item_fields_entry'):
            if hasattr(self, widget_name):
                getattr(self, widget_name).config(state=tk.NORMAL if not parameters_enabled else tk.DISABLED)
        if hasattr(self, 'graph_type_combo'):
            behavior = self.behavior_var.get()
            if behavior == BEHAVIOR_CURRENT_VALUE:
                graph_choices = ('none', 'cursor-histogram', 'cursor-points')
            elif behavior in (BEHAVIOR_VISIBLE_RANGE, BEHAVIOR_CURRENT_AND_RANGE):
                graph_choices = ('none', 'time-series', 'scatter', 'histogram', 'bar', 'custom')
            elif behavior == BEHAVIOR_COMPARE_SESSIONS:
                graph_choices = ('none', 'cursor-histogram', 'cursor-points')
            else:
                graph_choices = ('none',)
            self.graph_type_combo.config(values=graph_choices)
            graph_enabled = len(graph_choices) > 1
            self.graph_type_combo.config(state='readonly' if graph_enabled else 'disabled')
            if self.graph_type_var.get() not in graph_choices:
                self.graph_type_var.set('none')
            self.update_graph_states()

    def infer_parameter_max_count(self, _event=None):
        if not hasattr(self, 'atlas_parameter_text') or not hasattr(self, 'parameter_max_var'):
            return
        count = count_parameter_entries(self.atlas_parameter_text.get('1.0', tk.END))
        self.parameter_max_var.set(str(max(1, count)))

    def update_graph_states(self):
        if not hasattr(self, 'graph_title_entry'):
            return
        state = tk.NORMAL if self.graph_type_var.get() != 'none' else tk.DISABLED
        self.graph_title_entry.config(state=state)
        self.graph_units_entry.config(state=state)
        self.computed_series_entry.config(state=state)
        self.graph_legend_checkbutton.config(state=state)
        overlay_state = tk.NORMAL if self.graph_type_var.get() in ('cursor-histogram', 'cursor-points') else tk.DISABLED
        self.overlay_cursor_bars_checkbutton.config(state=overlay_state)
        if overlay_state == tk.DISABLED:
            self.overlay_cursor_bars_var.set(False)
        pair_state = (
            tk.NORMAL
            if self.graph_type_var.get() == 'cursor-points' and self.overlay_cursor_bars_var.get()
            else tk.DISABLED
        )
        self.pair_cursor_points_by_half_checkbutton.config(state=pair_state)
        if pair_state == tk.DISABLED:
            self.pair_cursor_points_by_half_var.set(False)

    def clear_saved_paths(self):
        if not messagebox.askyesno('Clear Saved Paths', 'Delete the persisted output, library, icon, and ATLAS paths?'):
            return
        clear_settings()
        self.out_var.set('')
        self.library_var.set('')
        self.icon_var.set('')
        self.atlas_install_var.set(DEFAULT_ATLAS_INSTALL_DIRECTORY)
        messagebox.showinfo('Clear Saved Paths', 'Persisted paths were cleared.')

    def build_preset_configuration(self):
        return {
            'name': self.name_var.get(),
            'description': self.description_var.get(),
            'behavior': self.behavior_var.get(),
            'basic_layout': self.basic_layout_var.get(),
            'atlas_parameters': self.atlas_parameter_text.get('1.0', tk.END).splitlines(),
            'display_properties': self.display_property_specs,
            'commands': self.command_specs,
            'services': [name for name, var in self.service_vars.items() if var.get()],
            'parameter_max_count': self.parameter_max_var.get(),
            'include_status_state': self.status_state_var.get(),
            'include_lifecycle_hooks': self.lifecycle_hooks_var.get(),
            'include_session_notifications': self.session_notifications_var.get(),
            'include_item_collection': self.item_collection_var.get(),
            'collection_name': self.collection_name_var.get(),
            'item_class_name': self.item_class_name_var.get(),
            'item_fields': self.item_fields_var.get(),
            'graph_type': self.graph_type_var.get(),
            'computed_series': self.computed_series_var.get(),
            'graph_title': self.graph_title_var.get(),
            'graph_units': self.graph_units_var.get(),
            'show_graph_legend': self.graph_legend_var.get(),
            'overlay_cursor_bars': self.overlay_cursor_bars_var.get(),
            'pair_cursor_points_by_half': self.pair_cursor_points_by_half_var.get(),
        }

    def apply_preset_configuration(self, configuration):
        self.name_var.set(configuration.get('name', ''))
        self.description_var.set(configuration.get('description', ''))
        self.behavior_var.set(configuration.get('behavior', BEHAVIOR_CURRENT_VALUE))
        self.basic_layout_var.set(configuration.get('basic_layout', 'text'))
        self.atlas_parameter_text.delete('1.0', tk.END)
        self.atlas_parameter_text.insert('1.0', '\n'.join(configuration.get('atlas_parameters', [])))
        self.display_property_specs = list(configuration.get('display_properties', []))
        self.command_specs = list(configuration.get('commands', []))
        self.dll_specs = []
        self.refresh_property_tree()
        self.refresh_command_tree()
        self.refresh_deployed_plugins()
        selected_services = set(configuration.get('services', []))
        for name, var in self.service_vars.items():
            var.set(name in selected_services)
        self.parameter_max_var.set(str(configuration.get('parameter_max_count', '100')))
        self.status_state_var.set(configuration.get('include_status_state', False))
        self.lifecycle_hooks_var.set(configuration.get('include_lifecycle_hooks', False))
        self.session_notifications_var.set(configuration.get('include_session_notifications', False))
        self.item_collection_var.set(configuration.get('include_item_collection', False))
        self.collection_name_var.set(configuration.get('collection_name', 'Items'))
        self.item_class_name_var.set(configuration.get('item_class_name', 'ItemViewModel'))
        self.item_fields_var.set(configuration.get('item_fields', 'Name:string'))
        self.graph_type_var.set(configuration.get('graph_type', 'none'))
        self.computed_series_var.set(configuration.get('computed_series', ''))
        self.graph_title_var.set(configuration.get('graph_title', ''))
        self.graph_units_var.set(configuration.get('graph_units', ''))
        self.graph_legend_var.set(configuration.get('show_graph_legend', True))
        self.overlay_cursor_bars_var.set(configuration.get('overlay_cursor_bars', False))
        self.pair_cursor_points_by_half_var.set(configuration.get('pair_cursor_points_by_half', False))
        self.update_behavior_states()

    def save_preset_dialog(self):
        path = filedialog.asksaveasfilename(
            title='Save PluginGenerator Preset',
            defaultextension='.json',
            filetypes=[('JSON preset', '*.json')],
        )
        if path:
            save_preset(path, self.build_preset_configuration())

    def load_preset_dialog(self):
        path = filedialog.askopenfilename(
            title='Load PluginGenerator Preset',
            filetypes=[('JSON preset', '*.json')],
        )
        if not path:
            return
        try:
            self.apply_preset_configuration(load_preset(path))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror('Load Preset', str(error))

    def generate(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror('Error', 'Please enter a plugin name')
            return

        base_out = self.out_var.get().strip()
        library_project = self.library_var.get().strip()
        icon_path = self.icon_var.get().strip()
        try:
            include_parameters = behavior_uses_parameters(self.behavior_var.get())
            if not base_out:
                raise ValueError('Select an output folder before generating.')
            if include_parameters and not library_project:
                raise ValueError('Select DisplayPluginLibrary.csproj before generating a data plugin.')
            if not icon_path:
                raise ValueError('Select a PNG icon before generating the plugin.')
            atlas_parameters = []
            existing_atlas_parameters = set()
            for line in self.atlas_parameter_text.get('1.0', tk.END).splitlines():
                if line.strip():
                    identifier = build_atlas_parameter(line, existing_atlas_parameters)
                    atlas_parameters.append(identifier)
                    existing_atlas_parameters.add(identifier)
            display_property_specs = list(self.display_property_specs)
            command_specs = list(self.command_specs)
            parameter_max_count = int(self.parameter_max_var.get())
            item_field_specs = [
                build_item_field_spec(value)
                for value in self.item_fields_var.get().split(',')
                if value.strip()
            ]
            computed_series_specs = [
                build_computed_series_spec(value)
                for value in self.computed_series_var.get().split(',')
                if value.strip()
            ]
            graph_units_text = self.graph_units_var.get().strip()
            graph_units = [unit.strip() for unit in graph_units_text.split(',')] if graph_units_text else []
            if atlas_parameters and not include_parameters:
                raise ValueError('ATLAS parameters require Current value or Visible range behavior.')
            service_names = [name for name, var in self.service_vars.items() if var.get()]
            summary = build_generation_summary(
                name,
                self.behavior_var.get(),
                True,
                atlas_parameters,
                display_property_specs,
                command_specs,
                service_names,
                basic_layout=self.basic_layout_var.get(),
                include_status_state=self.status_state_var.get(),
                include_lifecycle_hooks=self.lifecycle_hooks_var.get(),
                include_session_notifications=self.session_notifications_var.get(),
                include_item_collection=self.item_collection_var.get(),
                collection_name=self.collection_name_var.get().strip(),
                item_class_name=self.item_class_name_var.get().strip(),
                item_field_specs=item_field_specs,
                graph_type=self.graph_type_var.get(),
                dll_specs=self.dll_specs,
            )
            if not messagebox.askokcancel('Generation Preview', summary):
                return
            os.makedirs(base_out, exist_ok=True)
            target = generate_plugin(
                name,
                base_out,
                include_view=True,
                include_parameters=include_parameters,
                behavior=self.behavior_var.get(),
                atlas_parameters=atlas_parameters,
                display_property_specs=display_property_specs,
                command_specs=command_specs,
                include_status_state=self.status_state_var.get(),
                include_lifecycle_hooks=self.lifecycle_hooks_var.get(),
                include_session_notifications=self.session_notifications_var.get(),
                include_item_collection=self.item_collection_var.get(),
                basic_layout=self.basic_layout_var.get(),
                collection_name=self.collection_name_var.get().strip(),
                item_class_name=self.item_class_name_var.get().strip(),
                item_field_specs=item_field_specs,
                graph_type=self.graph_type_var.get(),
                computed_series_specs=computed_series_specs,
                graph_title=self.graph_title_var.get(),
                graph_units=graph_units,
                show_graph_legend=self.graph_legend_var.get(),
                overlay_cursor_bars=self.overlay_cursor_bars_var.get(),
                pair_cursor_points_by_half=self.pair_cursor_points_by_half_var.get(),
                parameter_max_count=parameter_max_count,
                workspace_root=default_workspace_root(),
                description=self.description_var.get().strip() or None,
                library_project=library_project,
                icon_path=icon_path,
                service_names=service_names,
                dll_specs=self.dll_specs,
                atlas_install_directory=self.atlas_install_var.get().strip(),
                sample_count=self.sample_count_var.get(),
            )
            copied_icon_path = os.path.join(
                target,
                os.path.basename(target),
                'Resources',
                os.path.basename(icon_path),
            )
            self.clear_generated_icon_temp_directory()
            self.set_icon_path(copied_icon_path)
            save_settings({
                'output_folder': base_out,
                'library_project': library_project,
                'icon_path': copied_icon_path,
                'atlas_install_directory': self.atlas_install_var.get().strip(),
            })

            build_succeeded = False
            if self.build_after_generation_var.get():
                self.update_idletasks()
                build_generated_plugin(target)
                build_succeeded = True

            # Show success message
            generated_name = os.path.basename(target)
            success_msg = f'Plugin "{generated_name}" created successfully at:\n{target}'
            if build_succeeded:
                success_msg += '\n\nBuild validation succeeded.'
            messagebox.showinfo('Success', success_msg)
            
            # Open folder if requested
            if self.open_folder_var.get():
                import subprocess
                import platform
                if platform.system() == 'Windows':
                    os.startfile(target)
                elif platform.system() == 'Darwin':  # macOS
                    subprocess.Popen(['open', target])
                else:  # Linux
                    subprocess.Popen(['xdg-open', target])
            
            # Ask if user wants to reset form
            if messagebox.askyesno('Continue', 'Create another plugin?'):
                self.reset_form()
            else:
                self.quit()
        except Exception as ex:
            messagebox.showerror('Error', str(ex))


def main():
    app = PluginGeneratorApp()
    app.mainloop()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--remove-deployed-plugin-files':
        remove_deployed_plugin_files(sys.argv[2:])
    else:
        main()
