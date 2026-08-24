import os
import re
import json
import tkinter as tk
from tkinter import filedialog, messagebox
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

namespace {namespace}
{{
    [DisplayPluginSettings(ParametersMaxCount = {parameter_max_count})]
    public sealed class {viewmodel_class} : ParameterSampleDisplayViewModelBase<ParameterViewModel>
    {{
        public {viewmodel_class}(
            ISignalBus signalBus,
            IDataRequestSignalFactory dataRequestSignalFactory,
            ILogger logger) :
            base(signalBus, dataRequestSignalFactory, logger)
        {{
        }}

    {custom_parameter_setup}
        protected override ParameterViewModel OnCreateParameterViewModel() => new ParameterViewModel();
    }}
}}
'''

BASIC_VIEWMODEL_TEMPLATE = '''using MAT.Atlas.Client.Presentation.Displays;
using MAT.Atlas.Client.Presentation.Plugins;

namespace {namespace}
{{
    [DisplayPluginSettings(ParametersMaxCount = {parameter_max_count})]
    public sealed class {viewmodel_class} : DisplayPluginViewModel
    {{
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


def parse_parameter_names(value):
    names = [line.strip() for line in value.splitlines() if line.strip()]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f'Duplicate custom parameters: {", ".join(duplicates)}')
    return names


def escape_csharp_string(value):
    return value.replace('\\', '\\\\').replace('"', '\\"')


def validate_icon_path(icon_path):
    icon_path = os.path.abspath(icon_path or '')
    if not os.path.isfile(icon_path):
        raise FileNotFoundError('Select a valid PNG icon before generating the plugin.')
    if os.path.splitext(icon_path)[1].lower() != '.png':
        raise ValueError('The plugin icon must be a PNG file.')
    return icon_path


def generate_plugin(name, base_out, include_view=True, include_parameters=True, parameter_names=None, parameter_max_count=100, workspace_root=None, description=None, library_project=None, icon_path=None):
    name = normalize_plugin_name(name)
    if not isinstance(parameter_max_count, int) or parameter_max_count < 1:
        raise ValueError('Maximum parameter count must be a positive integer.')
    parameter_names = list(parameter_names or [])
    if len(parameter_names) > parameter_max_count:
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
    if include_parameters and parameter_names:
        registrations = '\n'.join(
                f'            this.DisplayParameterService.AddParameterContainer("{escape_csharp_string(parameter_name)}");'
            for parameter_name in parameter_names
        )
        parameter_setup = (
            '        protected override void OnInitialised()\n'
            '        {\n'
            '            base.OnInitialised();\n'
            f'{registrations}\n'
            '        }\n'
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
            custom_parameter_setup=parameter_setup,
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
        self.geometry('560x800')
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
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
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
                       variable=self.add_parameters_var).pack(anchor='w', pady=4)
        
        # === Custom Parameters ===
        param_frame = tk.LabelFrame(scrollable_frame, text='Custom Parameters', padx=8, pady=8)
        param_frame.pack(fill=tk.BOTH, expand=True, pady=8)
        
        tk.Label(param_frame, text='Enter one parameter identifier per line (optional):', font=('Arial', 9)).pack(anchor='w', pady=4)
        self.parameter_text = tk.Text(param_frame, width=50, height=5)
        self.parameter_text.pack(fill=tk.BOTH, expand=True, pady=4)
        scrollbar_param = tk.Scrollbar(param_frame, command=self.parameter_text.yview)
        scrollbar_param.pack(side=tk.RIGHT, fill=tk.Y)
        self.parameter_text.config(yscrollcommand=scrollbar_param.set)
        
        tk.Label(param_frame, text='Example: "EngineSpeed", "BrakePressure", "Temperature"', 
                font=('Arial', 8, 'italic')).pack(anchor='w')
        
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

    def reset_form(self):
        self.name_var.set('')
        self.description_var.set('')
        self.parameter_text.delete('1.0', tk.END)
        self.icon_var.set('')
        self.parameter_max_var.set('100')
        self.add_view_var.set(True)
        self.add_parameters_var.set(True)
        self.open_folder_var.set(True)
        messagebox.showinfo('Reset', 'Form has been reset to default values')

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
            parameter_names = parse_parameter_names(self.parameter_text.get('1.0', 'end'))
            parameter_max_count = int(self.parameter_max_var.get())
            if parameter_names and not self.add_parameters_var.get():
                raise ValueError('Enable dynamic parameter support to generate custom parameters.')
            os.makedirs(base_out, exist_ok=True)
            target = generate_plugin(
                name,
                base_out,
                include_view=self.add_view_var.get(),
                include_parameters=self.add_parameters_var.get(),
                parameter_names=parameter_names,
                parameter_max_count=parameter_max_count,
                workspace_root=default_workspace_root(),
                description=self.description_var.get().strip() or None,
                library_project=library_project,
                icon_path=icon_path,
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
