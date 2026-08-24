import tempfile
import unittest
from pathlib import Path

from tools.PluginGenerator.gui import (
    BEHAVIOR_BASIC,
    BEHAVIOR_CURRENT_AND_RANGE,
    BEHAVIOR_CURRENT_VALUE,
    BEHAVIOR_VISIBLE_RANGE,
    behavior_uses_parameters,
    build_atlas_parameter,
    build_display_property,
    build_display_property_spec,
    generate_plugin,
)


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

    def test_atlas_identifier_accepts_colons(self):
        self.assertEqual('vCar:Chassis', build_atlas_parameter(' vCar:Chassis '))

    def test_atlas_identifier_rejects_duplicates(self):
        with self.assertRaisesRegex(ValueError, 'already exists'):
            build_atlas_parameter('vCar:Chassis', {'vCar:Chassis'})

    def test_display_property_requires_csharp_identifier(self):
        with self.assertRaisesRegex(ValueError, 'valid C# identifier'):
            build_display_property_spec('vCar:Chassis')

    def test_display_property_preserves_pascal_case(self):
        spec = build_display_property_spec('FontSize', persisted=True)
        source = build_display_property(spec)

        self.assertIn('public string FontSize', source)
        self.assertNotIn('Fontsize', source)
        self.assertIn('ReadProperty("FontSize")', source)
        self.assertIn('SaveProperty(value)', source)


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


if __name__ == '__main__':
    unittest.main()
