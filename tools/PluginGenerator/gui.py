import os
import re
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import shutil
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
  <Target Name="PostBuild" AfterTargets="PostBuildEvent">
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
using MAT.Atlas.Client.Presentation.Plugins;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Windows.Media;
{extra_usings}
namespace {namespace}
{{
    [DisplayPluginSettings(ParametersMaxCount = {parameter_max_count})]
    public sealed class {viewmodel_class} : ParameterSampleDisplayViewModelBase<ParameterViewModel>
    {{
{custom_parameter_fields}
        public {viewmodel_class}(
            ISignalBus signalBus,
            IDataRequestSignalFactory dataRequestSignalFactory,
            ILogger logger{extra_ctor_params}) :
            base(signalBus, dataRequestSignalFactory, logger)
        {{
{extra_ctor_assignments}        }}

{custom_parameter_properties}
    {custom_parameter_setup}
        protected override ParameterViewModel OnCreateParameterViewModel() => new ParameterViewModel();
    }}
}}
'''

BASIC_VIEWMODEL_TEMPLATE = '''{extra_usings}using MAT.Atlas.Client.Presentation.Displays;
using MAT.Atlas.Client.Presentation.Plugins;

namespace {namespace}
{{
    [DisplayPluginSettings(ParametersMaxCount = {parameter_max_count})]
    public sealed class {viewmodel_class} : DisplayPluginViewModel
    {{
{service_members}    }}
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
        <TextBlock Text="{view_class}"
                   VerticalAlignment="Center"
                   HorizontalAlignment="Center"
                   Foreground="White"
                   FontSize="20" />
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
        name += 'Plugin'
    return name


def to_camel_case(identifier):
    return identifier[:1].lower() + identifier[1:] if identifier else identifier


def build_parameter_spec(name, display_name='', category='', description='', order='', persisted=False, browsable=True, existing_names=None):
    name = (name or '').strip()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError(f'Parameter identifier "{name}" must be a valid C# identifier.')
    if existing_names and name in existing_names:
        raise ValueError(f'A parameter named "{name}" already exists.')
    display_name = (display_name or '').strip()
    category = (category or '').strip()
    description = (description or '').strip()
    order_text = str(order).strip()
    if not order_text:
        order_value = None
    elif re.fullmatch(r'-?\d+', order_text):
        order_value = int(order_text)
    else:
        raise ValueError(f'Parameter "{name}" order must be an integer.')
    return {
        'name': name,
        'display_name': display_name,
        'category': category,
        'description': description,
        'order': order_value,
        'persisted': bool(persisted),
        'browsable': bool(browsable),
    }


def escape_csharp_string(value):
    return value.replace('\\', '\\\\').replace('"', '\\"')


def build_parameter_field(spec):
    field = '_' + to_camel_case(spec['name'])
    return f'        private string {field};'


def build_parameter_property(spec):
    field = '_' + to_camel_case(spec['name'])
    default_value = escape_csharp_string(spec['name'])
    if spec['persisted']:
        accessor = (
            f'            get => this.{field} = this.ReadProperty("{default_value}");\n'
            '            set\n'
            '            {\n'
            f'                if (this.SetProperty(ref this.{field}, value))\n'
            '                {\n'
            '                    this.SaveProperty(value);\n'
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
        f'        public string {spec["name"]}\n'
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


def build_basic_service_members(viewmodel_class, entries):
    if not entries:
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
        '        }\n'
    )


def validate_icon_path(icon_path):
    icon_path = os.path.abspath(icon_path or '')
    if not os.path.isfile(icon_path):
        raise FileNotFoundError('Select a valid PNG icon before generating the plugin.')
    if os.path.splitext(icon_path)[1].lower() != '.png':
        raise ValueError('The plugin icon must be a PNG file.')
    return icon_path


def generate_plugin(name, base_out, include_view=True, include_parameters=True, parameter_specs=None, parameter_max_count=100, workspace_root=None, description=None, library_project=None, icon_path=None, service_names=None):
    name = normalize_plugin_name(name)
    if not isinstance(parameter_max_count, int) or parameter_max_count < 1:
        raise ValueError('Maximum parameter count must be a positive integer.')
    parameter_specs = list(parameter_specs or [])
    if len(parameter_specs) > parameter_max_count:
        raise ValueError('Maximum parameter count cannot be lower than the number of custom parameters.')
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

    viewmodel_template = VIEWMODEL_TEMPLATE if include_parameters else BASIC_VIEWMODEL_TEMPLATE
    view_template = VIEW_XAML_TEMPLATE if include_parameters else BASIC_VIEW_XAML_TEMPLATE
    parameter_setup = ''
    custom_parameter_fields = ''
    custom_parameter_properties = ''
    if include_parameters and parameter_specs:
        registrations = '\n'.join(
                f'            this.DisplayParameterService.AddParameterContainer("{escape_csharp_string(spec["name"])}");'
            for spec in parameter_specs
        )
        parameter_setup = (
            '        protected override void OnInitialised()\n'
            '        {\n'
            '            base.OnInitialised();\n'
            f'{registrations}\n'
            '        }\n'
        )
        custom_parameter_fields = '\n'.join(build_parameter_field(spec) for spec in parameter_specs)
        custom_parameter_properties = '\n'.join(build_parameter_property(spec) for spec in parameter_specs)

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
    if include_parameters:
        extra_service_fields = build_service_fields(service_entries)
        custom_parameter_fields = '\n'.join(filter(None, [custom_parameter_fields, extra_service_fields]))
        extra_ctor_params = ''.join(f',\n            {entry["interface"]} {entry["param"]}' for entry in service_entries)
        extra_ctor_assignments = ''.join(f'            this.{entry["param"]} = {entry["param"]};\n' for entry in service_entries)
    else:
        service_members = build_basic_service_members(f'{name}ViewModel', service_entries)

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
            custom_parameter_setup=parameter_setup,
            custom_parameter_fields=custom_parameter_fields,
            custom_parameter_properties=custom_parameter_properties,
            extra_usings=extra_usings,
            extra_ctor_params=extra_ctor_params,
            extra_ctor_assignments=extra_ctor_assignments,
            service_members=service_members,
            parameter_max_count=parameter_max_count,
        ),
    }
    if include_parameters:
        files['ParameterViewModel.cs'] = PARAMETER_VIEWMODEL_TEMPLATE.format(namespace=namespace)
    if include_view:
        files[f'{name}View.xaml'] = view_template.format(
            namespace=namespace,
            view_class=f'{name}View',
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
        
        # === View & Parameter Configuration ===
        config_frame = tk.LabelFrame(scrollable_frame, text='View & Parameter Configuration', padx=8, pady=8)
        config_frame.pack(fill=tk.X, pady=8)
        
        self.add_view_var = tk.BooleanVar(value=True)
        tk.Checkbutton(config_frame, text='Include simple WPF View', variable=self.add_view_var).pack(anchor='w', pady=4)
        
        self.add_parameters_var = tk.BooleanVar(value=True)
        tk.Checkbutton(config_frame, text='Include dynamic parameter support (uses ParameterSampleDisplayViewModelBase)', 
                       variable=self.add_parameters_var, command=self.update_service_checkbox_states).pack(anchor='w', pady=4)

        # === Injected Services ===
        services_frame = tk.LabelFrame(scrollable_frame, text='Injected Services', padx=8, pady=8)
        services_frame.pack(fill=tk.X, pady=8)

        tk.Label(
            services_frame,
            text='ISignalBus and IDataRequestSignalFactory are always injected when dynamic parameter support is enabled.',
            font=('Arial', 8, 'italic'), justify='left', wraplength=600,
        ).pack(anchor='w', pady=(0, 4))

        self.service_vars = {service_name: tk.BooleanVar(value=False) for service_name in SERVICE_DEFINITIONS}
        self.service_checkbuttons = {}
        for service_name in SERVICE_DEFINITIONS:
            checkbutton = tk.Checkbutton(services_frame, text=service_name, variable=self.service_vars[service_name])
            checkbutton.pack(anchor='w')
            self.service_checkbuttons[service_name] = checkbutton
        self.update_service_checkbox_states()
        
        # === Custom Parameters ===
        param_frame = tk.LabelFrame(scrollable_frame, text='Custom Parameters', padx=8, pady=8)
        param_frame.pack(fill=tk.BOTH, expand=True, pady=8)

        self.parameter_specs = []

        tree_columns = ('identifier', 'display_name', 'category', 'order', 'persisted', 'browsable')
        column_headings = {
            'identifier': 'Identifier',
            'display_name': 'Display Name',
            'category': 'Category',
            'order': 'Order',
            'persisted': 'Persisted',
            'browsable': 'Browsable',
        }
        column_widths = {'identifier': 120, 'display_name': 140, 'category': 100, 'order': 50, 'persisted': 70, 'browsable': 70}
        self.parameter_tree = ttk.Treeview(param_frame, columns=tree_columns, show='headings', height=6)
        for column in tree_columns:
            self.parameter_tree.heading(column, text=column_headings[column])
            self.parameter_tree.column(column, width=column_widths[column], anchor='w')
        self.parameter_tree.pack(fill=tk.BOTH, expand=True, pady=4)
        self.parameter_tree.bind('<Double-1>', lambda event: self.edit_selected_parameter())

        parameter_button_frame = tk.Frame(param_frame)
        parameter_button_frame.pack(fill=tk.X, pady=4)
        tk.Button(parameter_button_frame, text='Add...', command=self.add_parameter_dialog).pack(side=tk.LEFT, padx=4)
        tk.Button(parameter_button_frame, text='Edit...', command=self.edit_selected_parameter).pack(side=tk.LEFT, padx=4)
        tk.Button(parameter_button_frame, text='Remove', command=self.remove_selected_parameter).pack(side=tk.LEFT, padx=4)
        
        # === Advanced Settings ===
        advanced_frame = tk.LabelFrame(scrollable_frame, text='Advanced Settings', padx=8, pady=8)
        advanced_frame.pack(fill=tk.X, pady=8)
        
        tk.Label(advanced_frame, text='Maximum parameters:').grid(row=0, column=0, sticky='w', pady=6)
        self.parameter_max_var = tk.StringVar(value='100')
        tk.Spinbox(advanced_frame, from_=1, to=1000, textvariable=self.parameter_max_var, width=10).grid(row=0, column=1, sticky='w', padx=8)
        
        self.open_folder_var = tk.BooleanVar(value=True)
        tk.Checkbutton(advanced_frame, text='Open folder after generation', variable=self.open_folder_var).grid(row=1, column=0, columnspan=2, sticky='w', pady=4)
        
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

    def refresh_parameter_tree(self):
        self.parameter_tree.delete(*self.parameter_tree.get_children())
        for spec in self.parameter_specs:
            self.parameter_tree.insert('', tk.END, values=(
                spec['name'],
                spec['display_name'],
                spec['category'],
                '' if spec['order'] is None else spec['order'],
                'Yes' if spec['persisted'] else 'No',
                'Yes' if spec['browsable'] else 'No',
            ))

    def add_parameter_dialog(self):
        spec = self._parameter_dialog('Add Parameter')
        if spec:
            self.parameter_specs.append(spec)
            self.refresh_parameter_tree()

    def edit_selected_parameter(self):
        selection = self.parameter_tree.selection()
        if not selection:
            messagebox.showinfo('Edit Parameter', 'Select a parameter to edit.')
            return
        index = self.parameter_tree.index(selection[0])
        current = self.parameter_specs[index]
        spec = self._parameter_dialog('Edit Parameter', initial=current, editing_name=current['name'])
        if spec:
            self.parameter_specs[index] = spec
            self.refresh_parameter_tree()

    def remove_selected_parameter(self):
        selection = self.parameter_tree.selection()
        if not selection:
            messagebox.showinfo('Remove Parameter', 'Select a parameter to remove.')
            return
        index = self.parameter_tree.index(selection[0])
        del self.parameter_specs[index]
        self.refresh_parameter_tree()

    def _parameter_dialog(self, title, initial=None, editing_name=None):
        initial = initial or {}
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(True, True)
        dialog.minsize(320, 260)

        identifier_var = tk.StringVar(value=initial.get('name', ''))
        display_name_var = tk.StringVar(value=initial.get('display_name', ''))
        category_var = tk.StringVar(value=initial.get('category', ''))
        description_var = tk.StringVar(value=initial.get('description', ''))
        order_var = tk.StringVar(value='' if initial.get('order') is None else str(initial['order']))
        persisted_var = tk.BooleanVar(value=initial.get('persisted', False))
        browsable_var = tk.BooleanVar(value=initial.get('browsable', True))

        fields = [
            ('Identifier (required):', identifier_var),
            ('Display Name:', display_name_var),
            ('Category:', category_var),
            ('Description:', description_var),
            ('Order:', order_var),
        ]
        for row, (label_text, var) in enumerate(fields):
            tk.Label(dialog, text=label_text).grid(row=row, column=0, sticky='w', padx=8, pady=6)
            tk.Entry(dialog, textvariable=var, width=35).grid(row=row, column=1, sticky='ew', padx=8, pady=6)
        tk.Checkbutton(dialog, text='Persist to workbook', variable=persisted_var).grid(
            row=len(fields), column=0, columnspan=2, sticky='w', padx=8, pady=6)
        tk.Checkbutton(dialog, text='Visible in properties window (Browsable)', variable=browsable_var).grid(
            row=len(fields) + 1, column=0, columnspan=2, sticky='w', padx=8, pady=6)
        dialog.columnconfigure(1, weight=1)

        result = {}

        def on_ok():
            existing_names = {spec['name'] for spec in self.parameter_specs if spec['name'] != editing_name}
            try:
                result['spec'] = build_parameter_spec(
                    identifier_var.get(),
                    display_name_var.get(),
                    category_var.get(),
                    description_var.get(),
                    order_var.get(),
                    persisted_var.get(),
                    browsable_var.get(),
                    existing_names=existing_names,
                )
            except ValueError as error:
                messagebox.showerror('Invalid Parameter', str(error), parent=dialog)
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

    def reset_form(self):
        self.name_var.set('')
        self.description_var.set('')
        self.parameter_specs = []
        self.refresh_parameter_tree()
        self.icon_var.set('')
        self.parameter_max_var.set('100')
        self.add_view_var.set(True)
        self.add_parameters_var.set(True)
        for service_var in self.service_vars.values():
            service_var.set(False)
        self.update_service_checkbox_states()
        self.open_folder_var.set(True)
        messagebox.showinfo('Reset', 'Form has been reset to default values')

    def update_service_checkbox_states(self):
        # ISignalBus/IDataRequestSignalFactory are always injected by the parameter base class.
        parameters_enabled = self.add_parameters_var.get()
        for service_name in ('ISignalBus', 'IDataRequestSignalFactory'):
            checkbutton = self.service_checkbuttons[service_name]
            if parameters_enabled:
                self.service_vars[service_name].set(True)
                checkbutton.config(state=tk.DISABLED)
            else:
                checkbutton.config(state=tk.NORMAL)

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
            if not base_out:
                raise ValueError('Select an output folder before generating.')
            if self.add_parameters_var.get() and not library_project:
                raise ValueError('Select DisplayPluginLibrary.csproj before generating a parameter plugin.')
            if not icon_path:
                raise ValueError('Select a PNG icon before generating the plugin.')
            parameter_specs = list(self.parameter_specs)
            parameter_max_count = int(self.parameter_max_var.get())
            if parameter_specs and not self.add_parameters_var.get():
                raise ValueError('Enable dynamic parameter support to generate custom parameters.')
            service_names = [name for name, var in self.service_vars.items() if var.get()]
            os.makedirs(base_out, exist_ok=True)
            target = generate_plugin(
                name,
                base_out,
                include_view=self.add_view_var.get(),
                include_parameters=self.add_parameters_var.get(),
                parameter_specs=parameter_specs,
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

            # Show success message
            generated_name = os.path.basename(target)
            success_msg = f'Plugin "{generated_name}" created successfully at:\n{target}'
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
