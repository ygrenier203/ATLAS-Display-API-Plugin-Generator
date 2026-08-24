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
		choices=('current-value', 'visible-range', 'current-and-range', 'compare-sessions', 'basic'),
		default='current-value',
		help='plugin behavior: cursor values, visible-range data, compare sessions, or a basic display',
	)
	parser.add_argument('--no-parameters', action='store_true', help=argparse.SUPPRESS)
	parser.add_argument(
		'--atlas-parameter',
		action='append',
		default=[],
		help='ATLAS parameter identifier to add; repeat for multiple parameters',
	)
	parser.add_argument(
		'--command',
		action='append',
		default=[],
		help='command to generate with a default view button; repeat for multiple commands',
	)
	parser.add_argument('--max-parameters', type=int, default=100, help='maximum number of display parameters')
	parser.add_argument('--build', action='store_true', help='build and validate the generated solution without deploying it')
	parser.add_argument('--status-state', action='store_true', help='generate IsBusy, StatusMessage, and ErrorMessage properties')
	parser.add_argument('--lifecycle-hooks', action='store_true', help='generate initialization, visibility, and cleanup overrides')
	parser.add_argument('--session-notifications', action='store_true', help='generate session loaded, unloaded, and set-change overrides')
	parser.add_argument('--item-collection', action='store_true', help='generate a starter Items collection for a basic display')
	parser.add_argument('--clear-settings', action='store_true', help='clear persisted paths used by the generator and exit')
	options = parser.parse_args(args)

	from .gui import (
		BEHAVIOR_BASIC,
		BEHAVIOR_COMPARE_SESSIONS,
		BEHAVIOR_CURRENT_AND_RANGE,
		BEHAVIOR_CURRENT_VALUE,
		BEHAVIOR_VISIBLE_RANGE,
		build_generated_plugin,
		build_command_spec,
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
		'current-and-range': BEHAVIOR_CURRENT_AND_RANGE,
		'compare-sessions': BEHAVIOR_COMPARE_SESSIONS,
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
		parser.error('--atlas-parameter requires a data behavior.')
	if options.item_collection and behavior != BEHAVIOR_BASIC:
		parser.error('--item-collection requires --behavior basic.')
	if not icon_path:
		parser.error('--icon is required on first use. Choose the PNG icon for the plugin.')
	command_specs = []
	command_names = set()
	for command_name in options.command:
		try:
			command_spec = build_command_spec(command_name, existing_names=command_names)
		except ValueError as error:
			parser.error(str(error))
		command_specs.append(command_spec)
		command_names.add(command_spec['name'])
	target = generate_plugin(
		options.name,
		output,
		include_view=not options.no_view,
		include_parameters=include_parameters,
		behavior=behavior,
		atlas_parameters=options.atlas_parameter,
		command_specs=command_specs,
		include_status_state=options.status_state,
		include_lifecycle_hooks=options.lifecycle_hooks,
		include_session_notifications=options.session_notifications,
		include_item_collection=options.item_collection,
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
	if options.build:
		build_generated_plugin(target)
		print('Build validation succeeded.')
	print(f'Plugin created at: {target}')


if __name__ == '__main__':
	run()
