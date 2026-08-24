import os
import re
import json
import math
import html
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import shutil
import subprocess
import uuid


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
  <Target Name="PostBuild" AfterTargets="PostBuildEvent" Condition="'$(DeployAtlasPlugin)' == 'true'">
    <Exec Command="python &quot;$(SolutionDir)scripts\deploy.py&quot; &quot;$(TargetDir)$(ProjectName).dll&quot;" />
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


def relaunch_elevated(dll_path):
    parameters = subprocess.list2cmdline([__file__, str(dll_path)])
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


def deploy(dll_path):
    dll_path = Path(dll_path).resolve()
    if not dll_path.is_file():
        raise FileNotFoundError(f'Build output not found: {{dll_path}}')
    if not is_elevated():
        return relaunch_elevated(dll_path)
    DESTINATION.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dll_path, DESTINATION / dll_path.name)
    print(f'Deployed {{dll_path.name}} to {{DESTINATION}}')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Deploy a built ATLAS display plugin.')
    parser.add_argument('dll_path')
    arguments = parser.parse_args()
    try:
        sys.exit(deploy(arguments.dll_path))
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
{display_property_fields}
        public {viewmodel_class}(
            ISignalBus signalBus,
            IDataRequestSignalFactory dataRequestSignalFactory,
            ILogger logger{extra_ctor_params}) :
            base(signalBus, dataRequestSignalFactory, logger)
        {{
{extra_ctor_assignments}{command_initializers}        }}

{display_properties}
{command_properties}
    {atlas_parameter_setup}
        protected override ParameterViewModel OnCreateParameterViewModel() => new ParameterViewModel();

{command_handlers}
    }}
}}
'''

BASIC_VIEWMODEL_TEMPLATE = '''using System.ComponentModel;
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
{display_property_fields}
{service_members}
{display_properties}
{command_properties}
{command_handlers}    }}
}}
'''

TIMEBASE_VIEWMODEL_TEMPLATE = '''using System;
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
{display_property_fields}
        public {viewmodel_class}(
            ISignalBus signalBus,
            IDataRequestSignalFactory dataRequestSignalFactory,
            ILogger logger{extra_ctor_params}) :
            base(signalBus, dataRequestSignalFactory, logger)
        {{
            this.Disposables.Add(this.SignalBus.Subscribe<DataResultSignal>(
                this.HandleDataResultSignal,
                signal => signal.SourceId == this.ScopeIdentity.Guid));
{cursor_subscription}
{extra_ctor_assignments}{command_initializers}        }}

        [Category("Data")]
        [DisplayName("Sample Count")]
        [Description("Maximum number of samples requested across the visible time range.")]
        [Display(Order = 0)]
        public int DataRequestSampleCount
        {{
            get => this.dataRequestSampleCount = this.ReadProperty(1000);
            set
            {{
                if (this.SetProperty(ref this.dataRequestSampleCount, value))
                {{
                    this.SaveProperty(value);
                    this.MakeDataRequests(false, true);
                }}
            }}
        }}

        [Browsable(false)]
        public ObservableCollection<TimebaseSeriesViewModel> Series {{ get; }} =
            new ObservableCollection<TimebaseSeriesViewModel>();

{display_properties}
{command_properties}
    {atlas_parameter_setup}
        protected override async Task OnMakeTimebaseDataRequestsAsync(ICompositeSession compositeSession)
        {{
            await this.ExecuteOnUiAsync(this.SyncSeries);

            foreach (var parameter in this.DisplayParameterService.PrimaryParameters)
            {{
                var signal = this.DataRequestSignalFactory.CreateDataRequestSignal(
                    this.ScopeIdentity.Guid,
                    parameter,
                    compositeSession.TimebaseRange,
                    this.DataRequestSampleCount,
                    SampleMode.MaximumToMinimum);

                this.SignalBus.Send(signal);
            }}
        }}

{cursor_request_method}
{cursor_result_handler}

        private async void HandleDataResultSignal(DataResultSignal signal)
        {{
            try
            {{
                var parameterValues = signal.Data.ParameterValues;
                long[] timestamps;
                double[] values;
                parameterValues.Lock();
                try
                {{
                    timestamps = parameterValues.Timestamp.ToArray();
                    values = parameterValues.Data.ToArray();
                }}
                finally
                {{
                    parameterValues.Unlock();
                }}

                await this.ExecuteOnUiAsync(() =>
                {{
                    var series = this.Series.FirstOrDefault(item =>
                        item.ParameterIdentifier == signal.Data.Request.Parameter.InstanceIdentifier);
                    series?.Update(timestamps, values);
                }});
            }}
            catch (Exception exception)
            {{
                this.Logger.Trace("Error handling visible-range data", exception);
            }}
        }}

        private void SyncSeries()
        {{
            var existing = this.Series.ToDictionary(item => item.ParameterIdentifier);
            this.Series.Clear();
            foreach (var parameter in this.DisplayParameterService.PrimaryParameters)
            {{
                if (existing.TryGetValue(parameter.InstanceIdentifier, out var series))
                {{
                    series.Name = parameter.Name;
                    this.Series.Add(series);
                }}
                else
                {{
                    this.Series.Add(new TimebaseSeriesViewModel(
                        parameter.InstanceIdentifier,
                        parameter.Name));
                }}
            }}
        }}

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
{current_value_field}
        private string name;
        private int sampleCount;
        private IReadOnlyList<long> timestamps = Array.Empty<long>();
        private IReadOnlyList<double> values = Array.Empty<double>();

        public TimebaseSeriesViewModel(Guid parameterIdentifier, string name)
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
            var validValues = values.Where(value => !double.IsNaN(value)).ToArray();
            this.SampleCount = validValues.Length;
            this.Minimum = validValues.Length == 0 ? double.NaN : validValues.Min();
            this.Maximum = validValues.Length == 0 ? double.NaN : validValues.Max();
        }}

{current_value_update_method}
    }}
}}
'''

CURSOR_SUBSCRIPTION = '''            this.Disposables.Add(this.SignalBus.Subscribe<SampleResultSignal>(
                this.HandleSampleResultSignal,
                signal => signal.SourceId == this.ScopeIdentity.Guid));'''

CURSOR_REQUEST_METHOD = '''        protected override Task OnMakeCursorDataRequestsAsync(ICompositeSession compositeSession)
        {
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

            return Task.CompletedTask;
        }'''

CURSOR_RESULT_HANDLER = '''        private async void HandleSampleResultSignal(SampleResultSignal signal)
        {
            try
            {
                var parameterValues = signal.Data.ParameterValues;
                double value;
                parameterValues.Lock();
                try
                {
                    if (parameterValues.SampleCount == 0)
                    {
                        return;
                    }

                    value = parameterValues.Data[0];
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
                    series?.UpdateCurrentValue(value);
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

CURRENT_VALUE_UPDATE_METHOD = '''        public void UpdateCurrentValue(double value)
        {
            this.CurrentValue = value;
        }'''

CURRENT_VALUE_TEXT = '''                            <TextBlock Text="{Binding CurrentValue, StringFormat='Current: {0:F3}'}"
                                       FontSize="20" Foreground="White" />'''

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
{display_property_fields}
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

{display_properties}
{command_properties}
    {atlas_parameter_setup}
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
                var updates = new List<(CompositeSessionKey SessionKey, double Value)>();
                foreach (var result in signal.Data.Results)
                {{
                    var parameterValues = result.Value.ParameterValues;
                    parameterValues.Lock();
                    try
                    {{
                        if (parameterValues.SampleCount > 0 && !double.IsNaN(parameterValues.Data[0]))
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
        }}

{command_handlers}
    }}
}}
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

        public void Update(CompositeSessionKey sessionKey, double value)
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

        public CompareSessionValueViewModel(CompositeSessionKey sessionKey, string sessionName)
        {{
            this.SessionKey = sessionKey;
            this.sessionName = sessionName;
        }}

        [Browsable(false)]
        public CompositeSessionKey SessionKey {{ get; }}

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

VIEW_XAML_HEADER = '''<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
             xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
             xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
             xmlns:d="http://schemas.microsoft.com/expression/blend/2008"
             mc:Ignorable="d"
             d:DesignHeight="450" d:DesignWidth="800"'''

VIEW_XAML_TEMPLATE = VIEW_XAML_HEADER + '''
             x:Class="{namespace}.{view_class}">
    <ScrollViewer HorizontalScrollBarVisibility="Auto" VerticalScrollBarVisibility="Auto">
        <DockPanel>
            <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="4">
{command_buttons}            </StackPanel>
            <ItemsControl ItemsSource="{{Binding Parameters}}">
            <ItemsControl.ItemsPanel>
                <ItemsPanelTemplate>
                    <UniformGrid Columns="2" />
                </ItemsPanelTemplate>
            </ItemsControl.ItemsPanel>
            <ItemsControl.ItemTemplate>
                <DataTemplate>
                    <Border BorderBrush="DarkGray" BorderThickness="1" Padding="12" Margin="4">
                        <StackPanel>
                            <TextBlock Text="{{Binding Name}}" FontWeight="Bold" Foreground="White" />
                            <TextBlock Text="{{Binding Value, StringFormat=F3}}" FontSize="24" Foreground="White" />
                            <TextBlock Text="{{Binding Description}}" Foreground="White" />
                        </StackPanel>
                    </Border>
                </DataTemplate>
            </ItemsControl.ItemTemplate>
        </ItemsControl>
    </ScrollViewer>
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

BASIC_VIEW_XAML_TEMPLATE = VIEW_XAML_HEADER + '''
             x:Class="{namespace}.{view_class}">
    <Grid>
        <StackPanel VerticalAlignment="Center" HorizontalAlignment="Center">
            <StackPanel Orientation="Horizontal" HorizontalAlignment="Center" Margin="4">
{command_buttons}            </StackPanel>
            <TextBlock Text="{view_class}"
                   VerticalAlignment="Center"
                   HorizontalAlignment="Center"
                   Foreground="White"
                   FontSize="20" />
        </StackPanel>
    </Grid>
</UserControl>
'''

TIMEBASE_VIEW_XAML_TEMPLATE = VIEW_XAML_HEADER + '''
             x:Class="{namespace}.{view_class}">
    <ScrollViewer HorizontalScrollBarVisibility="Auto" VerticalScrollBarVisibility="Auto">
        <DockPanel>
            <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="4">
{command_buttons}            </StackPanel>
            <ItemsControl ItemsSource="{{Binding Series}}">
            <ItemsControl.ItemTemplate>
                <DataTemplate>
                    <Border BorderBrush="DarkGray" BorderThickness="1" Padding="12" Margin="4">
                        <StackPanel>
                            <TextBlock Text="{{Binding Name}}" FontWeight="Bold" Foreground="White" />
{current_value_text}
                            <TextBlock Text="{{Binding SampleCount, StringFormat='Samples: {{0}}'}}" Foreground="White" />
                            <TextBlock Text="{{Binding Minimum, StringFormat='Minimum: {{0:F3}}'}}" Foreground="White" />
                            <TextBlock Text="{{Binding Maximum, StringFormat='Maximum: {{0:F3}}'}}" Foreground="White" />
                        </StackPanel>
                    </Border>
                </DataTemplate>
            </ItemsControl.ItemTemplate>
            </ItemsControl>
        </DockPanel>
    </ScrollViewer>
</UserControl>
'''

COMPARE_VIEW_XAML_TEMPLATE = VIEW_XAML_HEADER + '''
             x:Class="{namespace}.{view_class}">
    <ScrollViewer HorizontalScrollBarVisibility="Auto" VerticalScrollBarVisibility="Auto">
        <DockPanel>
            <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="4">
{command_buttons}            </StackPanel>
            <ItemsControl ItemsSource="{{Binding Rows}}">
            <ItemsControl.ItemTemplate>
                <DataTemplate>
                    <Border BorderBrush="DarkGray" BorderThickness="1" Padding="12" Margin="4">
                        <StackPanel>
                            <TextBlock Text="{{Binding Name}}" FontWeight="Bold" Foreground="White" />
                            <ItemsControl ItemsSource="{{Binding SessionValues}}">
                                <ItemsControl.ItemsPanel>
                                    <ItemsPanelTemplate>
                                        <StackPanel Orientation="Horizontal" />
                                    </ItemsPanelTemplate>
                                </ItemsControl.ItemsPanel>
                                <ItemsControl.ItemTemplate>
                                    <DataTemplate>
                                        <StackPanel Margin="0,4,20,0">
                                            <TextBlock Text="{{Binding SessionName}}" Foreground="LightGray" />
                                            <TextBlock Text="{{Binding Value, StringFormat=F3}}"
                                                       FontSize="20" Foreground="White" />
                                        </StackPanel>
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
        name += 'Plugin'
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
    'Number': 'double',
    'Boolean': 'bool',
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
    if property_type == 'int':
        if not text:
            return 0
        try:
            return int(text)
        except ValueError as error:
            raise ValueError('Integer property default must be a whole number.') from error
    if property_type == 'double':
        if not text:
            return 0.0
        try:
            value = float(text)
        except ValueError as error:
            raise ValueError('Number property default must be numeric.') from error
        if not math.isfinite(value):
            raise ValueError('Number property default must be finite.')
        return value
    if property_type == 'bool':
        if not text:
            return False
        normalized = text.lower()
        if normalized in ('true', 'yes', '1'):
            return True
        if normalized in ('false', 'no', '0'):
            return False
        raise ValueError('Boolean property default must be true or false.')
    raise ValueError(f'Unsupported display property type: {property_type}')


def build_display_property_spec(name, display_name='', category='', description='', order='', persisted=False,
                                browsable=True, property_type='string', default_value='', change_action='none',
                                existing_names=None):
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
    if spec['type'] == 'double':
        return f'{format(value, ".15g")}d'
    if spec['type'] == 'bool':
        return 'true' if value else 'false'
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
    if spec['persisted'] or action_statement:
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
    'ISignalBus': {'namespace': 'MAT.Atlas.Api.Core.Signals', 'param': 'signalBus'},
    'IDataRequestSignalFactory': {'namespace': 'MAT.Atlas.Client.Platform.Data', 'param': 'dataRequestSignalFactory'},
    'ISessionService': {'namespace': 'MAT.Atlas.Client.Platform.Sessions', 'param': 'sessionService'},
    'ISessionSummaryService': {'namespace': 'MAT.Atlas.Client.Platform.Sessions', 'param': 'sessionSummaryService'},
    'ISessionCursorService': {'namespace': 'MAT.Atlas.Client.Platform.Sessions', 'param': 'sessionCursorService'},
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
            '-p:DeployAtlasPlugin=false',
        ]
    elif tool_kind == 'msbuild':
        command = [
            executable,
            solution_path,
            '-restore',
            '-p:Configuration=Debug',
            '-p:Platform=x64',
            '-p:DeployAtlasPlugin=false',
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


def build_command_spec(name, button_label='', include_button=True, existing_names=None, generate_can_execute=False):
    name = (name or '').strip()
    if name.endswith('Command'):
        name = name[:-len('Command')]
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError('Command name must be a valid C# identifier.')
    if existing_names and name in existing_names:
        raise ValueError(f'A command named "{name}" already exists.')
    return {
        'name': name,
        'button_label': (button_label or '').strip() or command_display_label(name),
        'include_button': bool(include_button),
        'generate_can_execute': bool(generate_can_execute),
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


def build_command_handler(spec):
    handler = (
        f'        private void On{spec["name"]}()\n'
        '        {\n'
        f'            // TODO: Implement {spec["name"]}.\n'
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
        'Margin="0,0,8,0" Padding="10,4" />\n'
    )


def generate_plugin(name, base_out, include_view=True, include_parameters=True, behavior=None, atlas_parameters=None,
                    display_property_specs=None, command_specs=None, parameter_max_count=100, workspace_root=None,
                    description=None, library_project=None, icon_path=None, service_names=None):
    name = normalize_plugin_name(name)
    behavior = behavior or (BEHAVIOR_CURRENT_VALUE if include_parameters else BEHAVIOR_BASIC)
    include_parameters = behavior_uses_parameters(behavior)
    if not isinstance(parameter_max_count, int) or parameter_max_count < 1:
        raise ValueError('Maximum parameter count must be a positive integer.')
    validated_atlas_parameters = []
    existing_atlas_parameters = set()
    for identifier in atlas_parameters or []:
        validated_identifier = build_atlas_parameter(identifier, existing_atlas_parameters)
        validated_atlas_parameters.append(validated_identifier)
        existing_atlas_parameters.add(validated_identifier)
    atlas_parameters = validated_atlas_parameters
    display_property_specs = list(display_property_specs or [])
    command_specs = list(command_specs or [])
    validate_display_property_actions(display_property_specs, behavior)
    if atlas_parameters and not include_parameters:
        raise ValueError('ATLAS parameters require a data behavior.')
    if len(atlas_parameters) > parameter_max_count:
        raise ValueError('Maximum parameter count cannot be lower than the number of ATLAS parameters.')
    namespace = name
    workspace_root = os.path.abspath(workspace_root or default_workspace_root())
    icon_path = validate_icon_path(icon_path)
    icon_filename = os.path.basename(icon_path)
    target = os.path.join(base_out, name)
    project_directory = os.path.join(target, name)
    os.makedirs(project_directory, exist_ok=True)
    resources_dir = os.path.join(project_directory, 'Resources')
    os.makedirs(resources_dir, exist_ok=True)
    shutil.copyfile(icon_path, os.path.join(resources_dir, icon_filename))

    project_guid = str(uuid.uuid4()).upper()
    assembly_guid = str(uuid.uuid4()).upper()
    description = description or f'{name} ATLAS display plugin'

    csproj = CS_PROJ_TEMPLATE.format(project_guid=project_guid, icon_filename=icon_filename)
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
        viewmodel_template = VIEWMODEL_TEMPLATE
        view_template = VIEW_XAML_TEMPLATE
    elif behavior in (BEHAVIOR_VISIBLE_RANGE, BEHAVIOR_CURRENT_AND_RANGE):
        viewmodel_template = TIMEBASE_VIEWMODEL_TEMPLATE
        view_template = TIMEBASE_VIEW_XAML_TEMPLATE
    elif behavior == BEHAVIOR_COMPARE_SESSIONS:
        viewmodel_template = COMPARE_VIEWMODEL_TEMPLATE
        view_template = COMPARE_VIEW_XAML_TEMPLATE
    else:
        viewmodel_template = BASIC_VIEWMODEL_TEMPLATE
        view_template = BASIC_VIEW_XAML_TEMPLATE
    atlas_parameter_setup = ''
    display_property_fields = ''
    display_properties = ''
    if include_parameters and atlas_parameters:
        registrations = '\n'.join(
                f'            this.DisplayParameterService.AddParameterContainer("{escape_csharp_string(identifier)}");'
            for identifier in atlas_parameters
        )
        atlas_parameter_setup = (
            '        protected override void OnInitialised()\n'
            '        {\n'
            '            base.OnInitialised();\n'
            f'{registrations}\n'
            '        }\n'
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
    if include_parameters:
        extra_service_names = [n for n in requested_services if n not in ('ISignalBus', 'IDataRequestSignalFactory')]
    else:
        extra_service_names = requested_services
    service_entries = build_service_entries(extra_service_names)
    extra_usings = build_service_usings(service_entries)
    extra_ctor_params = ''
    extra_ctor_assignments = ''
    service_members = ''
    command_properties = '\n'.join(build_command_property(spec) for spec in command_specs)
    command_initializers = ''.join(build_command_initializer(spec) for spec in command_specs)
    command_handlers = '\n'.join(build_command_handler(spec) for spec in command_specs)
    command_buttons = ''.join(build_command_button(spec) for spec in command_specs)
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
            cursor_subscription=CURSOR_SUBSCRIPTION if behavior == BEHAVIOR_CURRENT_AND_RANGE else '',
            cursor_request_method=CURSOR_REQUEST_METHOD if behavior == BEHAVIOR_CURRENT_AND_RANGE else '',
            cursor_result_handler=CURSOR_RESULT_HANDLER if behavior == BEHAVIOR_CURRENT_AND_RANGE else '',
            command_properties=command_properties,
            command_initializers=command_initializers,
            command_handlers=command_handlers,
        ),
    }
    if behavior == BEHAVIOR_CURRENT_VALUE:
        files['ParameterViewModel.cs'] = PARAMETER_VIEWMODEL_TEMPLATE.format(namespace=namespace)
    elif behavior in (BEHAVIOR_VISIBLE_RANGE, BEHAVIOR_CURRENT_AND_RANGE):
        include_current_value = behavior == BEHAVIOR_CURRENT_AND_RANGE
        files['TimebaseSeriesViewModel.cs'] = TIMEBASE_SERIES_VIEWMODEL_TEMPLATE.format(
            namespace=namespace,
            current_value_field=CURRENT_VALUE_FIELD if include_current_value else '',
            current_value_property=CURRENT_VALUE_PROPERTY if include_current_value else '',
            current_value_update_method=CURRENT_VALUE_UPDATE_METHOD if include_current_value else '',
        )
    elif behavior == BEHAVIOR_COMPARE_SESSIONS:
        files['CompareRowViewModel.cs'] = COMPARE_ROW_VIEWMODEL_TEMPLATE.format(namespace=namespace)
        files['CompareSessionValueViewModel.cs'] = COMPARE_SESSION_VALUE_VIEWMODEL_TEMPLATE.format(
            namespace=namespace,
        )
    if include_view:
        files[f'{name}View.xaml'] = view_template.format(
            namespace=namespace,
            view_class=f'{name}View',
            current_value_text=(CURRENT_VALUE_TEXT if behavior == BEHAVIOR_CURRENT_AND_RANGE else ''),
            command_buttons=command_buttons,
        )
        files[f'{name}View.xaml.cs'] = VIEW_CODEBEHIND_TEMPLATE.format(
            namespace=namespace,
            view_class=f'{name}View',
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
        atlas_install_path=r'C:\Program Files\McLaren Applied Technologies\ATLAS 10',
    )
    with open(os.path.join(scripts_dir, 'deploy.py'), 'w', encoding='utf-8', newline='') as stream:
        stream.write(deploy_py)
    
    return target


class PluginGeneratorApp(tk.Tk):
    def __init__(self):
        super().__init__()
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
        tk.Entry(output_frame, textvariable=self.icon_var, width=45).grid(row=2, column=1, sticky='ew', padx=8)
        tk.Button(output_frame, text='Browse', command=self.browse_icon).grid(row=2, column=2, padx=6)
        
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
        tk.Label(
            config_frame,
            text='Choose cursor values, visible-range samples, both, compare sessions, or a basic display.',
            font=('Arial', 8, 'italic'), justify='left', wraplength=600,
        ).pack(anchor='w', pady=(0, 4))
        
        self.add_view_var = tk.BooleanVar(value=True)
        tk.Checkbutton(config_frame, text='Include simple WPF View', variable=self.add_view_var).pack(anchor='w', pady=4)

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

        tree_columns = ('identifier', 'type', 'default', 'action', 'display_name', 'persisted', 'browsable')
        column_headings = {
            'identifier': 'Identifier',
            'type': 'Type',
            'default': 'Default',
            'action': 'When Changed',
            'display_name': 'Display Name',
            'persisted': 'Persisted',
            'browsable': 'Browsable',
        }
        column_widths = {
            'identifier': 110,
            'type': 70,
            'default': 90,
            'action': 130,
            'display_name': 120,
            'persisted': 65,
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
            columns=('name', 'button_label', 'include_button', 'can_execute'),
            show='headings',
            height=4,
        )
        self.command_tree.heading('name', text='Command')
        self.command_tree.heading('button_label', text='Button Label')
        self.command_tree.heading('include_button', text='Add Button')
        self.command_tree.heading('can_execute', text='Enabled Rule')
        self.command_tree.column('name', width=150, anchor='w')
        self.command_tree.column('button_label', width=180, anchor='w')
        self.command_tree.column('include_button', width=80, anchor='w')
        self.command_tree.column('can_execute', width=100, anchor='w')
        self.command_tree.pack(fill=tk.BOTH, expand=True, pady=4)
        self.command_tree.bind('<Double-1>', lambda event: self.edit_selected_command())

        command_button_frame = tk.Frame(command_frame)
        command_button_frame.pack(fill=tk.X, pady=4)
        tk.Button(command_button_frame, text='Add...', command=self.add_command_dialog).pack(side=tk.LEFT, padx=4)
        tk.Button(command_button_frame, text='Edit...', command=self.edit_selected_command).pack(side=tk.LEFT, padx=4)
        tk.Button(command_button_frame, text='Remove', command=self.remove_selected_command).pack(side=tk.LEFT, padx=4)
        
        # === Advanced Settings ===
        advanced_frame = tk.LabelFrame(scrollable_frame, text='Advanced Settings', padx=8, pady=8)
        advanced_frame.pack(fill=tk.X, pady=8)
        
        tk.Label(advanced_frame, text='Maximum parameters:').grid(row=0, column=0, sticky='w', pady=6)
        self.parameter_max_var = tk.StringVar(value='100')
        tk.Spinbox(advanced_frame, from_=1, to=1000, textvariable=self.parameter_max_var, width=10).grid(row=0, column=1, sticky='w', padx=8)
        
        self.open_folder_var = tk.BooleanVar(value=True)
        tk.Checkbutton(advanced_frame, text='Open folder after generation', variable=self.open_folder_var).grid(row=1, column=0, columnspan=2, sticky='w', pady=4)

        self.build_after_generation_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            advanced_frame,
            text='Build and validate after generation',
            variable=self.build_after_generation_var,
        ).grid(row=2, column=0, columnspan=2, sticky='w', pady=4)
        
        # === Action Buttons ===
        button_frame = tk.Frame(scrollable_frame)
        button_frame.pack(fill=tk.X, pady=12)
        
        tk.Button(button_frame, text='Generate Plugin', command=self.generate, 
                 bg='#4CAF50', fg='white', font=('Arial', 10, 'bold'), padx=20, pady=10).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Reset', command=self.reset_form, 
                 bg='#2196F3', fg='white', font=('Arial', 10), padx=20, pady=10).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Clear Saved Paths', command=self.clear_saved_paths,
             bg='#FF9800', fg='white', font=('Arial', 10), padx=20, pady=10).pack(side=tk.LEFT, padx=4)
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
            self.icon_var.set(path)

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
        tk.Checkbutton(dialog, text='Visible in properties window (Browsable)', variable=browsable_var).grid(
            row=len(fields) + 1, column=0, columnspan=2, sticky='w', padx=8, pady=6)
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
                    existing_names=existing_names,
                )
            except ValueError as error:
                messagebox.showerror('Invalid Display Property', str(error), parent=dialog)
                return
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        button_frame = tk.Frame(dialog)
        button_frame.grid(row=len(fields) + 2, column=0, columnspan=2, pady=10)
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
                spec['button_label'],
                'Yes' if spec['include_button'] else 'No',
                'Generated' if spec.get('generate_can_execute', False) else 'Always',
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

        tk.Label(dialog, text='Action Name (required):').grid(row=0, column=0, sticky='w', padx=8, pady=6)
        tk.Entry(dialog, textvariable=name_var, width=35).grid(row=0, column=1, sticky='ew', padx=8, pady=6)
        tk.Label(dialog, text='Button Label:').grid(row=1, column=0, sticky='w', padx=8, pady=6)
        tk.Entry(dialog, textvariable=button_label_var, width=35).grid(row=1, column=1, sticky='ew', padx=8, pady=6)
        tk.Checkbutton(dialog, text='Add button to generated view', variable=include_button_var).grid(
            row=2, column=0, columnspan=2, sticky='w', padx=8, pady=6
        )
        tk.Checkbutton(
            dialog,
            text='Generate an enabled/disabled rule (CanExecute)',
            variable=can_execute_var,
        ).grid(row=3, column=0, columnspan=2, sticky='w', padx=8, pady=6)
        dialog.columnconfigure(1, weight=1)

        result = {}

        def on_ok():
            existing_names = {spec['name'] for spec in self.command_specs if spec['name'] != editing_name}
            try:
                result['spec'] = build_command_spec(
                    name_var.get(),
                    button_label_var.get(),
                    include_button_var.get(),
                    existing_names,
                    can_execute_var.get(),
                )
            except ValueError as error:
                messagebox.showerror('Invalid Command', str(error), parent=dialog)
                return
            dialog.destroy()

        button_frame = tk.Frame(dialog)
        button_frame.grid(row=4, column=0, columnspan=2, pady=10)
        tk.Button(button_frame, text='OK', command=on_ok, width=10).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text='Cancel', command=dialog.destroy, width=10).pack(side=tk.LEFT, padx=4)
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
        dialog.wait_window()
        return result.get('spec')

    def reset_form(self):
        self.name_var.set('')
        self.description_var.set('')
        self.atlas_parameter_text.delete('1.0', tk.END)
        self.display_property_specs = []
        self.refresh_property_tree()
        self.command_specs = []
        self.refresh_command_tree()
        self.icon_var.set('')
        self.parameter_max_var.set('100')
        self.add_view_var.set(True)
        self.behavior_var.set(BEHAVIOR_CURRENT_VALUE)
        for service_var in self.service_vars.values():
            service_var.set(False)
        self.update_behavior_states()
        self.open_folder_var.set(True)
        self.build_after_generation_var.set(True)
        messagebox.showinfo('Reset', 'Form has been reset to default values')

    def update_behavior_states(self):
        # Data behaviors inject these services through DisplayPluginLibrary base classes.
        parameters_enabled = behavior_uses_parameters(self.behavior_var.get())
        for service_name in ('ISignalBus', 'IDataRequestSignalFactory'):
            checkbutton = self.service_checkbuttons[service_name]
            if parameters_enabled:
                self.service_vars[service_name].set(True)
                checkbutton.config(state=tk.DISABLED)
            else:
                checkbutton.config(state=tk.NORMAL)
        if hasattr(self, 'atlas_parameter_text'):
            self.atlas_parameter_text.config(state=tk.NORMAL if parameters_enabled else tk.DISABLED)

    def clear_saved_paths(self):
        if not messagebox.askyesno('Clear Saved Paths', 'Delete the persisted output and library paths?'):
            return
        clear_settings()
        self.out_var.set('')
        self.library_var.set('')
        self.icon_var.set('')
        messagebox.showinfo('Clear Saved Paths', 'Persisted paths were cleared.')

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
            if atlas_parameters and not include_parameters:
                raise ValueError('ATLAS parameters require Current value or Visible range behavior.')
            service_names = [name for name, var in self.service_vars.items() if var.get()]
            os.makedirs(base_out, exist_ok=True)
            target = generate_plugin(
                name,
                base_out,
                include_view=self.add_view_var.get(),
                include_parameters=include_parameters,
                behavior=self.behavior_var.get(),
                atlas_parameters=atlas_parameters,
                display_property_specs=display_property_specs,
                command_specs=command_specs,
                parameter_max_count=parameter_max_count,
                workspace_root=default_workspace_root(),
                description=self.description_var.get().strip() or None,
                library_project=library_project,
                icon_path=icon_path,
                service_names=service_names,
            )
            save_settings({
                'output_folder': base_out,
                'library_project': library_project,
                'icon_path': icon_path,
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
    main()
