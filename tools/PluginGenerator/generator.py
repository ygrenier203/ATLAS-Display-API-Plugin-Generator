import argparse
import os


def run(args=None):
	parser = argparse.ArgumentParser(description='Generate an ATLAS display plugin.')
	parser.add_argument('name', nargs='?', help='plugin name; omit to open the GUI')
	parser.add_argument('--output', help='parent folder for the generated plugin; required until configured')
	parser.add_argument('--library-project', help='path to DisplayPluginLibrary.csproj; required for data plugins until configured')
	parser.add_argument('--icon', help='path to the plugin PNG icon; required until configured')
	parser.add_argument('--no-view', action='store_true', help='omit the WPF view files')
	parser.add_argument(
		'--behavior',
		choices=('current-value', 'visible-range', 'basic'),
		default='current-value',
		help='plugin behavior: cursor values, visible time-range data, or a basic display',
	)
	parser.add_argument('--no-parameters', action='store_true', help=argparse.SUPPRESS)
	parser.add_argument(
		'--atlas-parameter',
		action='append',
		default=[],
		help='ATLAS parameter identifier to add; repeat for multiple parameters',
	)
	parser.add_argument('--max-parameters', type=int, default=100, help='maximum number of display parameters')
	parser.add_argument('--clear-settings', action='store_true', help='clear persisted paths used by the generator and exit')
	options = parser.parse_args(args)

	from .gui import (
		BEHAVIOR_BASIC,
		BEHAVIOR_CURRENT_VALUE,
		BEHAVIOR_VISIBLE_RANGE,
		clear_settings,
		default_output_folder,
		default_workspace_root,
		generate_plugin,
		load_settings,
		main,
		save_settings,
	)

	if options.clear_settings:
		clear_settings()
		print('Persisted generator settings cleared.')
		return

	if not options.name:
		main()
		return

	settings = load_settings()
	behavior_map = {
		'current-value': BEHAVIOR_CURRENT_VALUE,
		'visible-range': BEHAVIOR_VISIBLE_RANGE,
		'basic': BEHAVIOR_BASIC,
	}
	behavior = BEHAVIOR_BASIC if options.no_parameters else behavior_map[options.behavior]
	include_parameters = behavior != BEHAVIOR_BASIC
	output = options.output or settings.get('output_folder') or default_output_folder()
	library_project = options.library_project or settings.get('library_project', '')
	icon_path = options.icon or settings.get('icon_path', '')
	if not output:
		parser.error('--output is required on first use. Choose the parent folder for the generated plugin.')
	if include_parameters and not library_project:
		parser.error('--library-project is required for current-value plugins on first use.')
	if not include_parameters and options.atlas_parameter:
		parser.error('--atlas-parameter requires --behavior current-value or visible-range.')
	if not icon_path:
		parser.error('--icon is required on first use. Choose the PNG icon for the plugin.')
	target = generate_plugin(
		options.name,
		output,
		include_view=not options.no_view,
		include_parameters=include_parameters,
		behavior=behavior,
		atlas_parameters=options.atlas_parameter,
		parameter_max_count=options.max_parameters,
		workspace_root=default_workspace_root(),
		library_project=library_project,
		icon_path=icon_path,
	)
	save_settings({
		'output_folder': output,
		'library_project': library_project,
		'icon_path': icon_path,
	})
	print(f'Plugin created at: {target}')


if __name__ == '__main__':
	run()
