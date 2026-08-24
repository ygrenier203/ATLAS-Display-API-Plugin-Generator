import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from tools.PluginGenerator.gui import (
    BEHAVIOR_BASIC,
    BEHAVIOR_COMPARE_SESSIONS,
    BEHAVIOR_CURRENT_AND_RANGE,
    BEHAVIOR_CURRENT_VALUE,
    BEHAVIOR_VISIBLE_RANGE,
    behavior_uses_parameters,
    build_generated_plugin,
    build_atlas_parameter,
    build_command_button,
    build_command_handler,
    build_command_initializer,
    build_command_spec,
    build_status_state,
    build_lifecycle_hooks,
    build_session_notification_hooks,
    build_display_property,
    build_display_property_field,
    build_display_property_spec,
    generate_plugin,
)
from tools.PluginGenerator.generator import run


ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PROJECT = ROOT / 'DisplayPluginLibrary' / 'DisplayPluginLibrary.csproj'
ICON = ROOT / 'icon.png'


class ParameterAndPropertyTests(unittest.TestCase):
    def test_current_value_behavior_uses_parameter_support(self):
        self.assertTrue(behavior_uses_parameters(BEHAVIOR_CURRENT_VALUE))

    def test_basic_behavior_does_not_use_parameter_support(self):
        self.assertFalse(behavior_uses_parameters(BEHAVIOR_BASIC))

    def test_visible_range_behavior_uses_parameter_support(self):
        self.assertTrue(behavior_uses_parameters(BEHAVIOR_VISIBLE_RANGE))

    def test_combined_behavior_uses_parameter_support(self):
        self.assertTrue(behavior_uses_parameters(BEHAVIOR_CURRENT_AND_RANGE))

    def test_compare_behavior_uses_parameter_support(self):
        self.assertTrue(behavior_uses_parameters(BEHAVIOR_COMPARE_SESSIONS))

    def test_atlas_identifier_accepts_colons(self):
        self.assertEqual('vCar:Chassis', build_atlas_parameter(' vCar:Chassis '))

    def test_atlas_identifier_rejects_duplicates(self):
        with self.assertRaisesRegex(ValueError, 'already exists'):
            build_atlas_parameter('vCar:Chassis', {'vCar:Chassis'})

    def test_display_property_requires_csharp_identifier(self):
        with self.assertRaisesRegex(ValueError, 'valid C# identifier'):
            build_display_property_spec('vCar:Chassis')

    def test_display_property_preserves_pascal_case(self):
        spec = build_display_property_spec(
            'FontSize',
            persisted=True,
            property_type='int',
            default_value='20',
        )
        source = build_display_property(spec)

        self.assertIn('public int FontSize', source)
        self.assertNotIn('Fontsize', source)
        self.assertIn('ReadProperty(20)', source)
        self.assertIn('SaveProperty(value)', source)

    def test_display_property_types_generate_csharp_literals(self):
        cases = [
            ('Title', 'string', 'Ready', 'private string _title = "Ready";'),
            ('Count', 'int', '12', 'private int _count = 12;'),
            ('Scale', 'double', '1.5', 'private double _scale = 1.5d;'),
            ('Enabled', 'bool', 'true', 'private bool _enabled = true;'),
        ]
        for name, property_type, default_value, expected in cases:
            with self.subTest(property_type=property_type):
                spec = build_display_property_spec(
                    name,
                    property_type=property_type,
                    default_value=default_value,
                )
                self.assertIn(expected, build_display_property_field(spec))
                self.assertIn(f'public {property_type} {name}', build_display_property(spec))

    def test_invalid_typed_defaults_are_rejected(self):
        invalid_defaults = [
            ('int', '1.5'),
            ('double', 'not a number'),
            ('double', 'NaN'),
            ('bool', 'sometimes'),
        ]
        for property_type, default_value in invalid_defaults:
            with self.subTest(property_type=property_type, default=default_value):
                with self.assertRaises(ValueError):
                    build_display_property_spec(
                        'Setting',
                        property_type=property_type,
                        default_value=default_value,
                    )

    def test_property_change_action_generates_data_refresh(self):
        spec = build_display_property_spec(
            'SampleLimit',
            property_type='int',
            default_value='100',
            persisted=True,
            change_action='refresh-all',
        )
        source = build_display_property(spec)

        self.assertIn('this.SaveProperty(value);', source)
        self.assertIn('this.MakeDataRequests(true, true);', source)

    def test_command_name_and_default_label_are_normalized(self):
        spec = build_command_spec('ExportDataCommand')

        self.assertEqual('ExportData', spec['name'])
        self.assertEqual('Export Data', spec['button_label'])

    def test_command_button_escapes_xaml_text(self):
        spec = build_command_spec('Export', 'Save & Close')

        self.assertIn('Content="Save &amp; Close"', build_command_button(spec))

    def test_command_can_generate_enabled_rule(self):
        spec = build_command_spec('Export', generate_can_execute=True)

        self.assertIn(
            'new DelegateCommand(this.OnExport, this.CanExport)',
            build_command_initializer(spec),
        )
        handler = build_command_handler(spec)
        self.assertIn('private bool CanExport()', handler)
        self.assertIn('return true;', handler)

    def test_status_state_uses_property_notifications(self):
        fields, properties = build_status_state()

        self.assertIn('private bool isBusy;', fields)
        self.assertIn('public bool IsBusy', properties)
        self.assertIn('public string StatusMessage', properties)
        self.assertIn('public string ErrorMessage', properties)
        self.assertEqual(3, properties.count('this.SetProperty('))

    def test_lifecycle_hooks_include_base_calls_and_parameter_setup(self):
        source = build_lifecycle_hooks(['vCar:Chassis'], True)

        self.assertEqual(1, source.count('protected override void OnInitialised()'))
        self.assertIn('base.OnInitialised();', source)
        self.assertIn('AddParameterContainer("vCar:Chassis")', source)
        self.assertIn('OnActiveDisplayPageChanged(bool isActive)', source)
        self.assertIn('OnCanRenderDisplayChanged(bool canRender)', source)
        self.assertIn('OnDisposeManagedResources()', source)

    def test_session_notification_hooks_preserve_base_behavior(self):
        source = build_session_notification_hooks()

        self.assertIn('OnCompositeSessionLoaded(CompositeSessionEventArgs args)', source)
        self.assertIn('base.OnCompositeSessionLoaded(args);', source)
        self.assertIn('OnCompositeSessionUnLoaded(CompositeSessionUnloadedEventArgs args)', source)
        self.assertIn('base.OnCompositeSessionUnLoaded(args);', source)
        self.assertIn('base.OnCompositeSessionContainerChanged();', source)


class GenerationTests(unittest.TestCase):
    def generate(self, **options):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        return Path(generate_plugin(
            'SeparationPlugin',
            temporary_directory.name,
            icon_path=str(ICON),
            **options,
        ))

    @patch('tools.PluginGenerator.gui.save_settings')
    @patch('tools.PluginGenerator.gui.generate_plugin')
    def test_cli_commands_are_forwarded_to_generation(self, generate, save_settings):
        generate.return_value = Path('GeneratedPlugin')

        run([
            'SeparationPlugin',
            '--behavior', 'basic',
            '--output', str(ROOT),
            '--icon', str(ICON),
            '--command', 'RefreshData',
            '--command', 'Export',
        ])

        command_specs = generate.call_args.kwargs['command_specs']
        self.assertEqual(['RefreshData', 'Export'], [spec['name'] for spec in command_specs])
        self.assertEqual(['Refresh Data', 'Export'], [spec['button_label'] for spec in command_specs])
        self.assertTrue(all(spec['include_button'] for spec in command_specs))
        save_settings.assert_called_once()

    def test_atlas_parameter_is_registered_exactly(self):
        target = self.generate(
            include_parameters=True,
            library_project=str(LIBRARY_PROJECT),
            atlas_parameters=['vCar:Chassis'],
        )
        viewmodel = (
            target / 'SeparationPlugin' / 'SeparationPluginViewModel.cs'
        ).read_text(encoding='utf-8')

        self.assertIn('AddParameterContainer("vCar:Chassis")', viewmodel)
        self.assertNotIn('public string Vcar', viewmodel)

    def test_basic_plugin_can_generate_status_state(self):
        target = self.generate(include_parameters=False, include_status_state=True)
        viewmodel = (target / 'SeparationPlugin' / 'SeparationPluginViewModel.cs').read_text(encoding='utf-8')

        self.assertIn('public bool IsBusy', viewmodel)
        self.assertIn('public string StatusMessage', viewmodel)
        self.assertIn('public string ErrorMessage', viewmodel)

    def test_basic_plugin_can_generate_lifecycle_hooks(self):
        target = self.generate(include_parameters=False, include_lifecycle_hooks=True)
        viewmodel = (target / 'SeparationPlugin' / 'SeparationPluginViewModel.cs').read_text(encoding='utf-8')

        self.assertIn('protected override void OnInitialised()', viewmodel)
        self.assertIn('public override void OnActiveDisplayPageChanged(bool isActive)', viewmodel)
        self.assertIn('protected override void OnDisposeManagedResources()', viewmodel)

    def test_basic_plugin_can_generate_session_notifications(self):
        target = self.generate(include_parameters=False, include_session_notifications=True)
        viewmodel = (target / 'SeparationPlugin' / 'SeparationPluginViewModel.cs').read_text(encoding='utf-8')

        self.assertIn('using MAT.Atlas.Client.Platform.Sessions;', viewmodel)
        self.assertIn('public override void OnCompositeSessionLoaded', viewmodel)
        self.assertIn('public override void OnCompositeSessionUnLoaded', viewmodel)
        self.assertIn('public override void OnCompositeSessionContainerChanged', viewmodel)

    def test_basic_plugin_can_generate_item_collection_and_view(self):
        target = self.generate(include_parameters=False, include_item_collection=True)
        project = target / 'SeparationPlugin'
        viewmodel = (project / 'SeparationPluginViewModel.cs').read_text(encoding='utf-8')
        item_viewmodel = (project / 'ItemViewModel.cs').read_text(encoding='utf-8')
        view_path = project / 'SeparationPluginView.xaml'
        view = view_path.read_text(encoding='utf-8')

        self.assertIn('ObservableCollection<ItemViewModel> Items', viewmodel)
        self.assertIn('public sealed class ItemViewModel : BindableBase', item_viewmodel)
        self.assertIn('ItemsSource="{Binding Items}"', view)
        self.assertIn('Text="{Binding Name}"', view)
        ET.parse(view_path)

    def test_item_collection_rejects_data_behavior(self):
        with self.assertRaisesRegex(ValueError, 'only available for basic displays'):
            self.generate(
                behavior=BEHAVIOR_CURRENT_VALUE,
                library_project=str(LIBRARY_PROJECT),
                include_item_collection=True,
            )
    def test_generated_project_can_disable_deployment_during_validation(self):
        target = self.generate(include_parameters=False)
        project = (
            target / 'SeparationPlugin' / 'SeparationPlugin.csproj'
        ).read_text(encoding='utf-8')

        self.assertIn('<DeployAtlasPlugin Condition=', project)
        self.assertIn("Condition=\"'$(DeployAtlasPlugin)' == 'true'\"", project)

    def test_display_property_does_not_register_atlas_parameter(self):
        spec = build_display_property_spec('FontSize', persisted=True)
        target = self.generate(
            include_parameters=False,
            display_property_specs=[spec],
        )
        viewmodel = (
            target / 'SeparationPlugin' / 'SeparationPluginViewModel.cs'
        ).read_text(encoding='utf-8')

        self.assertIn('public string FontSize', viewmodel)
        self.assertNotIn('AddParameterContainer', viewmodel)

    def test_atlas_parameters_require_data_behavior(self):
        with self.assertRaisesRegex(ValueError, 'data behavior'):
            self.generate(
                include_parameters=False,
                atlas_parameters=['vCar:Chassis'],
            )

    def test_visible_range_generates_safe_timebase_workflow(self):
        target = self.generate(
            behavior=BEHAVIOR_VISIBLE_RANGE,
            library_project=str(LIBRARY_PROJECT),
            atlas_parameters=['vCar:Chassis'],
        )
        project = target / 'SeparationPlugin'
        viewmodel = (project / 'SeparationPluginViewModel.cs').read_text(encoding='utf-8')
        series = (project / 'TimebaseSeriesViewModel.cs').read_text(encoding='utf-8')
        view = (project / 'SeparationPluginView.xaml').read_text(encoding='utf-8')

        self.assertIn('TemplateDisplayViewModelBase', viewmodel)
        self.assertIn('OnMakeTimebaseDataRequestsAsync', viewmodel)
        self.assertIn('CreateDataRequestSignal', viewmodel)
        self.assertIn('signal.SourceId == this.ScopeIdentity.Guid', viewmodel)
        self.assertIn('parameterValues.Lock()', viewmodel)
        self.assertIn('parameterValues.Unlock()', viewmodel)
        self.assertIn('ExecuteOnUiAsync', viewmodel)
        self.assertIn('IReadOnlyList<long> Timestamps', series)
        self.assertIn('IReadOnlyList<double> Values', series)
        self.assertIn('ItemsSource="{Binding Series}"', view)
        self.assertFalse((project / 'ParameterViewModel.cs').exists())

    def test_combined_behavior_generates_cursor_and_timebase_workflows(self):
        target = self.generate(
            behavior=BEHAVIOR_CURRENT_AND_RANGE,
            library_project=str(LIBRARY_PROJECT),
            atlas_parameters=['vCar:Chassis'],
        )
        project = target / 'SeparationPlugin'
        viewmodel = (project / 'SeparationPluginViewModel.cs').read_text(encoding='utf-8')
        series = (project / 'TimebaseSeriesViewModel.cs').read_text(encoding='utf-8')
        view = (project / 'SeparationPluginView.xaml').read_text(encoding='utf-8')

        self.assertIn('OnMakeCursorDataRequestsAsync', viewmodel)
        self.assertIn('OnMakeTimebaseDataRequestsAsync', viewmodel)
        self.assertIn('Subscribe<SampleResultSignal>', viewmodel)
        self.assertIn('Subscribe<DataResultSignal>', viewmodel)
        self.assertIn('CreateSampleRequestSignal', viewmodel)
        self.assertIn('CreateDataRequestSignal', viewmodel)
        self.assertIn('UpdateCurrentValue', series)
        self.assertIn('public double CurrentValue', series)
        self.assertIn('CurrentValue', view)

    def test_compare_behavior_generates_composite_session_workflow(self):
        target = self.generate(
            behavior=BEHAVIOR_COMPARE_SESSIONS,
            library_project=str(LIBRARY_PROJECT),
            atlas_parameters=['vCar:Chassis'],
        )
        project = target / 'SeparationPlugin'
        viewmodel = (project / 'SeparationPluginViewModel.cs').read_text(encoding='utf-8')
        row = (project / 'CompareRowViewModel.cs').read_text(encoding='utf-8')
        value = (project / 'CompareSessionValueViewModel.cs').read_text(encoding='utf-8')
        view = (project / 'SeparationPluginView.xaml').read_text(encoding='utf-8')

        self.assertIn('Subscribe<CompositeSampleResultSignal>', viewmodel)
        self.assertIn('CreateCompositeSampleRequestSignal', viewmodel)
        self.assertIn('DisplayParameterService.ParameterContainers', viewmodel)
        self.assertIn('parameterValues.Lock()', viewmodel)
        self.assertIn('parameterValues.Unlock()', viewmodel)
        self.assertIn('ExecuteOnUiAsync', viewmodel)
        self.assertIn('ObservableCollection<CompareSessionValueViewModel>', row)
        self.assertIn('CompositeSessionKey SessionKey', value)
        self.assertIn('ItemsSource="{Binding Rows}"', view)
        self.assertIn('ItemsSource="{Binding SessionValues}"', view)

    def test_property_refresh_action_must_match_behavior(self):
        spec = build_display_property_spec(
            'RefreshSetting',
            change_action='refresh-visible',
        )
        with self.assertRaisesRegex(ValueError, 'cannot use'):
            self.generate(
                behavior=BEHAVIOR_CURRENT_VALUE,
                library_project=str(LIBRARY_PROJECT),
                display_property_specs=[spec],
            )

    def test_combined_behavior_accepts_refresh_all_action(self):
        spec = build_display_property_spec(
            'RefreshSetting',
            change_action='refresh-all',
        )
        target = self.generate(
            behavior=BEHAVIOR_CURRENT_AND_RANGE,
            library_project=str(LIBRARY_PROJECT),
            display_property_specs=[spec],
        )
        viewmodel = (
            target / 'SeparationPlugin' / 'SeparationPluginViewModel.cs'
        ).read_text(encoding='utf-8')

        self.assertIn('this.MakeDataRequests(true, true);', viewmodel)

    @patch('tools.PluginGenerator.gui.subprocess.run')
    def test_build_validation_uses_dotnet_without_deploying(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = 'Build succeeded.'
        run.return_value.stderr = ''
        target = self.generate(include_parameters=False)

        output = build_generated_plugin(target, build_tool=('dotnet', 'dotnet.exe'))

        self.assertEqual('Build succeeded.', output)
        command = run.call_args.args[0]
        self.assertEqual(['dotnet.exe', 'build'], command[:2])
        self.assertIn('-p:Platform=x64', command)
        self.assertIn('-p:DeployAtlasPlugin=false', command)

    @patch('tools.PluginGenerator.gui.subprocess.run')
    def test_build_validation_reports_compiler_output(self, run):
        run.return_value.returncode = 1
        run.return_value.stdout = 'Example.cs(10,5): error CS1002: ; expected'
        run.return_value.stderr = ''
        target = self.generate(include_parameters=False)

        with self.assertRaisesRegex(RuntimeError, 'CS1002'):
            build_generated_plugin(target, build_tool=('dotnet', 'dotnet.exe'))

    def test_basic_plugin_generates_command_handler_and_button(self):
        command = build_command_spec('ClearLog', 'Clear Log')
        target = self.generate(
            include_parameters=False,
            command_specs=[command],
        )
        project = target / 'SeparationPlugin'
        viewmodel = (project / 'SeparationPluginViewModel.cs').read_text(encoding='utf-8')
        view_path = project / 'SeparationPluginView.xaml'
        view = view_path.read_text(encoding='utf-8')

        self.assertIn('public ICommand ClearLogCommand', viewmodel)
        self.assertIn('new DelegateCommand(this.OnClearLog)', viewmodel)
        self.assertIn('private void OnClearLog()', viewmodel)
        self.assertIn('Command="{Binding ClearLogCommand}"', view)
        ET.parse(view_path)

    def test_command_can_omit_view_button(self):
        command = build_command_spec('InternalRefresh', include_button=False)
        target = self.generate(
            behavior=BEHAVIOR_CURRENT_VALUE,
            library_project=str(LIBRARY_PROJECT),
            command_specs=[command],
        )
        project = target / 'SeparationPlugin'
        viewmodel = (project / 'SeparationPluginViewModel.cs').read_text(encoding='utf-8')
        view = (project / 'SeparationPluginView.xaml').read_text(encoding='utf-8')

        self.assertIn('InternalRefreshCommand', viewmodel)
        self.assertNotIn('InternalRefreshCommand', view)


if __name__ == '__main__':
    unittest.main()
